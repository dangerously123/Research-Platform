"""
文件存储服务：管理上传文件的本地存储。

存储结构：
  uploads/
    {year}/{month}/
      {user_id}_{timestamp}_{random}.{ext}
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import settings


# 上传文件根目录（相对于项目根）
UPLOAD_ROOT = Path("uploads")

# 文件大小限制 (bytes)
FILE_SIZE_LIMITS: dict[str, int] = {
    "image": 10 * 1024 * 1024,       # 10 MB
    "pdf": 50 * 1024 * 1024,         # 50 MB
    "excel": 20 * 1024 * 1024,       # 20 MB
    "csv": 20 * 1024 * 1024,         # 20 MB
    "word": 50 * 1024 * 1024,        # 50 MB
    "text": 5 * 1024 * 1024,         # 5 MB
    "other": 10 * 1024 * 1024,       # 10 MB
}

# MIME 类型到文件类型的映射
MIME_TYPE_MAP: dict[str, str] = {
    # 图片
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/webp": "image",
    "image/bmp": "image",
    "image/gif": "image",
    # PDF
    "application/pdf": "pdf",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.ms-excel": "excel",
    # CSV
    "text/csv": "csv",
    "application/csv": "csv",
    # Word
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
    "application/msword": "word",
    # 纯文本
    "text/plain": "text",
    "text/markdown": "text",
}

# 允许的文件扩展名
ALLOWED_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
    ".pdf",
    ".xlsx", ".xls",
    ".csv",
    ".doc", ".docx",
    ".txt", ".md",
}


def detect_file_type(mime_type: str, filename: str) -> str:
    """
    检测文件类型。优先使用 MIME，回退到扩展名。

    Returns:
        文件类型标识: image/pdf/excel/csv/word/text/other
    """
    # MIME 匹配
    file_type = MIME_TYPE_MAP.get(mime_type)
    if file_type:
        return file_type

    # 扩展名匹配
    ext = os.path.splitext(filename)[1].lower()
    ext_map = {
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".webp": "image", ".bmp": "image", ".gif": "image",
        ".pdf": "pdf",
        ".xlsx": "excel", ".xls": "excel",
        ".csv": "csv",
        ".doc": "word", ".docx": "word",
        ".txt": "text", ".md": "text",
    }
    return ext_map.get(ext, "other")


def validate_file(filename: str, file_size: int, mime_type: str) -> tuple[bool, str]:
    """
    验证文件是否允许上传。

    Returns:
        (is_valid, error_message)
    """
    # 检查扩展名
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"不支持的文件类型: {ext}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    # 检查文件大小
    file_type = detect_file_type(mime_type, filename)
    max_size = FILE_SIZE_LIMITS.get(file_type, FILE_SIZE_LIMITS["other"])
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        return False, f"文件过大: {actual_mb:.1f}MB，{file_type} 类型限制为 {max_mb:.0f}MB"

    return True, ""


def generate_storage_path(user_id: int, filename: str) -> str:
    """
    生成文件存储路径。

    格式: uploads/{year}/{month}/{user_id}_{uuid8}.{ext}
    """
    now = datetime.now()
    ext = os.path.splitext(filename)[1].lower()
    unique_id = uuid.uuid4().hex[:8]

    relative_path = (
        UPLOAD_ROOT
        / f"{now.year}"
        / f"{now.month:02d}"
        / f"{user_id}_{unique_id}{ext}"
    )

    return str(relative_path)


async def save_file(content: bytes, storage_path: str) -> str:
    """
    保存文件到本地存储。

    Args:
        content: 文件内容
        storage_path: 相对存储路径

    Returns:
        绝对存储路径
    """
    # 确保目录存在
    abs_path = os.path.abspath(storage_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    with open(abs_path, "wb") as f:
        f.write(content)

    return abs_path


def delete_file(storage_path: str) -> bool:
    """删除已存储的文件。"""
    try:
        abs_path = os.path.abspath(storage_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
            return True
    except Exception:
        pass
    return False


def get_absolute_path(storage_path: str) -> str:
    """获取文件的绝对路径。"""
    return os.path.abspath(storage_path)
