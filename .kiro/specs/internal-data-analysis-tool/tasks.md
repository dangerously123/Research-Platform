# Implementation Plan: 内部数据分析工具

## Overview

基于 Vue 3 + FastAPI 微服务架构实现内部数据分析工具，包括 RAG 知识检索、LLM 智能体问答、数据报表分析、RBAC 权限管理、用户认证、数据安全、LLM 服务层与部署配置。按服务模块渐进式构建，优先完成核心基础设施（认证、权限），再构建业务功能（RAG、报表），接着实现 LLM 服务层（网关、对话管理、Prompt 模板、Token 监控、安全），最后集成前端和部署配置。

## Tasks

- [ ] 1. 项目基础架构搭建
  - [ ] 1.1 初始化后端项目结构与公共模块
    - 创建 FastAPI 项目骨架：目录结构（app/services/auth, app/services/rag, app/services/report, app/services/permission, app/services/security, app/services/llm, app/core, app/models, app/schemas, app/api）
    - 配置 SQLAlchemy 2.0 数据库连接、Pydantic Settings 环境变量管理
    - 实现统一错误响应格式（ErrorResponse）和错误代码常量（AUTH_001~LLM_008）
    - 配置 Redis 连接池（aioredis）
    - 创建 Alembic 数据库迁移初始化配置
    - _Requirements: 7.2, 7.3, 7.5_

  - [ ] 1.2 初始化前端项目结构
    - 使用 Vite 创建 Vue 3 + TypeScript 项目
    - 配置 Pinia 状态管理、Vue Router 路由、Axios HTTP 客户端（带拦截器处理 Token 刷新和错误响应）
    - 集成 Element Plus UI 组件库
    - 创建基础布局组件（侧边栏、顶栏、内容区）
    - _Requirements: 7.1, 7.5_

  - [ ] 1.3 创建数据库表结构迁移脚本
    - 编写 Alembic 迁移脚本，创建 users、roles、permissions、user_roles、departments、audit_logs、permission_change_logs、security_alerts、report_configs、export_tasks 全部表
    - _Requirements: 7.3_

- [ ] 2. 用户认证与身份管理服务
  - [ ] 2.1 实现用户模型与认证核心逻辑
    - 创建 SQLAlchemy User/Role/UserRole 模型
    - 实现密码哈希（bcrypt）和验证函数
    - 实现 JWT 令牌签发与验证（python-jose），包含 user_id、roles、exp 字段
    - 实现 SessionManager 类：登录认证、会话验证、活跃时间刷新
    - _Requirements: 4.1, 4.3_

  - [ ] 2.2 实现登录失败锁定机制
    - 使用 Redis 记录登录失败次数（key: login:attempts:{username}, TTL=60s）
    - 实现连续 5 次失败后锁定账号 15 分钟逻辑
    - 登录成功后重置失败计数
    - _Requirements: 4.4_

  - [ ] 2.3 实现会话超时管理
    - Redis 存储会话信息（key: session:{token_id}, TTL=30min）
    - 实现 30 分钟无操作自动终止会话逻辑
    - 每次有效请求刷新活跃时间
    - _Requirements: 4.5_

  - [ ] 2.4 实现认证 API 端点
    - POST /api/v1/auth/login - 登录
    - POST /api/v1/auth/logout - 登出（删除 Redis 会话）
    - GET /api/v1/auth/me - 获取当前用户信息和权限
    - 实现 FastAPI 依赖注入中间件：get_current_user（验证 Token 和会话有效性）
    - _Requirements: 4.1, 4.3_

  - [ ]* 2.5 编写认证模块属性测试
    - **Property 7: 认证令牌的有效性边界** - 验证过期令牌被拒绝
    - **Property 8: 登录失败锁定机制** - 验证 5 次失败锁定、少于 5 次不锁定
    - **Property 9: 会话超时终止** - 验证 30 分钟无操作后会话终止
    - **Validates: Requirements 4.3, 4.4, 4.5**

