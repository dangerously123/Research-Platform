"""Local storage helpers for uploaded files."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

UPLOAD_ROOT = Path("uploads")

FILE_SIZE_LIMITS: dict[str, int] = {
    "image": 10 * 1024 * 1024,
    "pdf": 50 * 1024 * 1024,
    "excel": 20 * 1024 * 1024,
    "csv": 20 * 1024 * 1024,
    "word": 50 * 1024 * 1024,
    "text": 5 * 1024 * 1024,
    "other": 10 * 1024 * 1024,
}

MIME_TYPE_MAP: dict[str, str] = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/webp": "image",
    "image/bmp": "image",
    "image/gif": "image",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.ms-excel": "excel",
    "text/csv": "csv",
    "application/csv": "csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
    "application/msword": "word",
    "text/plain": "text",
    "text/markdown": "text",
}

EXTENSION_TYPE_MAP: dict[str, str] = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".bmp": "image",
    ".gif": "image",
    ".pdf": "pdf",
    ".xlsx": "excel",
    ".xls": "excel",
    ".csv": "csv",
    ".doc": "word",
    ".docx": "word",
    ".txt": "text",
    ".md": "text",
}

ALLOWED_EXTENSIONS = set(EXTENSION_TYPE_MAP)


def detect_file_type(mime_type: str, filename: str) -> str:
    mime_type = (mime_type or "").lower()
    if mime_type in MIME_TYPE_MAP:
        return MIME_TYPE_MAP[mime_type]
    return EXTENSION_TYPE_MAP.get(Path(filename).suffix.lower(), "other")


def validate_file(filename: str, file_size: int, mime_type: str) -> tuple[bool, str]:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension: {ext}"

    file_type = detect_file_type(mime_type, filename)
    max_size = FILE_SIZE_LIMITS.get(file_type, FILE_SIZE_LIMITS["other"])
    if file_size <= 0:
        return False, "File is empty"
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        return False, f"File too large: {actual_mb:.1f}MB; {file_type} limit is {max_mb:.0f}MB"

    return True, ""


def generate_storage_path(user_id: int, filename: str) -> str:
    now = datetime.now()
    ext = Path(filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:12]
    return str(UPLOAD_ROOT / f"{now.year}" / f"{now.month:02d}" / f"{user_id}_{unique_id}{ext}")


def get_upload_root() -> Path:
    return UPLOAD_ROOT.resolve()


def get_absolute_path(storage_path: str) -> str:
    abs_path = Path(storage_path).resolve()
    upload_root = get_upload_root()
    try:
        abs_path.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("Storage path escapes upload root") from exc
    return str(abs_path)


def prepare_storage_path(storage_path: str) -> Path:
    abs_path = Path(storage_path).resolve()
    upload_root = get_upload_root()
    try:
        abs_path.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("Storage path escapes upload root") from exc
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    return abs_path


async def save_file(content: bytes, storage_path: str) -> str:
    abs_path = prepare_storage_path(storage_path)
    with open(abs_path, "wb") as file:
        file.write(content)
    return str(abs_path)


def delete_file(storage_path: str) -> bool:
    try:
        abs_path = Path(get_absolute_path(storage_path))
        if abs_path.exists():
            os.remove(abs_path)
            return True
    except Exception:
        return False
    return False
