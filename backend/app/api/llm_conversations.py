"""LLM conversation API routes."""

import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import LLM_001, LLM_005, AppException, NotFoundException
from app.core.redis import get_redis
from app.models.file import UploadedFile
from app.models.llm import LLMModelConfig
from app.schemas.llm import ConversationHistoryResponse, ConversationResponse, CreateConversationRequest, LLMMessageResponse, SendMessageRequest
from app.services.auth.dependencies import get_current_user
from app.services.llm.adapters.base import AllModelsUnavailableException, LLMRequest
from app.services.llm.conversation import ConversationManager
from app.services.llm.gateway import LLMGateway
from app.services.llm.memory import MemoryService
from app.services.llm.prompt_engine import PromptTemplateEngine
from app.services.llm.security import LLMSecurityFilter
from app.services.llm.token_monitor import TokenMonitorService

router = APIRouter()


async def _get_primary_model_config(db: AsyncSession) -> LLMModelConfig | None:
    result = await db.execute(
        select(LLMModelConfig).where(LLMModelConfig.status == "active").order_by(LLMModelConfig.priority).limit(1)
    )
    return result.scalar_one_or_none()


async def _load_file_context(db: AsyncSession, user_id: int, file_ids: list[int]) -> str:
    if not file_ids:
        return ""
    result = await db.execute(
        select(UploadedFile).where(
            UploadedFile.id.in_(file_ids),
            UploadedFile.user_id == user_id,
            UploadedFile.process_status == "completed",
        )
    )
    parts: list[str] = []
    for uploaded_file in result.scalars().all():
        file_parts = [f"--- File: {uploaded_file.original_name} ({uploaded_file.file_type}) ---"]
        if uploaded_file.image_description:
            file_parts.append(f"Image description: {uploaded_file.image_description}")
        if uploaded_file.ocr_text:
            file_parts.append(f"OCR text: {uploaded_file.ocr_text}")
        if uploaded_file.extracted_content:
            file_parts.append(f"Content: {uploaded_file.extracted_content}")
        parts.append("\n".join(file_parts))
    return "\n\n".join(parts)


def _message_response(message, content: str | None = None) -> LLMMessageResponse:
    return LLMMessageResponse(
        message_id=message.id,
        role=message.role,
        content=message.content if content is None else content,
        sources=message.sources or [],
        relevance_score=message.relevance_score,
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens,
    )


async def _build_prompt(
    db: AsyncSession,
    redis: aioredis.Redis,
    manager: ConversationManager,
    conversation_id: int,
    user_id: int,
    content: str,
    file_ids: list[int],
) -> tuple[str, int]:
    model_config = await _get_primary_model_config(db)
    context_window = model_config.context_window if model_config else 8192
    max_tokens = model_config.max_tokens if model_config else 4096
    provider = model_config.provider if model_config else "openai"

    context_messages, memory_context = await manager.build_prompt_context_with_memory(
        conversation_id=conversation_id,
        user_id=user_id,
        current_query=content,
        model_max_tokens=context_window,
    )
    conversation_history = "\n".join(f"{item['role']}: {item['content']}" for item in context_messages[-20:])
    file_context = await _load_file_context(db, user_id, file_ids)

    prompt_engine = PromptTemplateEngine(db=db)
    template_id = await prompt_engine.match_template(content)
    system_prompt = await prompt_engine.get_system_prompt(template_id)
    allocation = await manager.build_prompt_with_budget(
        conversation_id=conversation_id,
        user_id=user_id,
        current_query=content,
        system_prompt=system_prompt,
        model_context_window=context_window,
        max_output_tokens=max_tokens,
        provider=provider,
        rag_docs="",
        file_context=file_context,
        tools_prompt="",
    )
    if memory_context or conversation_history:
        prompt = f"{allocation.prompt}\n\nMemory context:\n{memory_context}\n\nRecent conversation:\n{conversation_history}"
    else:
        prompt = allocation.prompt
    return prompt, allocation.available_output_tokens