- [ ] 3. RBAC 权限管理服务
  - [ ] 3.1 实现权限模型与权限计算器
    - 创建 SQLAlchemy Role/Permission/Department 模型
    - 实现 PermissionCalculator 类：多角色权限合并，最高权限优先原则
    - 实现 Redis 权限缓存（key: perm:user:{user_id}, TTL=5min）
    - _Requirements: 3.4, 3.7_

  - [ ] 3.2 实现角色 CRUD API
    - GET /api/v1/roles - 获取角色列表
    - POST /api/v1/roles - 创建角色（含权限定义）
    - PUT /api/v1/roles/{role_id} - 更新角色
    - DELETE /api/v1/roles/{role_id} - 删除角色（检查是否有用户关联）
    - _Requirements: 3.1_

  - [ ] 3.3 实现用户角色分配与有效权限查询
    - POST /api/v1/users/{user_id}/roles - 分配角色
    - DELETE /api/v1/users/{user_id}/roles/{role_id} - 移除角色
    - GET /api/v1/users/{user_id}/effective-permissions - 查询有效权限
    - 角色变更时清除 Redis 权限缓存，确保即时生效
    - _Requirements: 3.2, 3.3, 3.4_

  - [ ] 3.4 实现权限中间件与数据过滤
    - 创建 FastAPI 依赖：check_permission(resource_type, resource_id, required_level)
    - 无角色用户访问业务资源时返回 PERM_001 错误
    - _Requirements: 3.5_

  - [ ]* 3.5 编写权限模块属性测试
    - **Property 3: 角色 CRUD 的数据一致性（Round-trip）** - 创建后读取应一致
    - **Property 4: 有效权限计算的最高优先原则** - 多角色合并取最高
    - **Property 5: 无角色用户的访问拒绝** - 无角色时拒绝所有业务访问
    - **Property 15: 角色分配即时生效** - 分配后立即查询包含新权限
    - **Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.7**

- [ ] 4. Checkpoint - 核心认证与权限验证
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. 数据安全服务
  - [ ] 5.1 实现数据加密模块
    - 实现 DataEncryptor 类：AES-256-GCM 加密/解密
    - 创建加密字段类型（SQLAlchemy TypeDecorator），透明加解密敏感字段
    - _Requirements: 5.1_

  - [ ] 5.2 实现审计日志模块
    - 实现 AuditLogger 类：log_operation 和 log_permission_change 方法
    - 创建 FastAPI 中间件：自动记录所有数据查询和导出操作的审计日志
    - 记录字段：用户身份、操作时间、操作类型、涉及数据范围、IP 地址
    - _Requirements: 5.3, 3.6_

  - [ ] 5.3 实现异常检测模块
    - 实现 AnomalyDetector 类：基于 Redis 计数的滑动窗口检测
    - 导出操作阈值：1 小时内 10 次
    - 查询操作阈值：1 小时内 200 次
    - 超阈值时创建 security_alerts 记录并通知管理员
    - _Requirements: 5.5_

  - [ ]* 5.4 编写数据安全模块属性测试
    - **Property 6: 审计日志完整性** - 操作后必须生成完整审计记录
    - **Property 10: 敏感数据加密 Round-trip** - 加密后解密应等于原始值
    - **Property 12: 异常检测阈值准确性** - 超阈值触发告警，未超不触发
    - **Validates: Requirements 5.1, 5.3, 5.5, 3.6**

- [ ] 6. LLM 相关数据库迁移
  - [ ] 6.1 创建 LLM 相关表迁移脚本
    - 编写 Alembic 迁移脚本，创建 llm_conversations、llm_messages、prompt_templates、prompt_template_versions、token_usage_records、token_quotas、llm_model_configs 七张表
    - 创建 llm_security_events 安全事件日志表
    - 定义所有外键关系、索引和枚举类型
    - _Requirements: 9.1, 10.1, 11.1, 12.1, 13.3, 16.1_

