# 技术设计文档：内部数据分析工具

## 1. 系统架构设计

### 1.1 整体架构

系统采用前后端分离的微服务架构，分为以下核心层次：

```
┌─────────────────────────────────────────────────────────────┐
│                    前端层 (Vue 3 + TypeScript)                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐      │
│  │ 智能问答  │  │ 数据报表  │  │ 权限管理  │  │ 用户中心│      │
│  │(对话界面) │  │          │  │          │  │        │      │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐      │
│  │ 知识检索  │  │Prompt管理│  │ Token监控仪表盘      │      │
│  └──────────┘  └──────────┘  └──────────────────────┘      │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTPS / RESTful API
┌─────────────────────────┴───────────────────────────────────┐
│                   API 网关层 (Nginx/Traefik)                  │
│          路由分发 / 限流 / TLS 终止 / 负载均衡                │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────────┐
│                  后端服务层 (Python FastAPI)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐      │
│  │ RAG 服务  │  │ 报表服务  │  │ 权限服务  │  │ 认证服务│      │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LLM 服务层                                │   │
│  │  ┌────────┐ ┌────────┐ ┌──────────┐ ┌────────────┐  │   │
│  │  │LLM网关 │ │对话管理│ │Prompt模板│ │ Token监控  │  │   │
│  │  │(路由/  │ │  器    │ │  引擎    │ │  服务      │  │   │
│  │  │Failover)│ │        │ │          │ │            │  │   │
│  │  └────────┘ └────────┘ └──────────┘ └────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              数据安全层 (横切关注点)                    │   │
│  │  加密/解密 | 审计日志 | 异常检测 | 访问控制            │   │
│  │  Prompt注入检测 | 敏感信息脱敏 | API Key管理(KMS)      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────────┐
│                  LLM 推理层                                   │
│  ┌──────────────────┐  ┌────────────────────────────────┐   │
│  │ 本地模型 (内网)   │  │ 云端 LLM API (云部署)           │   │
│  │ Ollama / vLLM    │  │ OpenAI / 通义千问 / 文心一言    │   │
│  └──────────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────────┐
│                      数据存储层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐      │
│  │  MySQL   │  │ ChromaDB │  │  Milvus  │  │  Redis │      │
│  │(结构化数据)│ │(小规模向量)│ │(大规模向量)│ │ (缓存) │      │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 微服务划分

| 服务名称 | 职责 | 技术栈 |
|---------|------|--------|
| `rag-service` | RAG 知识检索、文档嵌入、语义搜索 | FastAPI + LangChain + Sentence-Transformers |
| `llm-service` | LLM 网关、对话管理、Prompt 模板、Token 监控 | FastAPI + LangChain + tiktoken |
| `report-service` | 报表生成、数据聚合、图表渲染、导出 | FastAPI + Pandas + Matplotlib/ECharts |
| `auth-service` | 用户认证、令牌管理、LDAP集成 | FastAPI + python-jose + python-ldap |
| `permission-service` | RBAC 权限管理、角色分配、权限计算 | FastAPI + SQLAlchemy |
| `security-service` | 数据加密、审计日志、异常检测、Prompt注入检测 | FastAPI + cryptography + 审计模块 |
| `gateway` | API 路由、限流、TLS 终止 | Nginx / Traefik |

### 1.3 服务间通信

- 前端 → 后端：RESTful API over HTTPS
- 服务间调用：内部 HTTP（内网环境）或 gRPC（高性能场景）
- 异步任务：Redis 消息队列（报表生成、异常检测等耗时操作）
- LLM 流式响应：Server-Sent Events (SSE) 从后端推送到前端
- LLM 网关 → 模型推理：HTTP（Ollama/vLLM API）或 HTTPS（云端 LLM API）

## 2. 数据库设计

### 2.1 MySQL 表结构设计

#### 用户与权限相关表

```sql
-- 用户表
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    department_id BIGINT NOT NULL,
    position VARCHAR(64),
    email VARCHAR(128),
    status ENUM('active', 'locked', 'disabled') DEFAULT 'active',
    failed_login_count INT DEFAULT 0,
    locked_until DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_department (department_id),
    INDEX idx_status (status)
);

-- 角色表
CREATE TABLE roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL UNIQUE,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 权限定义表
CREATE TABLE permissions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    role_id BIGINT NOT NULL,
    resource_type ENUM('report', 'knowledge_base', 'data_dimension', 'system') NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    access_level ENUM('none', 'read', 'write', 'admin') NOT NULL DEFAULT 'read',
    department_scope VARCHAR(256) COMMENT '部门范围限制，JSON数组',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    INDEX idx_role_resource (role_id, resource_type, resource_id)
);

-- 用户角色关联表
CREATE TABLE user_roles (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    assigned_by BIGINT NOT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

-- 部门表
CREATE TABLE departments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    parent_id BIGINT NULL,
    path VARCHAR(512) COMMENT '部门层级路径',
    FOREIGN KEY (parent_id) REFERENCES departments(id)
);
```

#### 审计与安全相关表

```sql
-- 审计日志表
CREATE TABLE audit_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    operation_type ENUM('login', 'logout', 'query', 'export', 'permission_change', 'role_change', 'config_change') NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(128),
    data_scope TEXT COMMENT '涉及数据范围描述',
    details JSON COMMENT '操作详情',
    ip_address VARCHAR(45),
    user_agent VARCHAR(256),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, created_at),
    INDEX idx_operation (operation_type, created_at)
);

-- 权限变更日志表
CREATE TABLE permission_change_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    operator_id BIGINT NOT NULL,
    target_type ENUM('role', 'user_role', 'permission') NOT NULL,
    target_id BIGINT NOT NULL,
    action ENUM('create', 'update', 'delete') NOT NULL,
    old_value JSON,
    new_value JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_operator_time (operator_id, created_at)
);

-- 安全告警表
CREATE TABLE security_alerts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    alert_type ENUM('abnormal_access', 'brute_force', 'data_leak_attempt', 'unauthorized_access') NOT NULL,
    user_id BIGINT,
    description TEXT NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    status ENUM('open', 'acknowledged', 'resolved') DEFAULT 'open',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status_severity (status, severity)
);
```

#### 报表相关表

```sql
-- 报表配置表
CREATE TABLE report_configs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    report_type ENUM('table', 'line_chart', 'bar_chart', 'pie_chart') NOT NULL,
    data_source VARCHAR(256) NOT NULL,
    query_template TEXT NOT NULL,
    access_roles JSON COMMENT '可访问该报表的角色ID列表',
    created_by BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 报表导出任务表
CREATE TABLE export_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    report_config_id BIGINT NOT NULL,
    format ENUM('excel', 'pdf') NOT NULL,
    status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    file_path VARCHAR(512),
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (report_config_id) REFERENCES report_configs(id),
    INDEX idx_user_status (user_id, status)
);
```

#### LLM 相关表

```sql
-- LLM 对话会话表
CREATE TABLE llm_conversations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    title VARCHAR(256) COMMENT '会话标题（取自首次提问摘要）',
    status ENUM('active', 'archived', 'deleted') DEFAULT 'active',
    model_id VARCHAR(64) COMMENT '当前会话使用的模型标识',
    total_input_tokens BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    last_active_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status),
    INDEX idx_last_active (last_active_at)
);

-- 对话消息表
CREATE TABLE llm_messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    role ENUM('user', 'assistant', 'system') NOT NULL,
    content TEXT NOT NULL,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    model_id VARCHAR(64),
    sources JSON COMMENT '引用的文档来源列表',
    relevance_score FLOAT COMMENT '回答与检索文档的相关度评分',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES llm_conversations(id) ON DELETE CASCADE,
    INDEX idx_conversation_time (conversation_id, created_at)
);

-- Prompt 模板表
CREATE TABLE prompt_templates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    category ENUM('tech_doc', 'data_analysis', 'process_guide', 'general') NOT NULL DEFAULT 'general',
    template_content TEXT NOT NULL COMMENT '模板内容，含变量占位符',
    variables JSON COMMENT '支持的变量列表及描述',
    version INT DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    created_by BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category_active (category, is_active)
);

-- Prompt 模板版本历史表
CREATE TABLE prompt_template_versions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_id BIGINT NOT NULL,
    version INT NOT NULL,
    template_content TEXT NOT NULL,
    variables JSON,
    changed_by BIGINT NOT NULL,
    change_description VARCHAR(256),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (template_id) REFERENCES prompt_templates(id) ON DELETE CASCADE,
    INDEX idx_template_version (template_id, version)
);

-- Token 用量记录表
CREATE TABLE token_usage_records (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    department_id BIGINT NOT NULL,
    conversation_id BIGINT,
    model_id VARCHAR(64) NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    estimated_cost DECIMAL(10, 6) COMMENT '估算费用（元）',
    request_type ENUM('chat', 'regenerate', 'summary') NOT NULL DEFAULT 'chat',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_time (user_id, created_at),
    INDEX idx_department_time (department_id, created_at),
    INDEX idx_model_time (model_id, created_at)
);

