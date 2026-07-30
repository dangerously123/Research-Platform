"""文件处理服务：负责各类文件的内容提取和识别。"""

from app.services.file_processor.base import (
    FileProcessor,
    ProcessResult,
    get_processor_for_type,
    process_file,
)

__all__ = [
    "FileProcessor",
    "ProcessResult",
    "get_processor_for_type",
    "process_file",
]