- [ ] 7. LLM 网关核心逻辑
  - [ ] 7.1 实现模型适配器层
    - 创建 ModelAdapter 抽象基类（generate、stream_generate、health_check 方法）
    - 实现 OllamaAdapter：对接 Ollama HTTP API，支持流式输出
    - 实现 VLLMAdapter：对接 vLLM OpenAI-compatible API
    - 实现 OpenAIAdapter：对接 OpenAI Chat Completions API
    - 实现 QwenAdapter：对接通义千问 DashScope API
    - 实现 WenxinAdapter：对接文心一言 ERNIE API
    - _Requirements: 10.1, 10.2, 14.1_

  - [ ] 7.2 实现模型注册中心与健康检查
    - 实现 ModelRegistry 类：从数据库加载模型配置，维护可用模型列表
    - 实现定时健康检查任务（每 30s 检测模型可用性和响应延迟）
    - 实现模型状态缓存（Redis key: llm:model:{model_id}:status, TTL=30s）
    - 实现 mark_unhealthy/mark_healthy 模型状态管理
    - _Requirements: 10.3, 10.6_

  - [ ] 7.3 实现 LLM 网关路由与 Failover
    - 实现 LLMGateway 类：统一生成接口，编排安全检查 → 频率限制 → 配额检查 → 模型路由 → 调用 → 记录流程
    - 实现 _select_model 方法：按任务类型和优先级选择最优可用模型
    - 实现 _call_with_failover 方法：首选模型失败时按优先级自动切换备选模型
    - 实现模型熔断机制（3 次失败后熔断 45s）
    - _Requirements: 10.4, 10.5, 10.7_

  - [ ] 7.4 实现 LLM 流式响应（SSE）
    - 实现 Server-Sent Events 流式输出端点
    - 各适配器的 stream_generate 方法返回 AsyncIterator[str]
    - 前端通过 EventSource 接收流式 Token
    - _Requirements: 9.4_

  - [ ]* 7.5 编写 LLM 网关属性测试
    - **Property 18: 模型 Failover 优先级遵循** - 高优先级不可用时按优先级选择下一个
    - **Property 31: 本地模型任务路由正确性** - 按任务类型选择声明支持该类型的最高优先级模型
    - **Validates: Requirements 10.4, 14.5**

- [ ] 8. 对话管理器
  - [ ] 8.1 实现对话会话生命周期管理
    - 实现 ConversationManager 类：创建会话、结束会话、归档会话
    - Redis 缓存对话上下文（key: llm:conv:{conversation_id}, TTL=24h）
    - 实现 24 小时不活跃自动归档定时任务
    - _Requirements: 11.4, 11.6_

  - [ ] 8.2 实现上下文窗口与摘要压缩
    - 实现 build_prompt_context 方法：获取最近 20 轮对话历史
    - 使用 tiktoken 计算消息列表总 Token 数
    - 实现 _compress_context 方法：当超出模型 Token 限制 60% 时，对早期对话进行摘要压缩（保留最近 5 轮完整 + 摘要更早内容）
    - 实现 ContextSummarizer：调用 LLM 生成对话摘要
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ] 8.3 实现对话消息存储与检索
    - 实现消息持久化到 llm_messages 表
    - 实现会话历史查询接口（分页加载）
    - 记录每条消息的 input_tokens、output_tokens、model_id、sources
    - 更新会话级 Token 统计（total_input_tokens、total_output_tokens）
    - _Requirements: 11.5, 9.1_

  - [ ]* 8.4 编写对话管理器属性测试
    - **Property 19: 对话上下文窗口大小约束** - 不超过 20 轮
    - **Property 20: 对话上下文 Token 限制保证** - 压缩后不超过模型 60%
    - **Property 21: 会话终止清空上下文** - 结束/归档后上下文为空
    - **Validates: Requirements 11.2, 11.3, 11.4, 11.6**

