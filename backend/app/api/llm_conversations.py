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

    # ===== 意图识别（增强版）=====
    from app.services.llm.intent import IntentResolver
    from app.services.llm.intent.classifier import IntentCategory, ConfidenceLevel
    from app.services.llm.tools.executor import SmartToolRouter

    intent_resolver = IntentResolver(db=db, redis=redis)
    plan = await intent_resolver.resolve(request.content, context_messages)

    # 根据执行计划决定工具策略
    tool_router = SmartToolRouter()
    pre_result = None
    tools_prompt = ""

    if plan.pre_execute_tools:
        # 高置信度预执行
        for tool_spec in plan.pre_execute_tools:
            result = await tool_router.executor.execute_tool(
                tool_spec["tool"], **tool_spec["params"]
            )
            if result and "error" not in result:
                pre_result = {
                    "tool": tool_spec["tool"],
                    "result": result,
                    "context_injection": str(result),
                }
                break
        tools_prompt = tool_router.build_enhanced_prompt(request.content, pre_result)
    elif plan.should_inject_tools:
        # 中/低置信度：注入相关工具描述让 LLM 自主决定
        from app.services.llm.tools.intent_matcher import intent_matcher
        tools_prompt = intent_matcher.get_relevant_tools_prompt(
            plan.intent_result.rewritten_query or request.content
        )

    # 构建 Prompt 附加指令
    extra_instructions = "\n".join(plan.prompt_additions) if plan.prompt_additions else ""

    # 匹配 Prompt 模板并渲染
    prompt_engine = PromptTemplateEngine(db=db)
    template_id = await prompt_engine.match_template(request.content)
    prompt = await prompt_engine.render(template_id, {
        "user_query": plan.intent_result.rewritten_query or request.content,
        "context_docs": "" if not plan.should_use_rag else "",
        "memory_context": memory_context,
        "tools_prompt": tools_prompt + ("\n" + extra_instructions if extra_instructions else ""),
        "conversation_history": "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
            for m in context_messages[-10:]
        ),
        "current_time": "",
    })

    # ===== 判断是否使用 ReAct 循环 =====
    from app.services.llm.intent.resolver import ExecutionPath
    use_react = plan.path in (
        ExecutionPath.TOOL_LLM_CALL,
        ExecutionPath.MULTI_STEP,
        ExecutionPath.LLM_FALLBACK,
    ) and plan.should_inject_tools and not pre_result

    if use_react and not request.stream:
        # 使用 ReAct Agent 循环推理（非流式）
        from app.services.llm.react import ReActAgent, ReActConfig
        react_config = ReActConfig(
            max_iterations=5,
            quality_threshold=0.8,
            enable_self_check=True,
            timeout_seconds=60,
        )
        react_agent = ReActAgent(db=db, redis=redis, config=react_config)
        react_result = await react_agent.run(
            query=plan.intent_result.rewritten_query or request.content,
            context=memory_context,
            tools_prompt=tools_prompt,
        )

        # 输出过滤
        filtered_content = security.filter_output(react_result.final_answer)

        # 保存助手消息
        msg = await manager.add_message(
            conversation_id,
            role="assistant",
            content=filtered_content,
            model_id=react_result.model_id,
            input_tokens=react_result.total_input_tokens,
            output_tokens=react_result.total_output_tokens,
        )

        # 记录 Token 用量
        await token_monitor.record_usage(
            user_id=user_id,
            department_id=department_id,
            model_id=react_result.model_id or "unknown",
            input_tokens=react_result.total_input_tokens,
            output_tokens=react_result.total_output_tokens,
            conversation_id=conversation_id,
        )

        # 写入记忆
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
            pass

        return LLMMessageResponse(
            message_id=msg.id,
            role="assistant",
            content=filtered_content,
            input_tokens=react_result.total_input_tokens,
            output_tokens=react_result.total_output_tokens,
        )

    elif use_react and request.stream:
        # 使用 ReAct Agent 流式输出推理过程
        from app.services.llm.react import ReActAgent, ReActConfig

        async def react_event_generator():
            react_config = ReActConfig(max_iterations=5, quality_threshold=0.8, timeout_seconds=60)
            react_agent = ReActAgent(db=db, redis=redis, config=react_config)

            try:
                async for event in react_agent.run_stream(
                    query=plan.intent_result.rewritten_query or request.content,
                    context=memory_context,
                    tools_prompt=tools_prompt,
                ):
                    if event["type"] == "thought":
                        yield f"data: {json.dumps({'type': 'thought', 'content': event['content'], 'iteration': event['iteration']})}\n\n"
                    elif event["type"] == "action":
                        yield f"data: {json.dumps({'type': 'action', 'tool': event['tool'], 'iteration': event['iteration']})}\n\n"
                    elif event["type"] == "observation":
                        yield f"data: {json.dumps({'type': 'observation', 'content': event['content'], 'iteration': event['iteration']})}\n\n"
                    elif event["type"] == "final_answer":
                        final_content = security.filter_output(event["content"])

                        msg = await manager.add_message(
                            conversation_id, role="assistant", content=final_content,
                            output_tokens=len(final_content) // 2,
                        )
                        await token_monitor.record_usage(
                            user_id=user_id, department_id=department_id,
                            model_id="react", input_tokens=0,
                            output_tokens=len(final_content) // 2,
                            conversation_id=conversation_id,
                        )
                        try:
                            from app.services.llm.memory import MemoryService
                            memory_service = MemoryService(db=db, redis=redis)
                            await memory_service.save_memory(
                                user_id=user_id, question=request.content,
                                answer=final_content, conversation_id=conversation_id,
                                message_id=msg.id,
                            )
                        except Exception:
                            pass

                        await db.commit()
                        yield f"data: {json.dumps({'type': 'final_answer', 'content': final_content, 'done': True, 'message_id': msg.id, 'iterations': event['iterations'], 'exit_reason': event['exit_reason']})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            react_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ===== 非 ReAct 路径：原有单次调用逻辑 =====

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
