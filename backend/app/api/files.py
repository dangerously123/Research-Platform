"""文件上传与管理 API 路由。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.file import UploadedFile
from app.schemas.file import FileInfoResponse, FileListResponse, FileUploadResponse
from app.services.auth.dependencies import get_current_user
from app.services.file_processor import process_file
from app.services.file_processor.storage import (
    detect_file_type,
    generate_storage_path,
    get_absolute_path,
    save_file,
    validate_file,
)

router = APIRouter()


@router.post("/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文件。支持图片、Excel、CSV、PDF、Word、文本文件。
    上传后自动触发内容提取处理。
    """
    user_id = current_user["user_id"]

    # 读取文件内容
    content = await file.read()
    file_size = len(content)
    filename = file.filename or "unknown"
    mime_type = file.content_type or "application/octet-stream"

    # 验证文件
    is_valid, error = validate_file(filename, file_size, mime_type)
    if not is_valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=error)

    # 检测文件类型
    file_type = detect_file_type(mime_type, filename)

    # 生成存储路径并保存
    storage_path = generate_storage_path(user_id, filename)
    await save_file(content, storage_path)

    # 写入数据库
    uploaded = UploadedFile(
        user_id=user_id,
        conversation_id=conversation_id,
        original_name=filename,
        storage_path=storage_path,
        file_type=file_type,
        mime_type=mime_type,
        file_size=file_size,
        process_status="processing",
    )
    db.add(uploaded)
    await db.flush()

    # 同步处理文件内容提取
    abs_path = get_absolute_path(storage_path)
    result = await process_file(abs_path, file_type, mime_type)

    # 更新处理结果
    if result.success:
        uploaded.process_status = "completed"
        uploaded.extracted_content = result.text_content or None
        uploaded.extracted_metadata = result.structured_data or None
        uploaded.image_description = result.image_description or None
        uploaded.ocr_text = result.ocr_text or None
        uploaded.processed_at = datetime.now(timezone.utc)
    else:
        uploaded.process_status = "failed"
        uploaded.error_message = result.error
        uploaded.processed_at = datetime.now(timezone.utc)

    await db.flush()

    return FileUploadResponse(
        file_id=uploaded.id,
        original_name=uploaded.original_name,
        file_type=uploaded.file_type,
        mime_type=uploaded.mime_type,
        file_size=uploaded.file_size,
        process_status=uploaded.process_status,
        created_at=uploaded.created_at,
    )


@router.get("/{file_id}", response_model=FileInfoResponse)
async def get_file_info(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文件详细信息（含提取内容）。"""
    stmt = select(UploadedFile).where(
        UploadedFile.id == file_id,
        UploadedFile.user_id == current_user["user_id"],
    )
    result = await db.execute(stmt)
    file_record = result.scalar_one_or_none()

    if not file_record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileInfoResponse(
        file_id=file_record.id,
        original_name=file_record.original_name,
        file_type=file_record.file_type,
        mime_type=file_record.mime_type,
        file_size=file_record.file_size,
        process_status=file_record.process_status,
        extracted_content=file_record.extracted_content,
        extracted_metadata=file_record.extracted_metadata,
        image_description=file_record.image_description,
        ocr_text=file_record.ocr_text,
        error_message=file_record.error_message,
        created_at=file_record.created_at,
        processed_at=file_record.processed_at,
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    conversation_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户文件列表。"""
    user_id = current_user["user_id"]
    conditions = [UploadedFile.user_id == user_id]
    if conversation_id:
        conditions.append(UploadedFile.conversation_id == conversation_id)

    # 总数
    count_stmt = select(func.count(UploadedFile.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    # 分页数据
    offset = (page - 1) * page_size
    stmt = (
        select(UploadedFile)
        .where(*conditions)
        .order_by(UploadedFile.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    files = result.scalars().all()

    return FileListResponse(
        files=[
            FileUploadResponse(
                file_id=f.id,
                original_name=f.original_name,
                file_type=f.file_type,
                mime_type=f.mime_type,
                file_size=f.file_size,
                process_status=f.process_status,
                created_at=f.created_at,
            )
            for f in files
        ],
        total=total,
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file_endpoint(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文件。"""
    from app.services.file_processor.storage import delete_file as del_file

    stmt = select(UploadedFile).where(
        UploadedFile.id == file_id,
        UploadedFile.user_id == current_user["user_id"],
    )
    result = await db.execute(stmt)
    file_record = result.scalar_one_or_none()

    if not file_record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在")

    # 删除物理文件
    del_file(file_record.storage_path)

    # 删除数据库记录
    await db.delete(file_record)