- [ ] 9. Prompt 模板引擎
  - [ ] 9.1 实现 Prompt 模板 CRUD 与版本管理
    - 实现 PromptTemplateEngine 类：创建、编辑、删除、启用/禁用模板
    - 每次编辑时自动保存版本到 prompt_template_versions 表
    - 实现版本回退功能（rollback_version 方法）
    - 实现默认模板初始化（系统内置模板）
    - _Requirements: 12.1, 12.6, 12.7_

  - [ ] 9.2 实现模板变量替换与预览
    - 实现 _substitute_variables 方法：替换 {{variable_name}} 占位符
    - 支持内置变量：user_query、context_docs、conversation_history、user_role、current_time
    - 实现模板预览接口：传入示例变量值，返回渲染后的 Prompt 及 Token 计数
    - _Requirements: 12.2, 12.3_

  - [ ] 9.3 实现模板自动匹配与场景分类
    - 实现 match_template 方法：根据问题关键词自动匹配业务场景分类（tech_doc/data_analysis/process_guide/general）
    - 实现按分类管理模板列表
    - 未配置自定义模板时回退到系统默认模板
    - _Requirements: 12.4, 12.5, 12.7_

  - [ ]* 9.4 编写 Prompt 模板属性测试
    - **Property 22: Prompt 模板变量替换完整性** - 渲染后无未替换占位符
    - **Property 23: Prompt 模板版本回退正确性** - 回退后内容与历史版本一致
    - **Validates: Requirements 12.2, 12.6**

- [ ] 10. Token 监控服务
  - [ ] 10.1 实现 Token 用量记录与费用估算
    - 实现 TokenMonitorService 类：record_usage 方法记录每次调用的 Token 数和费用
    - 实现 _estimate_cost 方法：根据模型定价计算单次费用（本地模型费用为 0）
    - 配置各模型定价表（OpenAI/通义千问/文心一言）
    - _Requirements: 16.1_

  - [ ] 10.2 实现 Token 配额管理
    - 实现配额 CRUD（按用户/部门维度设置月度 Token 上限和费用上限）
    - 实现 check_quota 方法：达到 80% 发送预警通知，达到 100% 阻止调用
    - 实现 _update_quota_counter 方法：每次调用后更新当月累计用量
    - 实现每月 1 号自动重置月度计数器的定时任务
    - _Requirements: 16.3, 16.4_

  - [ ] 10.3 实现 Token 用量统计报表与仪表盘数据
    - 实现按用户、部门、模型、时间维度的 Token 用量聚合查询
    - 实现实时仪表盘数据接口（当月 Token 用量、费用累计、模型调用次数分布、Top 用户）
    - 实现预算上限配置与非关键场景自动暂停逻辑
    - 保留 12 个月历史用量数据
    - _Requirements: 16.2, 16.5, 16.6, 16.7_

  - [ ]* 10.4 编写 Token 监控属性测试
    - **Property 28: Token 用量记录完整性** - 每次调用创建完整用量记录，费用计算正确
    - **Property 29: Token 配额执行正确性** - 80%预警、100%阻止
    - **Validates: Requirements 16.1, 16.3, 16.4**

- [ ] 11. LLM 安全模块
  - [ ] 11.1 实现 Prompt 注入检测
    - 实现 LLMSecurityFilter 类：基于正则模式匹配已知 Prompt 注入模式
    - 检测特征：ignore previous instructions、override system、你现在是一个 等
    - 高风险输入直接拒绝并记录 llm_security_events 安全事件日志
    - _Requirements: 13.1, 13.6_

  - [ ] 11.2 实现敏感信息脱敏（PII 过滤）
    - 实现 sanitize_outbound 方法：出站内容中移除手机号、身份证号、邮箱、人名等 PII
    - 实现 _filter_classified_content 方法：过滤标记为"机密"/"绝密"级别的文档内容
    - 实现 filter_output 方法：对 LLM 返回内容进行二次 PII 过滤
    - _Requirements: 13.2, 13.4, 13.7_

  - [ ] 11.3 实现 LLM 调用频率限制
    - 实现 RateLimiter 类：基于 Redis 滑动窗口计数
    - 默认限制：单用户每小时 100 次 LLM 调用
    - 超限时返回 LLM_004 错误码
    - _Requirements: 13.5_

  - [ ] 11.4 实现 API Key KMS 管理
    - 实现 APIKeyManager 类：通过 KMS 加密存储所有 LLM API Key
    - 实现 store_key/get_key/rotate_key/disable_key 方法
    - 实现定期轮换机制（管理员配置轮换周期）
    - 实现异常检测：API Key 异常使用时自动禁用并告警
    - _Requirements: 15.1, 15.3, 15.6_

  - [ ] 11.5 实现 LLM 调用审计日志与网段控制
    - 实现 LLM 调用的输入/输出审计日志记录（请求时间、用户、模型、Token 数、响应状态）
    - 实现出站网段白名单控制：仅允许 LLM 服务层网段发起外部 API 调用
    - 实现 LLM 安全事件通知管理员功能
    - _Requirements: 13.3, 15.2, 15.4, 15.5_

  - [ ]* 11.6 编写 LLM 安全模块属性测试
    - **Property 24: Prompt 注入检测与拦截** - 已知注入模式被检测并拒绝
    - **Property 25: 出站内容敏感信息脱敏** - 脱敏后不含 PII 和机密信息
    - **Property 26: LLM 调用频率限制** - 超 100 次/小时被拒绝
    - **Property 27: LLM 调用审计日志完整性** - 每次调用生成完整审计记录
    - **Property 30: API Key 网段访问控制** - 非白名单网段请求被拒绝
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.5, 15.4, 15.5**

