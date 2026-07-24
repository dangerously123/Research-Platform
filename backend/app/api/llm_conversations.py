"""LLM 对话 API 路由。"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.errors import LLM_001, LLM_005, AppException, NotFoundException
from app.core.redis import get_redis
from app.schemas.llm import (
    ConversationHistoryResponse,
    ConversationResponse,
    CreateConversationRequest,
    LLMMessageResponse,
    SendMessageRequest,
)
from app.services.auth.dependencies import get_current_user
from app.services.llm.adapters.base import AllModelsUnavailableException, LLMRequest
from app.services.llm.conversation import ConversationManager
from app.services.llm.gateway import LLMGateway
from app.services.llm.prompt_engine import PromptTemplateEngine
from app.services.llm.security import LLMSecurityFilter
from app.services.llm.token_monitor import TokenMonitorService

router = APIRouter()


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """创建新对话。"""
    manager = ConversationManager(db=db, redis=redis)
    conv = await manager.create_conversation(
        user_id=current_user["user_id"],
        title=request.title,
    )
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        model_id=conv.model_id,
        total_input_tokens=conv.total_input_tokens,
        total_output_tokens=conv.total_output_tokens,
        created_at=conv.created_at,
    )


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """发送消息并获取 LLM 回答。支持 SSE 流式响应。"""
    user_id = current_user["user_id"]
    department_id = current_user.get("department_id", 0)

    # 验证会话
    manager = ConversationManager(db=db, redis=redis)
    conv = await manager.get_conversation(conversation_id, user_id)
    if not conv:
        raise NotFoundException(LLM_005)

    # 安全检查
    security = LLMSecurityFilter(db=db, redis=redis)
    await security.check_prompt_injection(request.content, user_id)
    await security.check_rate_limit(user_id)

    # 配额检查
    token_monitor = TokenMonitorService(db=db, redis=redis)
    await token_monitor.check_quota(user_id, department_id)

    # 保存用户消息
    await manager.add_message(conversation_id, role="user", content=request.content)

    # 构建上下文（含长期记忆检索）
    context_messages, memory_context = await manager.build_prompt_context_with_memory(
        conversation_id=conversation_id,
        user_id=user_id,
        current_query=request.content,
    )

    # 意图匹配：只注入相关工具描述（而非全部工具）
    from app.services.llm.tools.intent_matcher import intent_matcher
    from app.services.llm.tools.executor import SmartToolRouter

    # 两阶段工具调用：先尝试预执行
    tool_router = SmartToolRouter()
    pre_result = await tool_router.pre_execute(request.content)
    tools_prompt = tool_router.build_enhanced_prompt(request.content, pre_result)

    # 匹配 Prompt 模板并渲染
    prompt_engine = PromptTemplateEngine(db=db)
    template_id = await prompt_engine.match_template(request.content)
    prompt = await prompt_engine.render(template_id, {
        "user_query": request.content,
        "context_docs": "",  # RAG 检索结果由上层填充
        "memory_context": memory_context,
        "tools_prompt": tools_prompt,
        "conversation_history": "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
            for m in context_messages[-10:]
        ),
        "current_time": "",
    })

    # 调用 LLM
    gateway = LLMGateway(db=db, redis=redis)
    llm_request = LLMRequest(prompt=prompt, stream=request.stream)

    if request.stream:
        # 流式响应
        async def event_generator():
            try:
                iterator, model_id = await gateway.stream_generate(llm_request)
                full_content = ""
                async for token in iterator:
                    full_content += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

                # 保存助手消息
                msg = await manager.add_message(
                    conversation_id,
                    role="assistant",
                    content=full_content,
                    model_id=model_id,
                    output_tokens=len(full_content) // 2,
                )

                # 记录 Token 用量
                await token_monitor.record_usage(
                    user_id=user_id,
                    department_id=department_id,
                    model_id=model_id,
                    input_tokens=len(prompt) // 2,
                    output_tokens=len(full_content) // 2,
                    conversation_id=conversation_id,
                )

                # 异步写入长期记忆
                try:
                    from app.services.llm.memory import MemoryService
                    memory_service = MemoryService(db=db, redis=redis)
                    await memory_service.save_memory(
                        user_id=user_id,
                        question=request.content,
                        answer=full_content,
                        conversation_id=conversation_id,
                        message_id=msg.id,
                    )
                except Exception:
                    pass

                await db.commit()

                yield f"data: {json.dumps({'done': True, 'message_id': msg.id})}\n\n"
            except AllModelsUnavailableException:
                yield f"data: {json.dumps({'error': 'LLM 服务暂时不可用'})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        # 非流式
        try:
            response = await gateway.generate(llm_request)
        except AllModelsUnavailableException:
            raise AppException(LLM_001, status_code=503)

        # 输出过滤
        filtered_content = security.filter_output(response.content)

        # 后执行阶段：处理 LLM 回答中的工具调用
        if tool_router.executor.has_tool_calls(filtered_content):
            filtered_content, _tool_log = await tool_router.post_execute(filtered_content)

        # 保存助手消息
        msg = await manager.add_message(
            conversation_id,
            role="assistant",
            content=filtered_content,
            model_id=response.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        # 记录 Token 用量
        await token_monitor.record_usage(
            user_id=user_id,
            department_id=department_id,
            model_id=response.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            conversation_id=conversation_id,
        )

        # 异步写入长期记忆
        try:
            from app.services.llm.memory import MemoryService
            memory_service = MemoryService(db=db, redis=redis)
            await memory_service.save_memory(
                user_id=user_id,
                question=request.content,
                answer=filtered_content,
                conversation_id=conversation_id,
                message_id=msg.id,
            )
        except Exception:
            pass  # 记忆写入失败不影响正常回答

        return LLMMessageResponse(
            message_id=msg.id,
            role="assistant",
            content=filtered_content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


@router.post("/{conversation_id}/regenerate", response_model=LLMMessageResponse)
async def regenerate(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """重新生成最后一条回答。"""
    user_id = current_user["user_id"]

    manager = ConversationManager(db=db, redis=redis)
    conv = await manager.get_conversation(conversation_id, user_id)
    if not conv:
        raise NotFoundException(LLM_005)

    # 获取最后一条用户消息
    history = await manager.get_conversation_history(conversation_id, page=1, page_size=100)
    last_user_msg = None
    for msg in reversed(history):
        if msg.role == "user":
            last_user_msg = msg
            break

    if not last_user_msg:
        raise AppException(LLM_005, status_code=400)

    # 重新调用 LLM
    prompt_engine = PromptTemplateEngine(db=db)
    template_id = await prompt_engine.match_template(last_user_msg.content)
    prompt = await prompt_engine.render(template_id, {
        "user_query": last_user_msg.content,
        "context_docs": "",
        "conversation_history": "",
        "current_time": "",
    })

    gateway = LLMGateway(db=db, redis=redis)
    try:
        response = await gateway.generate(LLMRequest(prompt=prompt, stream=False))
    except AllModelsUnavailableException:
        raise AppException(LLM_001, status_code=503)

    security = LLMSecurityFilter(db=db, redis=redis)
    filtered = security.filter_output(response.content)

    msg = await manager.add_message(
        conversation_id,
        role="assistant",
        content=filtered,
        model_id=response.model_id,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )

    # 记录用量
    token_monitor = TokenMonitorService(db=db, redis=redis)
    await token_monitor.record_usage(
        user_id=user_id,
        department_id=current_user.get("department_id", 0),
        model_id=response.model_id,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        conversation_id=conversation_id,
        request_type="regenerate",
    )

    return LLMMessageResponse(
        message_id=msg.id,
        role="assistant",
        content=filtered,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


@router.get("/{conversation_id}/messages", response_model=ConversationHistoryResponse)
async def get_history(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取会话历史。"""
    manager = ConversationManager(db=db, redis=redis)
    conv = await manager.get_conversation(conversation_id, current_user["user_id"])
    if not conv:
        raise NotFoundException(LLM_005)

    messages = await manager.get_conversation_history(conversation_id)
    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        messages=[
            LLMMessageResponse(
                message_id=m.id,
                role=m.role,
                content=m.content,
                sources=m.sources or [],
                relevance_score=m.relevance_score,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
            )
            for m in messages
        ],
        total_tokens=conv.total_input_tokens + conv.total_output_tokens,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """删除会话。"""
    manager = ConversationManager(db=db, redis=redis)
    conv = await manager.get_conversation(conversation_id, current_user["user_id"])
    if not conv:
        raise NotFoundException(LLM_005)
    await manager.delete_conversation(conversation_id)
