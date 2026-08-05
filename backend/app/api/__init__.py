"""Aggregate API router."""

from fastapi import APIRouter

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.roles import router as roles_router
from app.api.permissions import router as permissions_router
from app.api.knowledge import router as knowledge_router
from app.api.reports import router as reports_router
from app.api.llm_conversations import router as llm_conversations_router
from app.api.llm_models import router as llm_models_router
from app.api.prompts import router as prompts_router
from app.api.tokens import router as tokens_router
from app.api.audit import router as audit_router
from app.api.memories import router as memories_router
from app.api.tools import router as tools_router
from app.api.files import router as files_router
from app.api.observability import router as observability_router
from app.api.eval import router as eval_router
from app.api.admin import router as admin_router

api_router = APIRouter(prefix=settings.API_V1_PREFIX)

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(roles_router, prefix="/roles", tags=["roles"])
api_router.include_router(permissions_router, prefix="/users", tags=["permissions"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(llm_conversations_router, prefix="/llm/conversations", tags=["llm-conversations"])
api_router.include_router(llm_models_router, prefix="/llm/models", tags=["llm-models"])
api_router.include_router(prompts_router, prefix="/prompts/templates", tags=["prompt-templates"])
api_router.include_router(tokens_router, prefix="/tokens", tags=["tokens"])
api_router.include_router(audit_router, prefix="/audit", tags=["audit"])
api_router.include_router(memories_router, prefix="/memories", tags=["memories"])
api_router.include_router(tools_router, prefix="/tools", tags=["tools"])
api_router.include_router(files_router, prefix="/files", tags=["files"])
api_router.include_router(observability_router, prefix="/observability", tags=["observability"])
api_router.include_router(eval_router, prefix="/eval", tags=["eval"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