- [ ] 12. LLM 相关 API 端点
  - [ ] 12.1 实现对话管理 API
    - POST /api/v1/llm/conversations - 创建新对话
    - POST /api/v1/llm/conversations/{id}/messages - 发送消息（支持 SSE 流式响应）
    - POST /api/v1/llm/conversations/{id}/regenerate - 重新生成回答
    - GET /api/v1/llm/conversations/{id}/messages - 获取会话历史
    - DELETE /api/v1/llm/conversations/{id} - 结束/删除会话
    - _Requirements: 9.1, 9.4, 9.6, 11.4, 11.5_

  - [ ] 12.2 实现 Prompt 模板管理 API
    - GET /api/v1/prompts/templates - 获取模板列表
    - POST /api/v1/prompts/templates - 创建模板
    - PUT /api/v1/prompts/templates/{id} - 更新模板（自动保存版本）
    - POST /api/v1/prompts/templates/{id}/preview - 预览渲染结果
    - GET /api/v1/prompts/templates/{id}/versions - 获取版本历史
    - POST /api/v1/prompts/templates/{id}/rollback/{version} - 版本回退
    - _Requirements: 12.1, 12.2, 12.3, 12.6_

  - [ ] 12.3 实现 Token 监控 API
    - GET /api/v1/tokens/usage - Token 用量统计查询
    - GET /api/v1/tokens/dashboard - 实时仪表盘数据
    - POST /api/v1/tokens/quotas - 设置配额
    - PUT /api/v1/tokens/quotas/{id} - 更新配额
    - GET /api/v1/tokens/quotas - 获取配额列表
    - _Requirements: 16.2, 16.3, 16.5_

  - [ ] 12.4 实现 LLM 模型管理 API
    - GET /api/v1/llm/models - 获取已配置模型列表（含状态、延迟）
    - POST /api/v1/llm/models - 添加新模型配置
    - POST /api/v1/llm/models/{model_id}/health-check - 手动健康检查
    - PUT /api/v1/llm/models/{model_id}/priority - 调整优先级
    - DELETE /api/v1/llm/models/{model_id} - 移除模型配置
    - _Requirements: 10.3, 10.5, 10.6_