-- Token 配额表
CREATE TABLE token_quotas (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    target_type ENUM('user', 'department') NOT NULL,
    target_id BIGINT NOT NULL,
    monthly_token_limit BIGINT NOT NULL COMMENT '月度 Token 配额',
    monthly_cost_limit DECIMAL(10, 2) COMMENT '月度费用上限（元）',
    current_month_tokens BIGINT DEFAULT 0,
    current_month_cost DECIMAL(10, 2) DEFAULT 0.00,
    alert_threshold FLOAT DEFAULT 0.8 COMMENT '预警阈值百分比',
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_target (target_type, target_id)
);

-- LLM 模型配置表
CREATE TABLE llm_model_configs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    model_id VARCHAR(64) NOT NULL UNIQUE COMMENT '模型标识符',
    model_name VARCHAR(128) NOT NULL COMMENT '显示名称',
    provider ENUM('ollama', 'vllm', 'openai', 'qwen', 'wenxin') NOT NULL,
    endpoint_url VARCHAR(512) NOT NULL,
    api_key_ref VARCHAR(256) COMMENT 'KMS 中的密钥引用（云端模型）',
    priority INT DEFAULT 0 COMMENT '优先级，数值越小优先级越高',
    max_tokens INT DEFAULT 4096,
    temperature FLOAT DEFAULT 0.7,
    task_types JSON COMMENT '适用的任务类型列表',
    status ENUM('active', 'inactive', 'error') DEFAULT 'active',
    last_health_check DATETIME,
    avg_latency_ms INT COMMENT '平均响应延迟（毫秒）',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_provider_status (provider, status),
    INDEX idx_priority (priority)
);

-- LLM 安全事件日志表
CREATE TABLE llm_security_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    event_type ENUM('prompt_injection', 'pii_detected', 'classification_blocked', 'rate_limited', 'key_anomaly') NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') NOT NULL,
    input_content TEXT COMMENT '触发事件的输入内容（脱敏后）',
    detection_details JSON COMMENT '检测详情',
    action_taken VARCHAR(64) COMMENT '采取的动作',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_type (user_id, event_type),
    INDEX idx_severity_time (severity, created_at)
);
```

### 2.2 向量数据库索引策略

#### ChromaDB（小规模/开发环境）

```python
# ChromaDB Collection 设计
collection_config = {
    "name": "knowledge_base",
    "metadata": {
        "hnsw:space": "cosine",       # 余弦相似度
        "hnsw:M": 16,                 # HNSW 图连接数
        "hnsw:ef_construction": 200,  # 构建时搜索宽度
    }
}

# 文档元数据 schema（用于权限过滤）
document_metadata = {
    "source": str,            # 文档来源
    "department_id": int,     # 所属部门
    "access_level": str,      # 访问级别: public/internal/confidential
    "access_roles": list,     # 允许访问的角色ID列表
    "created_at": str,        # 创建时间
    "doc_type": str,          # 文档类型
}
```

#### Milvus（生产环境/大规模检索）

```python
# Milvus Collection Schema
from pymilvus import CollectionSchema, FieldSchema, DataType

fields = [
    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768),
    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
    FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
    FieldSchema(name="department_id", dtype=DataType.INT64),
    FieldSchema(name="access_level", dtype=DataType.VARCHAR, max_length=32),
    FieldSchema(name="access_roles", dtype=DataType.VARCHAR, max_length=512),  # JSON 数组
    FieldSchema(name="created_at", dtype=DataType.INT64),
]

# 索引策略
index_params = {
    "index_type": "IVF_PQ",          # 倒排文件+乘积量化，平衡精度与性能
    "metric_type": "COSINE",
    "params": {
        "nlist": 1024,               # 聚类中心数
        "m": 8,                      # 子向量数
        "nbits": 8,                  # 每子向量编码位数
    }
}

# 搜索参数
search_params = {
    "metric_type": "COSINE",
    "params": {
        "nprobe": 32,                # 搜索时探测的聚类数
        "ef": 64,                    # HNSW 搜索宽度（如使用 HNSW 索引）
    }
}
```

### 2.3 Redis 缓存策略

```python
# 缓存 Key 设计
CACHE_KEYS = {
    "user_permissions": "perm:user:{user_id}",          # 用户有效权限缓存，TTL=5min
    "role_permissions": "perm:role:{role_id}",          # 角色权限定义缓存，TTL=10min
    "session": "session:{token_id}",                    # 会话信息，TTL=30min
    "login_attempts": "login:attempts:{username}",      # 登录失败次数，TTL=1min
    "report_cache": "report:{config_id}:{params_hash}", # 报表结果缓存，TTL=15min
    # LLM 相关缓存
    "llm_conversation": "llm:conv:{conversation_id}",   # 对话上下文缓存，TTL=24h
    "llm_rate_limit": "llm:rate:{user_id}",            # 用户 LLM 调用频率计数，TTL=1h
    "llm_model_status": "llm:model:{model_id}:status", # 模型健康状态缓存，TTL=30s
    "token_usage_daily": "token:daily:{user_id}:{date}",# 日 Token 用量计数，TTL=48h
    "token_quota": "token:quota:{target_type}:{id}",   # 配额剩余缓存，TTL=5min
}
```

## 3. API 设计

### 3.1 认证相关 API

```python
# POST /api/v1/auth/login
# 请求体
class LoginRequest(BaseModel):
    username: str
    password: str

# 响应
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: UserInfo

# POST /api/v1/auth/logout
# Header: Authorization: Bearer {token}
# 响应: 204 No Content

# GET /api/v1/auth/me
# 获取当前用户信息和权限
class CurrentUserResponse(BaseModel):
    user: UserInfo
    roles: list[RoleInfo]
    permissions: list[PermissionInfo]
```

### 3.2 RAG 知识检索 API

```python
# POST /api/v1/knowledge/search
class KnowledgeSearchRequest(BaseModel):
    query: str                       # 自然语言查询
    top_k: int = 10                  # 返回结果数
    filters: dict | None = None      # 额外过滤条件

class DocumentFragment(BaseModel):
    id: str
    content: str                     # 文档片段内容
    source: str                      # 来源文档名
    relevance_score: float           # 相关度评分 (0-1)
    metadata: dict                   # 其他元数据

class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[DocumentFragment]
    total_found: int
    search_time_ms: float

# POST /api/v1/knowledge/documents
# 上传文档到知识库（管理员）
class DocumentUploadRequest(BaseModel):
    title: str
    content: str
    department_id: int
    access_level: str                # public/internal/confidential
    access_roles: list[int] | None   # 指定可访问角色
    doc_type: str

# DELETE /api/v1/knowledge/documents/{document_id}
# 删除知识库文档（管理员）
```

### 3.3 报表 API

```python
# GET /api/v1/reports
# 获取当前用户可访问的报表列表
class ReportListResponse(BaseModel):
    reports: list[ReportConfigInfo]
    total: int

# POST /api/v1/reports/{report_id}/generate
class ReportGenerateRequest(BaseModel):
    date_range: DateRange            # 时间范围
    dimensions: list[str] | None     # 数据维度
    filters: dict | None             # 过滤条件
    chart_type: str                  # table/line_chart/bar_chart/pie_chart
    page: int = 1
    page_size: int = 50

class ReportGenerateResponse(BaseModel):
    data: list[dict]                 # 报表数据
    chart_config: dict               # 图表渲染配置
    pagination: PaginationInfo
    generated_at: datetime

# POST /api/v1/reports/{report_id}/export
class ReportExportRequest(BaseModel):
    format: str                      # excel/pdf
    date_range: DateRange
    dimensions: list[str] | None
    filters: dict | None

class ReportExportResponse(BaseModel):
    task_id: str                     # 异步任务 ID
    status: str

# GET /api/v1/reports/export/{task_id}
# 查询导出任务状态，完成后返回下载链接
class ExportStatusResponse(BaseModel):
    task_id: str
    status: str                      # pending/processing/completed/failed
    download_url: str | None
    error_message: str | None
```

### 3.4 权限管理 API

```python
# GET /api/v1/roles
# 获取角色列表（管理员）
class RoleListResponse(BaseModel):
    roles: list[RoleDetail]

# POST /api/v1/roles
class RoleCreateRequest(BaseModel):
    name: str
    description: str | None
    permissions: list[PermissionDefinition]

class PermissionDefinition(BaseModel):
    resource_type: str               # report/knowledge_base/data_dimension/system
    resource_id: str
    access_level: str                # none/read/write/admin
    department_scope: list[int] | None

# PUT /api/v1/roles/{role_id}
class RoleUpdateRequest(BaseModel):
    name: str | None
    description: str | None
    permissions: list[PermissionDefinition] | None

