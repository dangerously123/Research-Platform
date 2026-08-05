"""File upload and management API routes."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, get_db
from app.core.security import file_security_scanner
from app.models.file import UploadedFile
from app.schemas.file import FileInfoResponse, FileListResponse, FileUploadResponse
from app.services.auth.dependencies import get_current_user
from app.services.file_processor import process_file
from app.services.file_processor.storage import (
    FILE_SIZE_LIMITS,
    delete_file as delete_stored_file,
    detect_file_type,
    generate_storage_path,
    get_absolute_path,
    prepare_storage_path,
    validate_file,
)

router = APIRouter()
logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
SCAN_HEADER_BYTES = 8192


async def _process_uploaded_file(file_id: int) -> None:
    """Background file parsing task that updates processing status."""
    async with async_session_factory() as session:
        try:
            result = await session.execute(select(UploadedFile).where(UploadedFile.id == file_id))
            uploaded = result.scalar_one_or_none()
            if not uploaded:
                logger.warning("[Files] Background processing skipped; file_id=%s not found", file_id)
                return

            uploaded.process_status = "processing"
            await session.flush()

            abs_path = get_absolute_path(uploaded.storage_path)
            process_result = await process_file(abs_path, uploaded.file_type, uploaded.mime_type)

            if process_result.success:
                uploaded.process_status = "completed"
                uploaded.extracted_content = process_result.text_content or None
                uploaded.extracted_metadata = process_result.structured_data or None
                uploaded.image_description = process_result.image_description or None
                uploaded.ocr_text = process_result.ocr_text or None
                uploaded.error_message = None
            else:
                uploaded.process_status = "failed"
                uploaded.error_message = (process_result.error or "Processing failed")[:512]

            uploaded.processed_at = datetime.now(timezone.utc)
            await session.commit()
        except Exception as exc:
            logger.exception("[Files] Background processing failed: file_id=%s", file_id)
            await session.rollback()
            async with async_session_factory() as fail_session:
                fail_result = await fail_session.execute(select(UploadedFile).where(UploadedFile.id == file_id))
                failed = fail_result.scalar_one_or_none()
                if failed:
                    failed.process_status = "failed"
                    failed.error_message = str(exc)[:512]
                    failed.processed_at = datetime.now(timezone.utc)
                    await fail_session.commit()


@router.post("/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file, persist it safely, and process it in the background."""
    user_id = current_user["user_id"]
    filename = file.filename or "unknown"
    mime_type = file.content_type or "application/octet-stream"
    file_type = detect_file_type(mime_type, filename)
    max_size = FILE_SIZE_LIMITS.get(file_type, FILE_SIZE_LIMITS["other"])

    storage_path = generate_storage_path(user_id, filename)
    abs_path = prepare_storage_path(storage_path)
    total_size = 0
    header = bytearray()

    try:
        with open(abs_path, "wb") as output:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File too large; {file_type} limit is {max_size // (1024 * 1024)}MB",
                    )
                if len(header) < SCAN_HEADER_BYTES:
                    needed = SCAN_HEADER_BYTES - len(header)
                    header.extend(chunk[:needed])
                output.write(chunk)
    except Exception:
        delete_stored_file(storage_path)
        raise
    finally:
        await file.close()

    is_valid, error = validate_file(filename, total_size, mime_type)
    if not is_valid:
        delete_stored_file(storage_path)
        raise HTTPException(status_code=400, detail=error)

    scan_ok, scan_reason = file_security_scanner.scan(filename, bytes(header), mime_type)
    if not scan_ok:
        delete_stored_file(storage_path)
        raise HTTPException(status_code=400, detail=f"File security check failed: {scan_reason}")

    uploaded = UploadedFile(
        user_id=user_id,
        conversation_id=conversation_id,
        original_name=filename,
        storage_path=storage_path,
        file_type=file_type,
        mime_type=mime_type,
        file_size=total_size,
        process_status="pending",
    )

    try:
        db.add(uploaded)
        await db.flush()
        await db.refresh(uploaded)
        await db.commit()
    except Exception:
        delete_stored_file(storage_path)
        raise

    background_tasks.add_task(_process_uploaded_file, uploaded.id)

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
    """Get file details for the current user."""
    result = await db.execute(
        select(UploadedFile).where(
            UploadedFile.id == file_id,
            UploadedFile.user_id == current_user["user_id"],
        )
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

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
    """List files for the current user."""
    conditions = [UploadedFile.user_id == current_user["user_id"]]
    if conversation_id:
        conditions.append(UploadedFile.conversation_id == conversation_id)

    total = (await db.execute(select(func.count(UploadedFile.id)).where(*conditions))).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        select(UploadedFile)
        .where(*conditions)
        .order_by(UploadedFile.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    files = result.scalars().all()

    return FileListResponse(
        files=[
            FileUploadResponse(
                file_id=item.id,
                original_name=item.original_name,
                file_type=item.file_type,
                mime_type=item.mime_type,
                file_size=item.file_size,
                process_status=item.process_status,
                created_at=item.created_at,
            )
            for item in files
        ],
        total=total,
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file_endpoint(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user-owned file record and its stored file."""
    result = await db.execute(
        select(UploadedFile).where(
            UploadedFile.id == file_id,
            UploadedFile.user_id == current_user["user_id"],
        )
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    storage_path = file_record.storage_path
    if not delete_stored_file(storage_path):
        logger.warning("[Files] Stored file deletion failed or file missing: file_id=%s path=%s", file_id, storage_path)

    await db.delete(file_record)