- [ ] 13. Checkpoint - LLM 服务层集成验证
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 14. RAG 知识检索服务
  - [ ] 14.1 实现向量数据库连接与文档嵌入
    - 集成 ChromaDB（开发环境）和 Milvus（生产环境）客户端
    - 配置 Sentence-Transformers 嵌入模型（text2vec-base-chinese）
    - 实现文档切分、嵌入生成和向量入库流程
    - 存储文档元数据：source、department_id、access_level、access_roles
    - _Requirements: 7.4, 5.4_

  - [ ] 14.2 实现 RAG 检索引擎核心逻辑
    - 实现 RAGEngine 类：查询嵌入 → 向量检索 → 权限过滤 → 结果排序
    - 向量检索时多检索 3 倍候选集，为权限过滤留余量
    - 实现 _has_access 方法：基于 department_scope 和 access_level 过滤
    - _Requirements: 1.1, 1.3_

  - [ ] 14.3 实现 RAG + LLM 联合问答流程
    - 将 RAG 检索结果传递给 LLM 网关生成结构化回答
    - 实现回答相关度评分计算与低置信度提示
    - 实现 LLM 不可用时降级为原始文档片段展示
    - 无匹配结果时不调用 LLM，直接返回无结果提示
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 1.6, 1.7_

  - [ ] 14.4 实现知识检索 API 端点
    - POST /api/v1/knowledge/search - 语义检索（含权限过滤）
    - POST /api/v1/knowledge/documents - 上传文档（管理员）
    - DELETE /api/v1/knowledge/documents/{document_id} - 删除文档
    - 返回结果包含 content、source、relevance_score、metadata
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ]* 14.5 编写 RAG 模块属性测试
    - **Property 1: 权限过滤保证无越权访问（知识检索）** - 检索结果不含无权文档
    - **Property 11: 向量库文档访问控制标记一致性** - 存入与检索时标记一致
    - **Property 16: LLM 回答结构完整性与来源可追溯** - 回答含摘要/结论/引用，引用来源可追溯
    - **Property 17: LLM 回答相关度阈值检测** - 低于阈值标记低置信度
    - **Validates: Requirements 1.3, 5.4, 9.1, 9.2, 9.5**

- [ ] 15. 数据报表分析服务
  - [ ] 15.1 实现报表数据查询与生成逻辑
    - 实现 ReportGenerator 类：权限过滤维度 → 执行查询 → 构建图表配置
    - 支持 table/line_chart/bar_chart/pie_chart 四种图表类型
    - 大数据量（>10 万条）自动分页处理
    - 实现报表结果缓存（Redis, key: report:{config_id}:{params_hash}, TTL=15min）
    - _Requirements: 2.1, 2.2, 2.5, 6.4_

  - [ ] 15.2 实现报表导出功能（异步任务）
    - 集成 Celery 异步任务队列
    - 实现 Excel 导出（openpyxl/xlsxwriter）
    - 实现 PDF 导出（ReportLab/WeasyPrint）
    - 导出任务状态管理（pending → processing → completed/failed）
    - _Requirements: 2.3_

  - [ ] 15.3 实现报表 API 端点
    - GET /api/v1/reports - 获取可访问报表列表
    - POST /api/v1/reports/{report_id}/generate - 生成报表
    - POST /api/v1/reports/{report_id}/export - 发起导出任务
    - GET /api/v1/reports/export/{task_id} - 查询导出状态和下载链接
    - _Requirements: 2.1, 2.3, 2.4_

  - [ ]* 15.4 编写报表模块属性测试
    - **Property 2: 报表维度权限过滤完整性** - 返回维度均在授权范围
    - **Property 13: 大数据量分页正确性** - 分页数据条数和元数据准确
    - **Property 14: 报表导出数据完整性** - 导出文件包含全部源数据记录
    - **Validates: Requirements 2.3, 2.5, 6.4**