async def _save_memory_safe(
    db: AsyncSession,
    redis: aioredis.Redis,
    user_id: int,
    question: str,
    answer: str,
    conversation_id: int,
    message_id: int,
) -> None:
    try:
        await MemoryService(db=db, redis=redis).save_memory(
            user_id=user_id,
            question=question,
            answer=answer,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    except Exception:
        return


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    manager = ConversationManager(db=db, redis=redis)
    conversation = await manager.create_conversation(user_id=current_user["user_id"], title=request.title)
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        model_id=conversation.model_id,
        total_input_tokens=conversation.total_input_tokens,
        total_output_tokens=conversation.total_output_tokens,
        created_at=conversation.created_at,
    )


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = current_user["user_id"]
    department_id = current_user.get("department_id") or 0
    manager = ConversationManager(db=db, redis=redis)
    conversation = await manager.get_conversation(conversation_id, user_id)
    if not conversation:
        raise NotFoundException(LLM_005)

    security = LLMSecurityFilter(db=db, redis=redis)
    await security.check_prompt_injection(request.content, user_id)
    await security.check_rate_limit(user_id)
    token_monitor = TokenMonitorService(db=db, redis=redis)
    await token_monitor.check_quota(user_id, department_id)

    await manager.add_message(conversation_id, role="user", content=request.content)
    prompt, max_tokens = await _build_prompt(db, redis, manager, conversation_id, user_id, request.content, request.file_ids)
    sanitized_prompt = security.sanitize_outbound(prompt)
    gateway = LLMGateway(db=db, redis=redis)
    llm_request = LLMRequest(prompt=sanitized_prompt, max_tokens=max_tokens, stream=request.stream)

    if request.stream:
        async def event_generator():
            full_content = ""
            model_id = ""
            try:
                iterator, model_id = await gateway.stream_generate(llm_request)
                async for token in iterator:
                    full_content += token
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                filtered_content = security.filter_output(full_content)
                output_tokens = max(1, len(filtered_content) // 4)
                input_tokens = max(1, len(sanitized_prompt) // 4)
                message = await manager.add_message(
                    conversation_id,
                    role="assistant",
                    content=filtered_content,
                    model_id=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                await token_monitor.record_usage(
                    user_id=user_id,
                    department_id=department_id,
                    model_id=model_id or "unknown",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    conversation_id=conversation_id,
                    request_type="chat",
                )
                await _save_memory_safe(db, redis, user_id, request.content, filtered_content, conversation_id, message.id)
                await db.commit()
                yield f"data: {json.dumps({'done': True, 'message_id': message.id}, ensure_ascii=False)}\n\n"
            except AllModelsUnavailableException:
                yield f"data: {json.dumps({'error': 'LLM service unavailable'}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        response = await gateway.generate(llm_request)
    except AllModelsUnavailableException:
        raise AppException(LLM_001, status_code=503)

    filtered_content = security.filter_output(response.content)
    message = await manager.add_message(
        conversation_id,
        role="assistant",
        content=filtered_content,
        model_id=response.model_id,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    await token_monitor.record_usage(
        user_id=user_id,
        department_id=department_id,
        model_id=response.model_id or "unknown",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        conversation_id=conversation_id,
        request_type="chat",
    )
    await _save_memory_safe(db, redis, user_id, request.content, filtered_content, conversation_id, message.id)
    return _message_response(message, filtered_content)


@router.post("/{conversation_id}/regenerate", response_model=LLMMessageResponse)
async def regenerate(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = current_user["user_id"]
    manager = ConversationManager(db=db, redis=redis)
    conversation = await manager.get_conversation(conversation_id, user_id)
    if not conversation:
        raise NotFoundException(LLM_005)
    history = await manager.get_conversation_history(conversation_id, page=1, page_size=100)
    last_user_message = next((message for message in reversed(history) if message.role == "user"), None)
    if not last_user_message:
        raise AppException(LLM_005, status_code=400)

    security = LLMSecurityFilter(db=db, redis=redis)
    prompt, max_tokens = await _build_prompt(db, redis, manager, conversation_id, user_id, last_user_message.content, [])
    gateway = LLMGateway(db=db, redis=redis)
    try:
        response = await gateway.generate(LLMRequest(prompt=security.sanitize_outbound(prompt), max_tokens=max_tokens, stream=False))
    except AllModelsUnavailableException:
        raise AppException(LLM_001, status_code=503)

    filtered = security.filter_output(response.content)
    message = await manager.add_message(
        conversation_id,
        role="assistant",
        content=filtered,
        model_id=response.model_id,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    await TokenMonitorService(db=db, redis=redis).record_usage(
        user_id=user_id,
        department_id=current_user.get("department_id") or 0,
        model_id=response.model_id or "unknown",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        conversation_id=conversation_id,
        request_type="chat",
    )
    return _message_response(message, filtered)


@router.get("/{conversation_id}/messages", response_model=ConversationHistoryResponse)
async def get_history(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    manager = ConversationManager(db=db, redis=redis)
    conversation = await manager.get_conversation(conversation_id, current_user["user_id"])
    if not conversation:
        raise NotFoundException(LLM_005)
    messages = await manager.get_conversation_history(conversation_id)
    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        messages=[_message_response(message) for message in messages],
        total_tokens=conversation.total_input_tokens + conversation.total_output_tokens,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    manager = ConversationManager(db=db, redis=redis)
    conversation = await manager.get_conversation(conversation_id, current_user["user_id"])
    if not conversation:
        raise NotFoundException(LLM_005)
    await manager.delete_conversation(conversation_id)
