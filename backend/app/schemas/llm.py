"""LLM 相关请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ========== 对话 ==========

class CreateConversationRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    file_ids: list[int] = Field(default_factory=list, description="关联的文件ID列表")
    use_rag: bool = True
    stream: bool = True


class DocumentSource(BaseModel):
    doc_id: str
    title: str
    relevance_score: float
    snippet: str


class LLMMessageResponse(BaseModel):
    message_id: int
    role: str
    content: str
    sources: list[DocumentSource] = []
    relevance_score: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class ConversationResponse(BaseModel):
    id: int
    title: str | None
    status: str
    model_id: str | None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    created_at: datetime


class ConversationHistoryResponse(BaseModel):
    conversation_id: int
    messages: list[LLMMessageResponse]
    total_tokens: int


# ========== Prompt 模板 ==========

class VariableDefinition(BaseModel):
    name: str
    description: str
    required: bool = True


class CreatePromptTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field(default="general")
    template_content: str
    variables: list[VariableDefinition] = []


class UpdatePromptTemplateRequest(BaseModel):
    name: str | None = None
    template_content: str | None = None
    variables: list[VariableDefinition] | None = None
    is_active: bool | None = None
    change_description: str = ""


class TemplatePreviewRequest(BaseModel):
    variables: dict[str, str]


class TemplatePreviewResponse(BaseModel):
    rendered_content: str
    token_count: int


class PromptTemplateResponse(BaseModel):
    id: int
    name: str
    category: str
    template_content: str
    variables: list | None = None
    version: int
    is_active: bool
    is_default: bool


class TemplateVersionResponse(BaseModel):
    id: int
    version: int
    template_content: str
    changed_by: int
    change_description: str | None
    created_at: datetime


# ========== Token 监控 ==========

class SetQuotaRequest(BaseModel):
    target_type: str = Field(..., description="user/department")
    target_id: int
    monthly_token_limit: int
    monthly_cost_limit: float | None = None
    alert_threshold: float = 0.8


class TokenUsageSummary(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    total_calls: int


class TokenDashboardResponse(BaseModel):
    current_month: TokenUsageSummary
    quotas: list[dict] = []


# ========== LLM 模型管理 ==========

class AddModelRequest(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=64)
    model_name: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., description="ollama/vllm/openai/qwen/wenxin")
    endpoint_url: str
    api_key: str | None = None
    priority: int = 0
    context_window: int = Field(default=8192, description="模型上下文窗口大小（总 Token 数）")
    max_tokens: int = 4096
    temperature: float = 0.7
    task_types: list[str] | None = None


class ModelConfigResponse(BaseModel):
    model_id: str
    model_name: str
    provider: str
    status: str
    priority: int
    avg_latency_ms: int | None
    last_health_check: datetime | None


class HealthCheckResponse(BaseModel):
    model_id: str
    status: str
    latency_ms: int
    error_message: str | None = None