- [ ] 16. Checkpoint - 后端服务集成验证
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. 前端功能实现
  - [ ] 17.1 实现用户认证页面与路由守卫
    - 创建登录页面（用户名/密码表单、错误提示、锁定提示）
    - 实现路由守卫：未登录跳转登录页、Token 过期处理
    - Pinia store 管理用户状态和 Token
    - Axios 拦截器：自动附加 Authorization Header、处理 401 响应
    - _Requirements: 4.1, 4.3, 4.5_

  - [ ] 17.2 实现 LLM 智能问答对话界面
    - 创建对话列表侧边栏（会话管理：新建、切换、删除会话）
    - 创建聊天消息区域（支持流式逐字展示、Markdown 渲染）
    - 实现通过 EventSource 接收 SSE 流式响应
    - 实现重新生成按钮、低置信度回答提示和原始文档展示
    - 展示回答中的引用来源（可展开查看原文片段）
    - _Requirements: 9.3, 9.4, 9.5, 9.6_

  - [ ] 17.3 实现知识检索页面
    - 创建搜索输入框和结果展示组件
    - 展示文档片段、来源信息、相关度评分
    - 无结果时显示提示信息
    - 加载状态指示
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ] 17.4 实现数据报表页面
    - 集成 ECharts 图表组件（表格、折线图、柱状图、饼图）
    - 实现报表筛选条件面板（时间范围、维度选择、过滤器）
    - 实现分页加载和加载进度指示
    - 实现导出功能（选择格式、发起导出、轮询状态、下载）
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 17.5 实现 Prompt 模板管理页面（管理员）
    - 模板列表（按场景分类筛选、状态过滤）
    - 模板创建/编辑表单（模板内容编辑器、变量定义、场景分类选择）
    - 模板预览功能（输入示例变量值，实时展示渲染结果和 Token 计数）
    - 版本历史查看与回退操作
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6_

  - [ ] 17.6 实现 Token 监控仪表盘页面（管理员）
    - 实时仪表盘：当月 Token 用量、费用累计、预算剩余
    - 各模型调用次数分布图（饼图/柱状图）
    - Top 用户/部门用量排行
    - 配额管理界面（设置/修改用户和部门的 Token 配额）
    - 历史趋势图表（按日/周/月维度）
    - _Requirements: 16.2, 16.3, 16.5_

  - [ ] 17.7 实现 LLM 模型管理页面（管理员）
    - 模型列表（展示状态、响应延迟、优先级）
    - 模型配置表单（添加/编辑模型：provider、endpoint、API Key、优先级、参数）
    - 手动健康检查按钮和结果展示
    - 模型优先级拖拽排序
    - _Requirements: 10.3, 10.6_

  - [ ] 17.8 实现权限管理页面（管理员）
    - 角色列表/创建/编辑/删除界面
    - 权限配置面板（资源类型、资源ID、访问级别、部门范围）
    - 用户角色分配界面
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 17.9 实现审计日志与安全告警页面（管理员）
    - 审计日志列表（筛选条件：用户、操作类型、时间范围）
    - LLM 安全事件日志列表（Prompt 注入事件、PII 检测事件）
    - 安全告警列表（严重程度、状态过滤）
    - _Requirements: 5.3, 5.5, 13.3, 13.6_

- [ ] 18. Checkpoint - 前后端集成验证
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. 部署配置与系统集成
  - [ ] 19.1 编写 Docker 容器化配置
    - 创建各服务 Dockerfile（多阶段构建）
    - 创建 docker-compose.yml（开发环境：全部服务 + MySQL + ChromaDB + Redis）
    - 创建 docker-compose.prod.yml（生产环境：含 Milvus、Nginx、Redis Sentinel）
    - _Requirements: 7.5, 8.1_

  - [ ] 19.2 实现 LLM 服务部署配置
    - 创建 Ollama Docker 配置文件（GPU 支持、模型预加载、端口映射）
    - 创建 vLLM Docker 配置文件（GPU 分配、模型挂载、API 兼容层）
    - 配置 LLM 推理服务与网关的网络连接
    - 创建本地模型文件导入脚本（从安全介质加载模型权重）
    - GPU 资源监控配置（nvidia-smi 集成）
    - _Requirements: 14.1, 14.2, 14.4_

  - [ ] 19.3 实现 Nginx API 网关配置
    - 配置路由分发（各微服务路由规则，包含 LLM 服务端点）
    - 配置 TLS 终止（HTTPS 证书）
    - 配置请求限流（rate limiting）
    - 配置 SSE 长连接支持（proxy_buffering off）
    - 配置负载均衡（upstream）
    - _Requirements: 5.2, 7.5_

  - [ ] 19.4 实现 LDAP 集成（可选认证源）
    - 集成 python-ldap，实现 LDAP 认证后端
    - 配置开关：支持本地认证或 LDAP 认证切换
    - _Requirements: 4.2_

  - [ ] 19.5 实现纯内网部署方案支持
    - 配置离线 Embedding 模型加载（本地模型文件）
    - 配置离线 LLM 模型加载（Ollama 模型文件离线导入）
    - 实现知识库离线导入接口（文件上传批量入库）
    - 创建离线依赖打包脚本（pip download、npm pack）
    - _Requirements: 8.1, 8.3, 14.2, 14.3_

  - [ ] 19.6 实现云部署安全加固配置
    - 创建安全组/防火墙规则配置模板
    - 配置 VPN 接入网关规则
    - 实现 IP 白名单中间件
    - 配置 LLM API 出站白名单（仅允许指定 LLM 服务端点）
    - 配置数据备份加密策略
    - 集成 KMS 服务配置（用于 LLM API Key 加密）
    - _Requirements: 8.2, 8.4, 8.6, 5.7, 15.1, 15.4_

