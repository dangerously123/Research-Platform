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
    流程：验证 → 安全扫描 → 存储 → 异步处理（小文件同步，大文件返回 processing）。
    """
    from app.core.security import file_security_scanner
    from app.services.file_processor.storage import FILE_SIZE_LIMITS

    user_id = current_user["user_id"]
    filename = file.filename or "unknown"
    mime_type = file.content_type or "application/octet-stream"

    # 1. 先验证文件名和扩展名（不读内容）
    file_type = detect_file_type(mime_type, filename)
    max_size = FILE_SIZE_LIMITS.get(file_type, FILE_SIZE_LIMITS.get("other", 10 * 1024 * 1024))

    # 2. 流式读取，限制最大大小（避免一次性撑爆内存）
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 每次读 1MB
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            from fastapi import HTTPException
            max_mb = max_size / (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"文件过大，{file_type} 类型限制为 {max_mb:.0f}MB",
            )
        chunks.append(chunk)

    content = b"".join(chunks)
    file_size = total_size

    # 3. 验证文件（扩展名、文件名安全）
    is_valid, error = validate_file(filename, file_size, mime_type)
    if not is_valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=error)

    # 4. 安全扫描（魔术字节、双扩展名、路径穿越）
    scan_ok, scan_reason = file_security_scanner.scan(filename, content[:8192], mime_type)
    if not scan_ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"文件安全检查未通过: {scan_reason}")

    # 5. 存储文件
    storage_path = generate_storage_path(user_id, filename)
    await save_file(content, storage_path)

    # 6. 写入数据库
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

    # 7. 处理文件内容：小文件同步处理，大文件标记为 processing 后续异步
    SYNC_THRESHOLD = 5 * 1024 * 1024  # 5MB 以内同步处理
    if file_size <= SYNC_THRESHOLD:
        abs_path = get_absolute_path(storage_path)
        result = await process_file(abs_path, file_type, mime_type)

        if result.success:
            uploaded.process_status = "completed"
            uploaded.extracted_content = result.text_content or None
            uploaded.extracted_metadata = result.structured_data or None
            uploaded.image_description = result.image_description or None
            uploaded.ocr_text = result.ocr_text or None
        else:
            uploaded.process_status = "failed"
            uploaded.error_message = result.error

        from datetime import datetime, timezone
        uploaded.processed_at = datetime.now(timezone.utc)
    # 大文件保持 processing 状态，由后台 Celery 处理

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
    """删除文件（物理文件删除失败时记录日志但仍删除数据库记录）。"""
    import logging
    from app.services.file_processor.storage import delete_file as del_file

    logger = logging.getLogger(__name__)

    stmt = select(UploadedFile).where(
        UploadedFile.id == file_id,
        UploadedFile.user_id == current_user["user_id"],
    )
    result = await db.execute(stmt)
    file_record = result.scalar_one_or_none()

    if not file_record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在")

    # 删除物理文件（失败时记录但不阻塞）
    storage_path = file_record.storage_path
    file_deleted = del_file(storage_path)
    if not file_deleted:
        logger.warning(
            f"[Files] 物理文件删除失败（可能已不存在）: "
            f"file_id={file_id} path={storage_path}"
        )

    # 删除数据库记录
    await db.delete(file_record)
