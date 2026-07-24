"""数据库模型汇总导入，确保 Alembic 能发现所有模型。"""

from app.models.user import User, Role, Permission, UserRole, Department  # noqa: F401
from app.models.audit import AuditLog, PermissionChangeLog, SecurityAlert  # noqa: F401
from app.models.report import ReportConfig, ExportTask  # noqa: F401
from app.models.llm import (  # noqa: F401
    LLMConversation,
    LLMMessage,
    PromptTemplate,
    PromptTemplateVersion,
    TokenUsageRecord,
    TokenQuota,
    LLMModelConfig,
    LLMSecurityEvent,
)
from app.models.memory import MemoryRecord  # noqa: F401