- [ ] 20. 系统容错与性能保障
  - [ ] 20.1 实现服务熔断器
    - 集成 circuitbreaker 库
    - 配置 RAG 服务熔断（5 次失败，恢复 30s）
    - 配置报表数据源熔断（3 次失败，恢复 60s）
    - 配置 LLM 模型调用熔断（3 次失败，恢复 45s）
    - 实现优雅降级响应
    - _Requirements: 6.5_

  - [ ] 20.2 实现数据禁止外传控制
    - 网络出站控制配置（仅允许安全更新通道和指定 LLM API 端点）
    - FastAPI 中间件：检测并阻止向外部地址的数据传输
    - _Requirements: 5.6_

- [ ] 21. Final Checkpoint - 全系统集成验证
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- 技术栈：后端 Python 3.11+ / FastAPI，前端 Vue 3 + TypeScript
- 向量数据库：开发环境使用 ChromaDB，生产环境使用 Milvus
- 异步任务（报表导出）使用 Celery + Redis 作为消息队列
- LLM 推理层：内网使用 Ollama/vLLM 本地推理，云部署可对接 OpenAI/通义千问/文心一言
- LLM 服务层新增模块：LLM 网关、对话管理器、Prompt 模板引擎、Token 监控服务、LLM 安全模块
- LLM 相关新增 7 张数据库表：llm_conversations、llm_messages、prompt_templates、prompt_template_versions、token_usage_records、token_quotas、llm_model_configs、llm_security_events

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2"] },
    { "id": 4, "tasks": ["2.4", "3.3", "3.4"] },
    { "id": 5, "tasks": ["2.5", "3.5", "5.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "6.1"] },
    { "id": 7, "tasks": ["5.4", "7.1"] },
    { "id": 8, "tasks": ["7.2", "7.3"] },
    { "id": 9, "tasks": ["7.4", "7.5", "8.1"] },
    { "id": 10, "tasks": ["8.2", "8.3", "9.1"] },
    { "id": 11, "tasks": ["8.4", "9.2", "9.3", "10.1"] },
    { "id": 12, "tasks": ["9.4", "10.2", "10.3", "11.1"] },
    { "id": 13, "tasks": ["10.4", "11.2", "11.3", "11.4"] },
    { "id": 14, "tasks": ["11.5", "11.6"] },
    { "id": 15, "tasks": ["12.1", "12.2", "12.3", "12.4"] },
    { "id": 16, "tasks": ["14.1", "15.1"] },
    { "id": 17, "tasks": ["14.2", "14.3", "15.2"] },
    { "id": 18, "tasks": ["14.4", "15.3"] },
    { "id": 19, "tasks": ["14.5", "15.4"] },
    { "id": 20, "tasks": ["17.1", "17.2", "17.3", "17.4"] },
    { "id": 21, "tasks": ["17.5", "17.6", "17.7", "17.8", "17.9"] },
    { "id": 22, "tasks": ["19.1", "19.2", "19.3"] },
    { "id": 23, "tasks": ["19.4", "19.5", "19.6"] },
    { "id": 24, "tasks": ["20.1", "20.2"] }
  ]
}
```
