"""Prompt 模板管理 API 路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.llm import PromptTemplate
from app.schemas.llm import (
    CreatePromptTemplateRequest,
    PromptTemplateResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateVersionResponse,
    UpdatePromptTemplateRequest,
)
from app.services.auth.dependencies import get_current_user
from app.services.llm.prompt_engine import PromptTemplateEngine
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.get("", response_model=list[PromptTemplateResponse])
async def list_templates(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取模板列表。"""
    stmt = select(PromptTemplate).order_by(PromptTemplate.category, PromptTemplate.name)
    result = await db.execute(stmt)
    templates = result.scalars().all()
    return [
        PromptTemplateResponse(
            id=t.id, name=t.name, category=t.category,
            template_content=t.template_content, variables=t.variables,
            version=t.version, is_active=t.is_active, is_default=t.is_default,
        )
        for t in templates
    ]


@router.post("", response_model=PromptTemplateResponse, status_code=201)
async def create_template(
    request: CreatePromptTemplateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """创建模板（管理员）。"""
    engine = PromptTemplateEngine(db=db)
    template = await engine.create_template(
        name=request.name,
        category=request.category,
        template_content=request.template_content,
        variables=[v.model_dump() for v in request.variables] if request.variables else None,
        created_by=current_user["user_id"],
    )
    return PromptTemplateResponse(
        id=template.id, name=template.name, category=template.category,
        template_content=template.template_content, variables=template.variables,
        version=template.version, is_active=template.is_active, is_default=template.is_default,
    )


@router.put("/{template_id}", response_model=PromptTemplateResponse)
async def update_template(
    template_id: int,
    request: UpdatePromptTemplateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """更新模板（管理员）。"""
    engine = PromptTemplateEngine(db=db)
    template = await engine.update_template(
        template_id=template_id,
        changed_by=current_user["user_id"],
        name=request.name,
        template_content=request.template_content,
        variables=[v.model_dump() for v in request.variables] if request.variables else None,
        is_active=request.is_active,
        change_description=request.change_description,
    )
    if not template:
        from app.core.errors import NotFoundException, PERM_002
        raise NotFoundException(PERM_002)

    return PromptTemplateResponse(
        id=template.id, name=template.name, category=template.category,
        template_content=template.template_content, variables=template.variables,
        version=template.version, is_active=template.is_active, is_default=template.is_default,
    )


@router.post("/{template_id}/preview", response_model=TemplatePreviewResponse)
async def preview_template(
    template_id: int,
    request: TemplatePreviewRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """预览模板渲染结果。"""
    engine = PromptTemplateEngine(db=db)
    rendered, token_count = await engine.preview(template_id, request.variables)
    return TemplatePreviewResponse(rendered_content=rendered, token_count=token_count)


@router.get("/{template_id}/versions", response_model=list[TemplateVersionResponse])
async def get_versions(
    template_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取模板版本历史。"""
    engine = PromptTemplateEngine(db=db)
    versions = await engine.get_template_versions(template_id)
    return [
        TemplateVersionResponse(
            id=v.id, version=v.version, template_content=v.template_content,
            changed_by=v.changed_by, change_description=v.change_description,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.post("/{template_id}/rollback/{version}", response_model=PromptTemplateResponse)
async def rollback_template(
    template_id: int,
    version: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """回退模板到指定版本（管理员）。"""
    engine = PromptTemplateEngine(db=db)
    template = await engine.rollback_version(template_id, version)
    if not template:
        from app.core.errors import NotFoundException, PERM_002
        raise NotFoundException(PERM_002)

    return PromptTemplateResponse(
        id=template.id, name=template.name, category=template.category,
        template_content=template.template_content, variables=template.variables,
        version=template.version, is_active=template.is_active, is_default=template.is_default,
    )