# DELETE /api/v1/roles/{role_id}
# 响应: 204 No Content

# POST /api/v1/users/{user_id}/roles
class AssignRoleRequest(BaseModel):
    role_ids: list[int]

# DELETE /api/v1/users/{user_id}/roles/{role_id}
# 移除用户角色

# GET /api/v1/users/{user_id}/effective-permissions
# 获取用户有效权限（合并多角色后）
class EffectivePermissionsResponse(BaseModel):
    user_id: int
    permissions: list[EffectivePermission]
    roles: list[RoleInfo]
```

### 3.5 审计日志 API

```python
# GET /api/v1/audit/logs
class AuditLogQuery(BaseModel):
    user_id: int | None
    operation_type: str | None
    start_time: datetime | None
    end_time: datetime | None
    page: int = 1
    page_size: int = 50

class AuditLogListResponse(BaseModel):
    logs: list[AuditLogEntry]
    pagination: PaginationInfo

# GET /api/v1/security/alerts
class SecurityAlertListResponse(BaseModel):
    alerts: list[SecurityAlert]
    pagination: PaginationInfo
```

### 3.6 LLM 对话 API

```python
# POST /api/v1/llm/conversations
# 创建新对话
class CreateConversationRequest(BaseModel):
    title: str | None = None

class ConversationResponse(BaseModel):
    id: int
    title: str | None
    status: str
    model_id: str
    created_at: datetime

# POST /api/v1/llm/conversations/{conversation_id}/messages
# 发送消息并获取 LLM 回答（支持 SSE 流式响应）
class SendMessageRequest(BaseModel):
    content: str                      # 用户问题
    use_rag: bool = True              # 是否使用 RAG 检索
    stream: bool = True               # 是否流式响应

class LLMMessageResponse(BaseModel):
    message_id: int
    role: str                         # "assistant"
    content: str                      # LLM 生成的回答
    sources: list[DocumentSource]     # 引用的文档来源
    relevance_score: float            # 回答与检索文档的相关度
    input_tokens: int
    output_tokens: int

class DocumentSource(BaseModel):
    doc_id: str
    title: str
    relevance_score: float
    snippet: str                      # 引用片段

# POST /api/v1/llm/conversations/{conversation_id}/regenerate
# 重新生成最后一条回答
class RegenerateResponse(BaseModel):
    message_id: int
    content: str
    sources: list[DocumentSource]

# GET /api/v1/llm/conversations/{conversation_id}/messages
# 获取会话历史
class ConversationHistoryResponse(BaseModel):
    conversation_id: int
    messages: list[MessageEntry]
    total_tokens: int

# DELETE /api/v1/llm/conversations/{conversation_id}
# 结束/删除会话
# 响应: 204 No Content
```

### 3.7 Prompt 模板管理 API

```python
# GET /api/v1/prompts/templates
# 获取模板列表（管理员）
class PromptTemplateListResponse(BaseModel):
    templates: list[PromptTemplateInfo]
    total: int

# POST /api/v1/prompts/templates
class CreatePromptTemplateRequest(BaseModel):
    name: str
    category: str                    # tech_doc/data_analysis/process_guide/general
    template_content: str
    variables: list[VariableDefinition]

class VariableDefinition(BaseModel):
    name: str                        # 变量名：如 {{user_query}}, {{context_docs}}
    description: str
    required: bool = True

# PUT /api/v1/prompts/templates/{template_id}
class UpdatePromptTemplateRequest(BaseModel):
    name: str | None
    template_content: str | None
    variables: list[VariableDefinition] | None
    is_active: bool | None
    change_description: str          # 变更说明

# POST /api/v1/prompts/templates/{template_id}/preview
# 预览模板渲染结果
class TemplatePreviewRequest(BaseModel):
    variables: dict[str, str]        # 变量名 → 示例值

class TemplatePreviewResponse(BaseModel):
    rendered_content: str
    token_count: int

# GET /api/v1/prompts/templates/{template_id}/versions
# 获取模板版本历史
class TemplateVersionListResponse(BaseModel):
    versions: list[TemplateVersionInfo]

# POST /api/v1/prompts/templates/{template_id}/rollback/{version}
# 回退到指定版本
class TemplateRollbackResponse(BaseModel):
    template_id: int
    current_version: int
    rolled_back_from: int
```

### 3.8 Token 监控 API

```python
# GET /api/v1/tokens/usage
# 获取 Token 用量统计
class TokenUsageQuery(BaseModel):
    user_id: int | None
    department_id: int | None
    model_id: str | None
    start_time: datetime | None
    end_time: datetime | None
    group_by: str = "day"            # day/week/month

class TokenUsageResponse(BaseModel):
    records: list[TokenUsageRecord]
    summary: TokenUsageSummary

class TokenUsageSummary(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    period: str

# GET /api/v1/tokens/dashboard
# 实时仪表盘数据
class TokenDashboardResponse(BaseModel):
    current_month_tokens: int
    current_month_cost: float
    budget_remaining: float | None
    model_breakdown: list[ModelUsageInfo]
    top_users: list[UserUsageInfo]

# POST /api/v1/tokens/quotas
# 设置 Token 配额（管理员）
class SetQuotaRequest(BaseModel):
    target_type: str                 # user/department
    target_id: int
    monthly_token_limit: int
    monthly_cost_limit: float | None
    alert_threshold: float = 0.8

# GET /api/v1/tokens/quotas
# 获取配额列表
class QuotaListResponse(BaseModel):
    quotas: list[QuotaInfo]

# PUT /api/v1/tokens/quotas/{quota_id}
# 更新配额配置
class UpdateQuotaRequest(BaseModel):
    monthly_token_limit: int | None
    monthly_cost_limit: float | None
    alert_threshold: float | None
```

### 3.9 LLM 模型管理 API

```python
# GET /api/v1/llm/models
# 获取已配置模型列表
class ModelListResponse(BaseModel):
    models: list[ModelConfigInfo]

class ModelConfigInfo(BaseModel):
    model_id: str
    model_name: str
    provider: str
    status: str
    priority: int
    avg_latency_ms: int | None
    last_health_check: datetime | None

# POST /api/v1/llm/models
# 添加新模型配置（管理员）
class AddModelRequest(BaseModel):
    model_id: str
    model_name: str
    provider: str                    # ollama/vllm/openai/qwen/wenxin
    endpoint_url: str
    api_key: str | None              # 云端模型需要，将通过 KMS 加密存储
    priority: int = 0
    max_tokens: int = 4096
    temperature: float = 0.7
    task_types: list[str] | None

# POST /api/v1/llm/models/{model_id}/health-check
# 手动触发健康检查
class HealthCheckResponse(BaseModel):
    model_id: str
    status: str                      # active/error
    latency_ms: int
    error_message: str | None

# PUT /api/v1/llm/models/{model_id}/priority
# 调整模型优先级
class UpdatePriorityRequest(BaseModel):
    priority: int

# DELETE /api/v1/llm/models/{model_id}
# 移除模型配置
# 响应: 204 No Content
```

## 4. 安全架构设计

### 4.1 认证流程

```
用户登录 → 验证凭证(本地/LDAP) → 检查锁定状态
    │                                    │
    ├─ 失败 → 记录失败次数 → 超过5次 → 锁定15分钟
    │
    └─ 成功 → 生成 JWT Token → 缓存会话 → 返回 Token
               │
               ├─ access_token: 包含 user_id, roles, exp
               └─ 存入 Redis: session:{token_id}, TTL=30min
```

### 4.2 权限计算模型

```python
class PermissionCalculator:
    """
    权限计算器：合并用户多角色权限，冲突时取最高权限。
    """
    ACCESS_LEVEL_PRIORITY = {"none": 0, "read": 1, "write": 2, "admin": 3}

    def calculate_effective_permissions(
        self, user_id: int, roles: list[Role]
    ) -> list[EffectivePermission]:
        """
        合并用户所有角色的权限定义。
        对同一资源的不同权限级别，取最高级别（最高权限优先原则）。
        """
        permission_map: dict[str, EffectivePermission] = {}

        for role in roles:
            for perm in role.permissions:
                key = f"{perm.resource_type}:{perm.resource_id}"
                if key not in permission_map:
                    permission_map[key] = perm
                else:
                    existing = permission_map[key]
                    if self.ACCESS_LEVEL_PRIORITY[perm.access_level] > \
                       self.ACCESS_LEVEL_PRIORITY[existing.access_level]:
                        permission_map[key] = perm

        return list(permission_map.values())
```

### 4.3 数据加密策略

```python
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

class DataEncryptor:
    """AES-256 加密器，用于敏感数据字段加密存储。"""

    def __init__(self, key: bytes):
        """key 为 32 字节 AES-256 密钥。"""
        assert len(key) == 32
        self.key = key

    def encrypt(self, plaintext: str) -> str:
        """加密明文，返回 Base64 编码的密文（含 IV）。"""
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext.encode()) + encryptor.finalize()
        # 返回格式: base64(iv + tag + ciphertext)
        return base64.b64encode(iv + encryptor.tag + ciphertext).decode()

    def decrypt(self, encrypted: str) -> str:
        """解密 Base64 编码的密文。"""
        data = base64.b64decode(encrypted)
        iv, tag, ciphertext = data[:16], data[16:32], data[32:]
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(iv, tag))
        decryptor = cipher.decryptor()
        return (decryptor.update(ciphertext) + decryptor.finalize()).decode()
