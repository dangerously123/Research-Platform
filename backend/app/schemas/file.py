"""文件上传相关请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


class FileUploadResponse(BaseModel):
    """文件上传成功响应。"""
    file_id: int
    original_name: str
    file_type: str
    mime_type: str
    file_size: int
    process_status: str
    created_at: datetime


class FileInfoResponse(BaseModel):
    """文件详细信息响应。"""
    file_id: int
    original_name: str
    file_type: str
    mime_type: str
    file_size: int
    process_status: str
    extracted_content: str | None = None
    extracted_metadata: dict | None = None
    image_description: str | None = None
    ocr_text: str | None = None
    error_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class FileListResponse(BaseModel):
    """文件列表响应。"""
    files: list[FileUploadResponse]
    total: int
