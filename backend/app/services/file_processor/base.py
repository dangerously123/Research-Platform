"""文件处理器基类和调度逻辑。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """文件处理结果。"""
    success: bool = True
    text_content: str = ""                      # 提取的文本内容
    structured_data: dict[str, Any] = field(default_factory=dict)  # 结构化数据
    image_description: str = ""                 # 图片描述（VLM）
    ocr_text: str = ""                          # OCR 识别文本
    metadata: dict[str, Any] = field(default_factory=dict)  # 文件元数据
    error: str = ""                             # 错误信息

    def get_context_text(self) -> str:
        """
        生成用于注入 Agent 上下文的文本。
        合并所有提取的内容为一段可读文本。
        """
        parts = []

        if self.image_description:
            parts.append(f"[图片内容描述]: {self.image_description}")

        if self.ocr_text:
            parts.append(f"[图片中的文字]: {self.ocr_text}")

        if self.text_content:
            parts.append(f"[文件内容]: {self.text_content}")

        if self.structured_data:
            # 结构化数据格式化
            if "summary" in self.structured_data:
                parts.append(f"[数据摘要]: {self.structured_data['summary']}")
            if "columns" in self.structured_data:
                parts.append(f"[数据列]: {', '.join(self.structured_data['columns'])}")
            if "preview" in self.structured_data:
                parts.append(f"[数据预览]:\n{self.structured_data['preview']}")

        return "\n\n".join(parts) if parts else ""


class FileProcessor(ABC):
    """文件处理器抽象基类。"""

    @abstractmethod
    async def process(self, file_path: str, mime_type: str) -> ProcessResult:
        """
        处理文件并提取内容。

        Args:
            file_path: 文件在服务器上的存储路径
            mime_type: 文件 MIME 类型

        Returns:
            ProcessResult 包含提取的所有内容
        """
        ...

    @abstractmethod
    def supported_types(self) -> list[str]:
        """返回支持的文件类型标识列表。"""
        ...


# ============================================================
# 处理器注册和调度
# ============================================================

_processors: dict[str, FileProcessor] = {}


def register_processor(file_type: str, processor: FileProcessor) -> None:
    """注册文件处理器。"""
    _processors[file_type] = processor


def get_processor_for_type(file_type: str) -> FileProcessor | None:
    """根据文件类型获取对应的处理器。"""
    return _processors.get(file_type)


async def process_file(file_path: str, file_type: str, mime_type: str) -> ProcessResult:
    """
    处理文件的统一入口。

    Args:
        file_path: 文件存储路径
        file_type: 文件类型标识（image/pdf/excel/csv/word/text）
        mime_type: MIME 类型

    Returns:
        ProcessResult
    """
    processor = get_processor_for_type(file_type)
    if not processor:
        return ProcessResult(
            success=False,
            error=f"不支持的文件类型: {file_type}",
        )

    try:
        result = await processor.process(file_path, mime_type)
        return result
    except Exception as e:
        logger.error(f"文件处理失败 [{file_type}] {file_path}: {e}")
        return ProcessResult(
            success=False,
            error=f"处理失败: {str(e)}",
        )


def _register_all_processors():
    """注册所有内置处理器。"""
    try:
        from app.services.file_processor.image import ImageProcessor
        proc = ImageProcessor()
        for t in proc.supported_types():
            register_processor(t, proc)
    except ImportError:
        logger.warning("[FileProcessor] ImageProcessor 加载失败")

    try:
        from app.services.file_processor.data import DataProcessor
        proc = DataProcessor()
        for t in proc.supported_types():
            register_processor(t, proc)
    except ImportError:
        logger.warning("[FileProcessor] DataProcessor 加载失败")


# 模块加载时注册
_register_all_processors()