```

### 4.4 审计日志机制

```python
class AuditLogger:
    """统一审计日志记录器，覆盖所有数据操作和权限变更。"""

    async def log_operation(
        self,
        user_id: int,
        operation_type: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        data_scope: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        """记录操作审计日志。"""
        await self.db.execute(
            audit_logs.insert().values(
                user_id=user_id,
                operation_type=operation_type,
                resource_type=resource_type,
                resource_id=resource_id,
                data_scope=data_scope,
                details=json.dumps(details) if details else None,
                ip_address=ip_address,
            )
        )

    async def log_permission_change(
        self,
        operator_id: int,
        target_type: str,
        target_id: int,
        action: str,
        old_value: dict | None,
        new_value: dict | None,
    ) -> None:
        """记录权限变更审计日志。"""
        await self.db.execute(
            permission_change_logs.insert().values(
                operator_id=operator_id,
                target_type=target_type,
                target_id=target_id,
                action=action,
                old_value=json.dumps(old_value) if old_value else None,
                new_value=json.dumps(new_value) if new_value else None,
            )
        )
```

### 4.5 异常检测机制

```python
class AnomalyDetector:
    """数据访问异常检测器。"""

    # 阈值配置
    EXPORT_THRESHOLD = 10          # 1小时内导出次数上限
    QUERY_THRESHOLD = 200          # 1小时内查询次数上限
    WINDOW_SECONDS = 3600          # 检测窗口（1小时）

    async def check_access_pattern(self, user_id: int, operation: str) -> bool:
        """
        检查用户访问模式是否异常。
        返回 True 表示异常，需触发告警。
        """
        key = f"access_count:{user_id}:{operation}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.WINDOW_SECONDS)

        threshold = (
            self.EXPORT_THRESHOLD if operation == "export"
            else self.QUERY_THRESHOLD
        )

        if count > threshold:
            await self.trigger_alert(user_id, operation, count)
            return True
        return False
```

## 5. LLM 服务设计

### 5.1 LLM 网关架构

```python
class LLMGateway:
    """
    LLM 统一网关：提供统一接口、模型路由和 Failover 策略。
    所有 LLM 调用通过此网关统一管理。
    """

    def __init__(
        self,
        model_registry: ModelRegistry,
        rate_limiter: RateLimiter,
        security_filter: SecurityFilter,
        token_monitor: TokenMonitor,
    ):
        self.model_registry = model_registry
        self.rate_limiter = rate_limiter
        self.security_filter = security_filter
        self.token_monitor = token_monitor

    async def generate(
        self, request: LLMRequest, user_id: int
    ) -> AsyncIterator[str]:
        """
        统一生成接口，支持流式输出。
        流程：安全检查 → 频率限制 → 配额检查 → 模型路由 → 调用 → 记录
        """
        # 1. Prompt 注入检测
        await self.security_filter.check_prompt_injection(request.prompt)

        # 2. 频率限制
        await self.rate_limiter.check(user_id, limit=100, window=3600)

        # 3. Token 配额检查
        await self.token_monitor.check_quota(user_id)

        # 4. 敏感信息脱敏（云端模型时）
        model = await self._select_model(request.task_type)
        if model.provider in ('openai', 'qwen', 'wenxin'):
            request = await self.security_filter.sanitize_outbound(request)

        # 5. 调用模型（含 Failover）
        response = await self._call_with_failover(model, request)

        # 6. 输出安全过滤
        response = await self.security_filter.filter_output(response)

        # 7. 记录 Token 用量
        await self.token_monitor.record_usage(
            user_id=user_id,
            model_id=model.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        return response

    async def _select_model(self, task_type: str | None) -> ModelConfig:
        """
        模型选择策略：
        1. 如果指定了 task_type，选择该类型适用的最高优先级可用模型
        2. 否则按全局优先级选择最高优先级可用模型
        """
        models = await self.model_registry.get_available_models(task_type)
        if not models:
            raise AllModelsUnavailableException()
        return models[0]  # 已按优先级排序

    async def _call_with_failover(
        self, primary_model: ModelConfig, request: LLMRequest
    ) -> LLMResponse:
        """
        Failover 策略：
        - 首选模型调用失败时，按优先级顺序尝试下一个可用模型
        - 记录失败模型状态，短期内不再尝试（熔断）
        - 所有模型都不可用时，返回服务不可用错误
        """
        models = await self.model_registry.get_available_models(request.task_type)
        last_error = None

        for model in models:
            try:
                return await self._invoke_model(model, request)
            except ModelInvocationException as e:
                last_error = e
                await self.model_registry.mark_unhealthy(model.model_id)
                continue

        raise AllModelsUnavailableException(last_error=last_error)

    async def _invoke_model(
        self, model: ModelConfig, request: LLMRequest
    ) -> LLMResponse:
        """调用具体模型实例。"""
        adapter = self._get_adapter(model.provider)
        return await adapter.generate(
            endpoint=model.endpoint_url,
            prompt=request.prompt,
            max_tokens=model.max_tokens,
            temperature=model.temperature,
            stream=request.stream,
        )

    def _get_adapter(self, provider: str) -> ModelAdapter:
        """获取对应供应商的模型适配器。"""
        adapters = {
            "ollama": OllamaAdapter(),
            "vllm": VLLMAdapter(),
            "openai": OpenAIAdapter(),
            "qwen": QwenAdapter(),
            "wenxin": WenxinAdapter(),
        }
        return adapters[provider]
```

### 5.2 对话管理器设计

```python
class ConversationManager:
    """
    对话管理器：维护多轮对话上下文，处理上下文窗口和摘要压缩。
    """

    MAX_CONTEXT_TURNS = 20           # 最大上下文轮数
    ARCHIVE_INACTIVE_HOURS = 24      # 不活跃自动归档时间

    def __init__(
        self,
        redis_client: Redis,
        db: Database,
        summarizer: ContextSummarizer,
        tokenizer: Tokenizer,
    ):
        self.redis = redis_client
        self.db = db
        self.summarizer = summarizer
        self.tokenizer = tokenizer

    async def build_prompt_context(
        self, conversation_id: int, model_max_tokens: int
    ) -> list[dict]:
        """
        构建当前对话的 Prompt 上下文：
        1. 获取最近 20 轮对话历史
        2. 计算总 Token 数
        3. 如超出模型限制，对早期内容进行摘要压缩
        4. 返回格式化的消息列表
        """
        # 获取最近对话历史
        messages = await self._get_recent_messages(
            conversation_id, limit=self.MAX_CONTEXT_TURNS * 2  # 每轮含 user + assistant
        )

        # 计算 Token 数
        total_tokens = self.tokenizer.count_messages_tokens(messages)
        context_budget = int(model_max_tokens * 0.6)  # 保留 40% 给新回答

        # 超出限制时摘要压缩
        if total_tokens > context_budget:
            messages = await self._compress_context(messages, context_budget)

        return messages

    async def _compress_context(
        self, messages: list[dict], token_budget: int
    ) -> list[dict]:
        """
        上下文压缩策略：
        - 保留最近 5 轮完整对话
        - 将更早的对话内容压缩为摘要
        """
        recent_messages = messages[-10:]  # 最近 5 轮
        older_messages = messages[:-10]

        if older_messages:
            summary = await self.summarizer.summarize(older_messages)
            summary_message = {"role": "system", "content": f"[对话历史摘要]: {summary}"}
            return [summary_message] + recent_messages

        return recent_messages

    async def end_conversation(self, conversation_id: int) -> None:
        """结束会话，清空上下文缓存。"""
        await self.redis.delete(f"llm:conv:{conversation_id}")
        await self.db.execute(
            llm_conversations.update()
            .where(llm_conversations.c.id == conversation_id)
            .values(status="archived")
        )

    async def archive_inactive_conversations(self) -> int:
        """归档超过 24 小时未活动的会话（定时任务调用）。"""
        threshold = datetime.utcnow() - timedelta(hours=self.ARCHIVE_INACTIVE_HOURS)
        result = await self.db.execute(
            llm_conversations.update()
            .where(
                llm_conversations.c.status == "active",
                llm_conversations.c.last_active_at < threshold,
            )
            .values(status="archived")
        )
        # 清理 Redis 缓存
        archived_ids = await self._get_archived_ids(threshold)
        for conv_id in archived_ids:
            await self.redis.delete(f"llm:conv:{conv_id}")
        return result.rowcount
```

### 5.3 Prompt 模板引擎设计

```python
class PromptTemplateEngine:
    """
    Prompt 模板引擎：管理模板存储、变量替换和版本控制。
    """

    # 内置变量名称
    BUILTIN_VARIABLES = {
        "user_query": "用户的原始问题",
        "context_docs": "RAG 检索到的相关文档内容",
        "conversation_history": "对话历史上下文",
        "user_role": "当前用户的角色信息",
        "current_time": "当前时间戳",
    }

    # 默认模板
    DEFAULT_TEMPLATE = """你是一个企业内部知识助手。请基于以下检索到的文档内容回答用户的问题。

检索文档：
{{context_docs}}

{% if conversation_history %}
对话历史：
{{conversation_history}}
{% endif %}

用户问题：{{user_query}}

请提供结构化回答，包含：
1. 摘要（一句话概括）
2. 关键要点（列表形式）
3. 详细说明
4. 参考来源（标注引用的文档）

如果检索文档中没有相关信息，请明确说明无法回答并建议用户调整问题。"""

    async def render(
        self, template_id: int | None, variables: dict[str, str]
    ) -> str:
        """
        渲染 Prompt 模板：
        1. 获取指定模板（或使用默认模板）
        2. 替换所有变量占位符
        3. 返回最终 Prompt 字符串
        """
        template = await self._get_template(template_id)
        return self._substitute_variables(template.template_content, variables)

    async def match_template(self, question: str, category: str | None) -> int:
        """
        自动匹配最合适的 Prompt 模板：
        1. 如果指定了 category，在该分类中选择活跃模板
        2. 否则基于问题关键词匹配分类
        3. 回退到默认模板
        """
        if category:
            template = await self._get_by_category(category)
            if template:
                return template.id

        # 关键词分类匹配
        detected_category = self._detect_category(question)
        template = await self._get_by_category(detected_category)
        if template:
            return template.id

        # 使用默认模板
        return await self._get_default_template_id()

    async def rollback_version(self, template_id: int, target_version: int) -> None:
        """回退模板到指定版本。"""
        version_record = await self.db.fetch_one(
            prompt_template_versions.select().where(
                prompt_template_versions.c.template_id == template_id,
                prompt_template_versions.c.version == target_version,
            )
        )
        if not version_record:
            raise VersionNotFoundException(template_id, target_version)

        # 更新当前模板内容为目标版本
        await self.db.execute(
            prompt_templates.update()
            .where(prompt_templates.c.id == template_id)
            .values(
                template_content=version_record.template_content,
                variables=version_record.variables,
                version=version_record.version,
            )
        )

    def _substitute_variables(self, template: str, variables: dict[str, str]) -> str:
        """替换模板中的变量占位符 {{variable_name}}。"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        return result
```

### 5.4 Token 监控服务设计

```python
class TokenMonitorService:
    """
    Token 监控服务：用量记录、配额管理和成本估算。
    """

    # 各模型定价（每千 Token，单位：元）
    MODEL_PRICING = {
        "openai:gpt-4": {"input": 0.21, "output": 0.42},
        "openai:gpt-3.5-turbo": {"input": 0.01, "output": 0.02},
        "qwen:qwen-plus": {"input": 0.008, "output": 0.02},
        "wenxin:ernie-4.0": {"input": 0.12, "output": 0.12},
        "ollama:*": {"input": 0.0, "output": 0.0},  # 本地模型无费用
        "vllm:*": {"input": 0.0, "output": 0.0},
    }

    async def record_usage(
        self,
        user_id: int,
        department_id: int,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        conversation_id: int | None = None,
        request_type: str = "chat",
    ) -> None:
        """记录一次 LLM 调用的 Token 用量和费用。"""
        cost = self._estimate_cost(model_id, input_tokens, output_tokens)

        await self.db.execute(
            token_usage_records.insert().values(
                user_id=user_id,
                department_id=department_id,
                conversation_id=conversation_id,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=cost,
                request_type=request_type,
            )
        )

        # 更新配额计数
        await self._update_quota_counter(user_id, department_id, input_tokens + output_tokens, cost)

    async def check_quota(self, user_id: int) -> None:
        """
        检查用户/部门的 Token 配额：
        - 达到 80% 时发送预警通知
        - 达到 100% 时阻止调用
        """
        user_quota = await self._get_quota("user", user_id)
        if user_quota and user_quota.current_month_tokens >= user_quota.monthly_token_limit:
            raise QuotaExceededException(target_type="user", target_id=user_id)

        dept_id = await self._get_user_department(user_id)
        dept_quota = await self._get_quota("department", dept_id)
        if dept_quota and dept_quota.current_month_tokens >= dept_quota.monthly_token_limit:
            raise QuotaExceededException(target_type="department", target_id=dept_id)

        # 检查预警阈值
        await self._check_alert_threshold(user_quota)
        await self._check_alert_threshold(dept_quota)

    async def check_budget_limit(self) -> bool:
        """检查总费用是否达到预算上限，达到则暂停非关键调用。"""
        budget = await self._get_global_budget()
        if not budget:
            return True

        current_cost = await self._get_current_month_total_cost()
        return current_cost < budget.monthly_cost_limit

    def _estimate_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """估算单次调用费用。"""
        pricing = self._get_pricing(model_id)
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000

    async def _check_alert_threshold(self, quota) -> None:
        """当用量达到配额的 alert_threshold 比例时，发送预警。"""
        if not quota or not quota.is_active:
            return
        ratio = quota.current_month_tokens / quota.monthly_token_limit
        if ratio >= quota.alert_threshold:
            await self._send_quota_alert(quota)
```

### 5.5 LLM 安全设计

```python
class LLMSecurityFilter:
    """
    LLM 安全过滤器：Prompt 注入检测、敏感信息脱敏、输出过滤。
    """

    # Prompt 注入特征模式
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+above",
        r"你(现在)?是一个",
        r"forget\s+(everything|all)",
        r"system\s*prompt",
        r"disregard\s+(all|previous)",
        r"new\s+instructions?:",
        r"override\s+(system|safety)",
    ]

    # PII 检测模式
    PII_PATTERNS = {
        "phone": r"1[3-9]\d{9}",
        "id_card": r"\d{17}[\dXx]",
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "name_pattern": r"[\u4e00-\u9fa5]{2,4}(?=先生|女士|经理|总|主任)",
    }

    async def check_prompt_injection(self, content: str) -> None:
        """
        Prompt 注入检测：
        - 基于正则模式匹配已知注入模式
        - 检测异常的指令格式
        - 高风险输入直接拒绝并记录安全事件
        """
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                await self._log_security_event(
                    event_type="prompt_injection",
                    severity="high",
                    input_content=content[:500],
                    detection_details={"pattern": pattern},
                )
                raise PromptInjectionDetectedException()

    async def sanitize_outbound(self, request: LLMRequest) -> LLMRequest:
        """
        出站内容安全过滤（发送至云端 LLM 前）：
        1. 移除 PII（人名、手机号、身份证号等）
        2. 过滤机密/绝密级别文档内容
        3. 替换为脱敏占位符
        """
        sanitized_prompt = request.prompt

        # PII 脱敏
        for pii_type, pattern in self.PII_PATTERNS.items():
            sanitized_prompt = re.sub(
                pattern, f"[{pii_type.upper()}_REDACTED]", sanitized_prompt
            )

        # 文档分类过滤
        sanitized_prompt = self._filter_classified_content(sanitized_prompt)

        return LLMRequest(
            prompt=sanitized_prompt,
            task_type=request.task_type,
            stream=request.stream,
        )

    async def filter_output(self, response: LLMResponse) -> LLMResponse:
        """
        输出安全过滤（LLM 返回内容展示前）：
        - 检测输出中是否包含敏感信息标记
        - 过滤可能的 PII 泄露
        """
        filtered_content = response.content
        for pii_type, pattern in self.PII_PATTERNS.items():
            filtered_content = re.sub(
                pattern, f"[已脱敏]", filtered_content
            )
        return LLMResponse(
            content=filtered_content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    def _filter_classified_content(self, content: str) -> str:
        """过滤标记为机密或绝密级别的文档内容。"""
        # 移除 [机密] 或 [绝密] 标记的段落
        lines = content.split("\n")
        filtered_lines = []
        skip = False
        for line in lines:
            if "[机密]" in line or "[绝密]" in line or "[confidential]" in line.lower():
                skip = True
                filtered_lines.append("[此段内容因安全等级限制已移除]")
                continue
            if skip and line.strip() == "":
                skip = False
                continue
            if not skip:
                filtered_lines.append(line)
        return "\n".join(filtered_lines)


class APIKeyManager:
    """
    API Key 管理器：通过 KMS 加密存储，支持定期轮换。
    """

    def __init__(self, kms_client, db: Database):
        self.kms = kms_client
        self.db = db

    async def store_key(self, model_id: str, api_key: str) -> str:
        """加密存储 API Key，返回 KMS 引用 ID。"""
        encrypted = await self.kms.encrypt(api_key.encode())
        key_ref = f"kms://{model_id}/{uuid4().hex}"
        await self.db.execute(
            llm_model_configs.update()
            .where(llm_model_configs.c.model_id == model_id)
            .values(api_key_ref=key_ref)
        )
        return key_ref

    async def get_key(self, model_id: str) -> str:
        """从 KMS 解密获取 API Key。"""
        config = await self.db.fetch_one(
            llm_model_configs.select().where(
                llm_model_configs.c.model_id == model_id
            )
        )
        if not config or not config.api_key_ref:
            raise KeyNotFoundException(model_id)
        decrypted = await self.kms.decrypt(config.api_key_ref)
        return decrypted.decode()

    async def rotate_key(self, model_id: str, new_key: str) -> None:
        """轮换 API Key：存储新 Key 并废弃旧 Key。"""
        old_ref = await self._get_key_ref(model_id)
        new_ref = await self.store_key(model_id, new_key)
        if old_ref:
            await self.kms.schedule_deletion(old_ref)

    async def disable_key(self, model_id: str) -> None:
        """紧急禁用 API Key（泄露或异常时）。"""
        await self.db.execute(
            llm_model_configs.update()
            .where(llm_model_configs.c.model_id == model_id)
            .values(status="inactive", api_key_ref=None)
        )
        await self._trigger_security_alert(model_id)
```

## 6. 部署架构设计

### 6.1 方案对比总览

| 对比维度 | 纯内网部署 | 云服务器 + 安全加固 |
|---------|-----------|-------------------|
| 网络环境 | 完全隔离，无外网访问 | 通过 VPN/防火墙访问 |
| 数据安全 | 物理隔离，最高安全性 | 逻辑隔离 + 加密传输 |
| AI 模型 | 本地部署（离线推理） | 可选私有化部署或加密API调用 |
| 知识库更新 | 离线导入（USB/内网传输） | 受控网络通道更新 |
| 扩展性 | 受限于本地硬件 | 弹性扩容 |
| 运维成本 | 硬件采购 + 运维人力 | 云服务费用 + 少量运维 |
| 合规性 | 满足最严格数据驻留要求 | 需额外合规认证 |
| 可用性 | 依赖本地基础设施 | 云厂商 SLA 保障 |

### 6.2 纯内网部署方案

```
┌─────────────────────────────────────────────────────────────┐
│                   企业内网环境                                │
│                                                             │
│  ┌───────────┐     ┌───────────────────────────────────┐   │
│  │  用户终端  │────▶│       负载均衡 (Nginx)             │   │
│  └───────────┘     └─────────────┬─────────────────────┘   │
│                                  │                          │
│  ┌───────────────────────────────┴──────────────────────┐  │
│  │            应用服务器集群                              │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐           │  │
│  │  │ RAG  │ │报表  │ │权限  │ │ 认证/安全  │           │  │
│  │  └──────┘ └──────┘ └──────┘ └──────────┘           │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │          LLM 服务层                           │   │  │
│  │  │  LLM网关 | 对话管理 | Prompt引擎 | Token监控  │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            数据层                                     │  │
│  │  ┌──────┐  ┌────────┐  ┌──────┐  ┌──────┐          │  │
│  │  │MySQL │  │ChromaDB│  │Milvus│  │Redis │          │  │
│  │  │(主从) │  │        │  │(集群)│  │(哨兵)│          │  │
│  │  └──────┘  └────────┘  └──────┘  └──────┘          │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │   离线 AI 推理层                                      │  │
│  │  ┌──────────────┐  ┌──────────────────────────────┐  │  │
│  │  │Embedding模型 │  │ 本地 LLM 推理                 │  │  │
│  │  │(本地部署)    │  │ Ollama (单机/轻量场景)        │  │  │
│  │  │              │  │ vLLM (高并发/GPU 集群场景)    │  │  │
│  │  └──────────────┘  └──────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐│  │
│  │  │ GPU 资源池: NVIDIA A100/A800 或 RTX 4090        ││  │
│  │  │ 支持多模型并行加载，按任务类型自动路由            ││  │
│  │  └──────────────────────────────────────────────────┘│  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  无外网连接 ✕                                               │
└─────────────────────────────────────────────────────────────┘
```

**关键技术要点：**
- Embedding 模型本地部署（如 `text2vec-base-chinese`）
- LLM 模型本地部署：Ollama 适用于单机轻量场景，vLLM 适用于高并发 GPU 集群
- 支持多模型同时加载（如 Qwen-14B 用于通用问答，CodeLlama 用于代码分析）
- 模型文件通过安全介质离线导入，支持版本管理和回退
- 知识库通过离线包更新：管理员通过安全介质导入文档
- 所有依赖包预装，无需外网 pip/npm 下载
- 定期离线安全补丁更新
- GPU 资源监控和自动调度

### 6.3 云服务器 + 安全加固方案

```
┌─────────────────────────────────────────────────────────────────┐
│                      云服务器环境 (VPC)                            │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                安全边界层                                 │   │
│  │  ┌────────┐  ┌──────────┐  ┌───────────────────┐       │   │
│  │  │WAF/DDoS│  │ 防火墙   │  │ 入侵检测 (IDS)    │       │   │
│  │  │防护    │  │ (安全组) │  │                   │       │   │
│  │  └────────┘  └──────────┘  └───────────────────┘       │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                   │
│  ┌─────────────┐          │          ┌──────────────┐         │
│  │  VPN 网关   │◀─────────┼─────────▶│  IP 白名单    │         │
│  └─────────────┘          │          └──────────────┘         │
│                            │                                   │
│  ┌─────────────────────────┴───────────────────────────────┐   │
│  │        应用子网 (Private Subnet)                         │   │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐              │   │
│  │  │ RAG  │ │报表  │ │权限  │ │ 认证/安全  │              │   │
│  │  └──────┘ └──────┘ └──────┘ └──────────┘              │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │          LLM 服务层                               │  │   │
│  │  │  LLM网关 | 对话管理 | Prompt引擎 | Token监控      │  │   │
│  │  └──────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │        数据子网 (Isolated Subnet)                        │   │
│  │  ┌──────┐  ┌────────┐  ┌──────┐  ┌──────┐             │   │
│  │  │MySQL │  │ChromaDB│  │Milvus│  │Redis │             │   │
│  │  │(RDS) │  │        │  │(集群)│  │      │             │   │
│  │  └──────┘  └────────┘  └──────┘  └──────┘             │   │
│  │  ★ 数据存储节点逻辑隔离，仅应用子网可访问                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │        密钥管理 (KMS)                                    │   │
│  │  ┌────────────────┐  ┌─────────────────────────────┐   │   │
│  │  │ LLM API Key    │  │ 数据加密密钥                 │   │   │
│  │  │ 加密存储/轮换  │  │ AES-256 Master Key          │   │   │
│  │  └────────────────┘  └─────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  出站规则: 仅允许安全更新 + 指定 LLM API 端点 ✓                   │
└─────────────────────────────────────────────────────────────────┘
         │                              │
         │ VPN / 专线                    │ HTTPS (TLS 1.2+)
         │                              │ 仅限指定 LLM API 端点
┌────────┴────────┐          ┌──────────┴──────────┐
│   企业内网用户   │          │   云端 LLM 服务      │
└─────────────────┘          │  OpenAI / 通义千问   │
                             │  文心一言             │
                             └─────────────────────┘
```

**关键安全加固措施：**
- IP 白名单：仅允许企业出口 IP 访问
- VPN 接入：员工通过企业 VPN 连接
- 网络隔离：数据子网与应用子网分离，数据库无公网访问
- DDoS 防护：云厂商原生 DDoS 防护
- 入侵检测：实时流量分析和异常行为告警
- 出站控制：禁止业务数据外传，仅开放安全更新通道和指定 LLM API 端点
- KMS 密钥管理：所有 LLM API Key 通过 KMS 加密存储，支持自动轮换
- LLM 出站网段限制：仅允许 LLM 服务层所在网段发起外部 API 调用

## 7. 技术选型详细说明

### 7.1 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ^3.4 | 前端框架 |
| TypeScript | ^5.3 | 类型安全 |
| Vite | ^5.0 | 构建工具 |
| Pinia | ^2.1 | 状态管理 |
| Vue Router | ^4.2 | 路由管理 |
| Axios | ^1.6 | HTTP 客户端 |
| ECharts | ^5.4 | 图表可视化 |
| Element Plus | ^2.4 | UI 组件库 |
| XLSX.js | ^0.18 | Excel 导出 |

### 7.2 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | ^3.11 | 运行时 |
| FastAPI | ^0.104 | Web 框架 |
| SQLAlchemy | ^2.0 | ORM |
| Pydantic | ^2.5 | 数据验证 |
| python-jose | ^3.3 | JWT 处理 |
| cryptography | ^41.0 | AES-256 加密 |
| LangChain | ^0.1 | RAG 编排 + LLM 调用链 |
| Sentence-Transformers | ^2.2 | 文本嵌入 |
| Pandas | ^2.1 | 数据处理 |
| Celery | ^5.3 | 异步任务队列 |
| python-ldap | ^3.4 | LDAP 集成 |
| Redis (aioredis) | ^5.0 | 缓存/会话 |
| tiktoken | ^0.5 | Token 计数（OpenAI 模型） |
| Ollama Python SDK | ^0.1 | 本地 Ollama 模型调用 |
| vLLM | ^0.2 | 高性能本地模型推理 |
| openai | ^1.6 | OpenAI API 客户端 |
| dashscope | ^1.14 | 通义千问 API 客户端 |

### 7.3 LLM 推理层技术栈

| 技术 | 版本 | 用途 | 适用场景 |
|------|------|------|---------|
| Ollama | ^0.1 | 本地模型管理和推理 | 单机/轻量部署，快速模型切换 |
| vLLM | ^0.2 | 高性能批量推理引擎 | 高并发 GPU 集群，PagedAttention 加速 |
| tiktoken | ^0.5 | OpenAI 系模型 Token 计数 | 精确 Token 预估和计费 |
| transformers | ^4.36 | HuggingFace 模型加载 | 自定义模型微调和加载 |
| CUDA | ^12.0 | GPU 加速 | 本地推理加速 |

### 7.4 数据库选型理由

| 数据库 | 选型理由 |
|--------|---------|
| MySQL 8.0 | 成熟稳定，支持 JSON 类型，事务支持完善，适合结构化业务数据和权限数据存储 |
| ChromaDB | 轻量级向量数据库，适合开发环境和小规模（<100万向量）场景，Python 原生支持 |
| Milvus 2.x | 分布式向量数据库，支持十亿级向量检索，适合生产环境大规模知识库 |
| Redis 7.x | 高性能缓存，支持过期策略，适合会话管理、权限缓存和限流计数 |

## 8. 核心组件设计

### 8.1 RAG 检索引擎

```python
class RAGEngine:
    """RAG 知识检索引擎核心逻辑。"""

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        permission_service: PermissionService,
    ):
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.permission_service = permission_service

    async def search(
        self, query: str, user_id: int, top_k: int = 10
    ) -> list[DocumentFragment]:
        """
        执行知识检索：
        1. 将查询转为嵌入向量
        2. 在向量库中检索相似文档
        3. 根据用户权限过滤结果
        4. 返回排序后的文档片段
        """
        # 1. 生成查询向量
        query_embedding = await self.embedding_model.encode(query)

        # 2. 向量检索（多检索一些，为权限过滤留余量）
        candidates = await self.vector_store.search(
            embedding=query_embedding,
            top_k=top_k * 3,
        )

        # 3. 权限过滤
        user_permissions = await self.permission_service.get_effective_permissions(user_id)
        filtered = [
            doc for doc in candidates
            if self._has_access(doc, user_permissions)
        ]

        # 4. 截取 top_k 并返回
        return filtered[:top_k]

    def _has_access(
        self, doc: DocumentFragment, permissions: list[EffectivePermission]
    ) -> bool:
        """检查用户是否有权访问该文档。"""
        for perm in permissions:
            if perm.resource_type == "knowledge_base":
                if doc.department_id in perm.department_scope or perm.access_level == "admin":
                    return True
                if doc.access_level == "public":
                    return True
        return False
```

### 8.2 报表生成模块

```python
class ReportGenerator:
    """报表生成核心逻辑。"""

    SUPPORTED_CHART_TYPES = ("table", "line_chart", "bar_chart", "pie_chart")

    async def generate(
        self,
        config: ReportConfig,
        params: ReportGenerateRequest,
        user_permissions: list[EffectivePermission],
    ) -> ReportGenerateResponse:
        """
        生成报表：
        1. 验证用户对请求维度的访问权限
        2. 执行数据查询（分页）
        3. 格式化为图表配置
        """
        # 1. 权限过滤维度
        allowed_dimensions = self._filter_dimensions(
            params.dimensions, user_permissions
        )

        # 2. 执行查询（大数据量自动分页）
        data = await self._execute_query(
            config, params, allowed_dimensions
        )

        # 3. 构建图表配置
        chart_config = self._build_chart_config(
            data, params.chart_type
        )

        return ReportGenerateResponse(
            data=data,
            chart_config=chart_config,
            pagination=PaginationInfo(
                page=params.page,
                page_size=params.page_size,
                total=await self._count_total(config, params),
            ),
            generated_at=datetime.utcnow(),
        )

    async def _execute_query(
        self, config: ReportConfig, params: ReportGenerateRequest,
        dimensions: list[str],
    ) -> list[dict]:
        """执行数据查询，超过 10 万条自动分页。"""
        query = self._build_query(config, params, dimensions)
        return await self.db.fetch_all(
            query.offset((params.page - 1) * params.page_size)
                 .limit(params.page_size)
        )
```

### 8.3 会话管理

```python
class SessionManager:
    """会话管理器，处理令牌生命周期和会话超时。"""

    TOKEN_EXPIRE_MINUTES = 30
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15

    async def authenticate(self, username: str, password: str) -> LoginResponse:
        """用户认证流程。"""
        user = await self._get_user(username)

        # 检查锁定状态
        if user and user.locked_until and user.locked_until > datetime.utcnow():
            raise AccountLockedException(
                locked_until=user.locked_until
            )

        # 验证凭证
        if not user or not self._verify_password(password, user.password_hash):
            await self._record_failed_attempt(username)
            raise InvalidCredentialsException()

        # 重置失败计数
        await self._reset_failed_attempts(user.id)

        # 生成令牌
        token = self._create_token(user)
        await self._store_session(token, user)

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=self.TOKEN_EXPIRE_MINUTES * 60,
            user=UserInfo.from_orm(user),
        )

    async def validate_session(self, token: str) -> UserSession | None:
        """验证会话有效性，刷新活跃时间。"""
        session = await self.redis.get(f"session:{self._get_token_id(token)}")
        if not session:
            return None

        session_data = json.loads(session)
        last_active = datetime.fromisoformat(session_data["last_active"])

        # 检查会话超时（30 分钟无操作）
        if (datetime.utcnow() - last_active).total_seconds() > self.TOKEN_EXPIRE_MINUTES * 60:
            await self.redis.delete(f"session:{self._get_token_id(token)}")
            return None

        # 刷新活跃时间
        session_data["last_active"] = datetime.utcnow().isoformat()
        await self.redis.setex(
            f"session:{self._get_token_id(token)}",
            self.TOKEN_EXPIRE_MINUTES * 60,
            json.dumps(session_data),
        )

        return UserSession(**session_data)
```

## 9. 错误处理策略

### 9.1 统一错误响应格式

```python
class ErrorResponse(BaseModel):
    code: str           # 错误代码，如 "AUTH_001"
    message: str        # 用户可读的错误消息
    detail: str | None  # 开发调试信息（仅非生产环境返回）

# 错误代码规范
ERROR_CODES = {
    # 认证错误
    "AUTH_001": "用户名或密码错误",
    "AUTH_002": "账号已锁定，请稍后重试",
    "AUTH_003": "登录会话已过期，请重新登录",
    "AUTH_004": "无效的认证令牌",
    # 权限错误
    "PERM_001": "无权访问该资源",
    "PERM_002": "角色不存在",
    "PERM_003": "无法删除仍有用户关联的角色",
    # 业务错误
    "RAG_001": "知识库检索失败",
    "RAG_002": "未找到匹配结果",
    "REPORT_001": "报表生成失败",
    "REPORT_002": "数据源连接失败",
    "REPORT_003": "导出任务失败",
    # LLM 错误
    "LLM_001": "LLM 服务暂时不可用，已降级为检索模式",
    "LLM_002": "Prompt 注入检测：请求被拒绝",
    "LLM_003": "Token 配额已用尽，请联系管理员",
    "LLM_004": "LLM 调用频率超限，请稍后重试",
    "LLM_005": "对话会话不存在或已归档",
    "LLM_006": "模型配置验证失败",
    "LLM_007": "所有模型均不可用",
    "LLM_008": "回答相关度过低，建议调整问题",
    # 系统错误
    "SYS_001": "系统内部错误",
    "SYS_002": "服务暂时不可用",
}
```

### 9.2 故障隔离设计

```python
from circuitbreaker import circuit

class ServiceCircuitBreaker:
    """服务熔断器，实现故障隔离。"""

    @circuit(failure_threshold=5, recovery_timeout=30)
    async def call_rag_service(self, request):
        """RAG 服务调用，5 次失败后熔断 30 秒。"""
        return await self.rag_client.search(request)

    @circuit(failure_threshold=3, recovery_timeout=60)
    async def call_report_data_source(self, query):
        """报表数据源调用，3 次失败后熔断 60 秒。"""
        return await self.db_client.execute(query)

    @circuit(failure_threshold=3, recovery_timeout=45)
    async def call_llm_model(self, model_id, request):
        """LLM 模型调用，3 次失败后熔断 45 秒，触发 Failover 到下一优先级模型。"""
        return await self.llm_gateway.invoke_model(model_id, request)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: 权限过滤保证无越权访问（知识检索）

*For any* 用户和任意知识库检索结果集，经过权限过滤后返回的文档片段集合中，不应包含任何该用户角色无权访问的文档（即文档的 department_id 不在用户权限范围内且文档 access_level 非 public）。

**Validates: Requirements 1.3**

### Property 2: 报表维度权限过滤完整性

*For any* 用户和任意报表页面请求，返回的数据维度和指标列表中的每一项，都必须属于该用户角色明确授权的资源范围内。

**Validates: Requirements 2.5**

### Property 3: 角色 CRUD 的数据一致性（Round-trip）

*For any* 有效的角色定义（包含名称和权限列表），创建角色后再读取该角色，返回的权限定义应与创建时提交的完全一致。

**Validates: Requirements 3.1**

### Property 4: 有效权限计算的最高优先原则

*For any* 拥有多个角色的用户，当多个角色对同一资源定义了不同访问级别时，该用户对该资源的有效权限应等于所有角色中该资源的最高访问级别。

**Validates: Requirements 3.4, 3.7**

### Property 5: 无角色用户的访问拒绝

*For any* 没有任何角色分配的用户，对任何业务资源的访问请求都应被拒绝（返回权限不足错误）。

**Validates: Requirements 3.5**

### Property 6: 审计日志完整性

*For any* 数据查询、导出操作或权限变更操作，系统必须生成包含完整字段（用户身份、操作时间、操作类型、涉及数据范围/变更内容）的审计日志记录。

**Validates: Requirements 3.6, 5.3**

### Property 7: 认证令牌的有效性边界

*For any* 已签发的认证令牌，当令牌过期时间已超过当前时间时，使用该令牌的任何 API 请求都应被拒绝。

**Validates: Requirements 4.3**

### Property 8: 登录失败锁定机制

*For any* 用户账号，在 1 分钟窗口内，当连续登录失败次数达到 5 次时，该账号应被锁定；当失败次数少于 5 次时，账号不应被锁定。

**Validates: Requirements 4.4**

### Property 9: 会话超时终止

*For any* 用户会话，当最后一次活跃操作距今超过 30 分钟时，该会话应被自动终止，后续请求应要求重新认证。

**Validates: Requirements 4.5**

### Property 10: 敏感数据加密 Round-trip

*For any* 敏感数据字段值，经过 AES-256 加密存储后再解密读取，应得到与原始值完全相同的数据。

**Validates: Requirements 5.1**

### Property 11: 向量库文档访问控制标记一致性

*For any* 存入向量数据库的文档，其访问控制标记（access_level、access_roles、department_id）在检索时应与存入时保持一致，且检索结果应尊重这些标记进行过滤。

**Validates: Requirements 5.4**

### Property 12: 异常检测阈值准确性

*For any* 用户的数据访问操作序列，当同一操作在检测窗口内的执行次数超过设定阈值时，系统应触发安全告警；当未超过阈值时，不应触发告警。

**Validates: Requirements 5.5**

### Property 13: 大数据量分页正确性

*For any* 超过 10 万条记录的报表查询请求，返回结果应采用分页方式，首页数据条数不超过 page_size 参数值，且分页元数据（total、page、page_size）应准确反映完整数据集信息。

**Validates: Requirements 6.4**

### Property 14: 报表导出数据完整性

*For any* 有效的报表数据集，导出为 Excel 或 PDF 格式后，文件应为有效格式且包含源数据中的全部记录。

**Validates: Requirements 2.3**

### Property 15: 角色分配即时生效

*For any* 角色分配操作，在管理员将角色分配给用户后，立即查询该用户的有效权限应包含新角色定义的全部权限。

**Validates: Requirements 3.2**

### Property 16: LLM 回答结构完整性与来源可追溯

*For any* 用户问题和 RAG 引擎返回的检索文档集合，LLM 服务生成的回答应包含摘要、关键结论和来源引用三部分结构，且回答中引用的每个文档来源都必须存在于输入的检索文档集合中。

**Validates: Requirements 9.1, 9.2**

### Property 17: LLM 回答相关度阈值检测

*For any* LLM 生成的回答，当其与检索文档的相关度评分低于设定阈值时，系统应标记该回答为低置信度；当评分高于阈值时，不应添加低置信度标记。

**Validates: Requirements 9.5**

### Property 18: 模型 Failover 优先级遵循

*For any* 包含多个模型配置的 LLM 网关，当高优先级模型不可用时，系统应按优先级顺序选择下一个可用模型进行调用，且最终选中的模型优先级应是所有可用模型中最高的。

**Validates: Requirements 10.4**

### Property 19: 对话上下文窗口大小约束

*For any* 多轮对话会话，构建 Prompt 时纳入的历史对话轮数不应超过 20 轮；当对话总轮数超过 20 时，仅保留最近 20 轮。

**Validates: Requirements 11.2**

### Property 20: 对话上下文 Token 限制保证

*For any* 对话上下文，经过摘要压缩后构建的最终 Prompt 的 Token 数不应超过模型最大 Token 限制的 60%（为回答预留空间）。

**Validates: Requirements 11.3**

### Property 21: 会话终止清空上下文

*For any* 活跃的对话会话，当用户主动结束会话或会话超过 24 小时不活跃后，该会话的上下文缓存应被清空，后续查询应返回空上下文。

**Validates: Requirements 11.4, 11.6**

### Property 22: Prompt 模板变量替换完整性

*For any* Prompt 模板和一组完整的变量值映射，渲染后的 Prompt 不应包含未替换的变量占位符（如 `{{variable_name}}`），且每个变量对应的值应正确出现在渲染结果中。

**Validates: Requirements 12.2**

### Property 23: Prompt 模板版本回退正确性

*For any* 具有版本历史的 Prompt 模板，执行回退到指定历史版本后，当前模板内容应与该历史版本的内容完全一致。

**Validates: Requirements 12.6**

### Property 24: Prompt 注入检测与拦截

*For any* 包含已知 Prompt 注入模式（如 "ignore previous instructions"、"你现在是一个"等指令篡改特征）的用户输入，系统应检测到威胁并拒绝该请求。

**Validates: Requirements 13.1**

### Property 25: 出站内容敏感信息脱敏

*For any* 发送至云端 LLM 服务的内容，经脱敏处理后不应包含手机号、身份证号等 PII 信息，且标记为"机密"或"绝密"级别的文档内容不应出现在出站请求中。

**Validates: Requirements 13.2, 13.7**

### Property 26: LLM 调用频率限制

*For any* 单个用户，在一小时时间窗口内，当 LLM 调用次数达到 100 次上限后，后续调用请求应被拒绝；当调用次数未达上限时，请求应被正常处理。

**Validates: Requirements 13.5**

### Property 27: LLM 调用审计日志完整性

*For any* LLM 调用（无论成功或失败），系统应生成包含请求时间、用户身份、模型标识、输入/输出 Token 数和响应状态的完整审计日志记录。

**Validates: Requirements 13.3, 15.5**

### Property 28: Token 用量记录完整性

*For any* LLM 调用完成后，Token 监控服务应创建一条包含输入 Token 数、输出 Token 数和费用估算的用量记录，且费用估算应等于（输入Token × 输入单价 + 输出Token × 输出单价）。

**Validates: Requirements 16.1**

### Property 29: Token 配额执行正确性

*For any* 设置了 Token 配额的用户或部门，当累计用量达到配额 80% 时应触发预警通知；当达到 100% 时应阻止后续 LLM 调用。低于 80% 时不应触发预警，低于 100% 时不应阻止调用。

**Validates: Requirements 16.3, 16.4**

### Property 30: API Key 网段访问控制

*For any* 发起外部 LLM API 调用的请求，仅当请求源 IP 属于配置的内部服务网段白名单时才允许通过；来自非白名单网段的请求应被拒绝。

**Validates: Requirements 15.4**

### Property 31: 本地模型任务路由正确性

*For any* 指定了任务类型的 LLM 请求，当存在多个本地模型时，LLM 网关应选择配置中声明支持该任务类型且优先级最高的可用模型。

**Validates: Requirements 14.5**
