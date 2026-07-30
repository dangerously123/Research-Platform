"""
图片处理器：OCR 文字提取 + 基础图片信息分析。

支持：png, jpg, jpeg, webp, bmp, gif
依赖：
- 优先使用 paddleocr（中文 OCR 效果好）
- 回退到 pytesseract
- 兜底：仅返回图片基础信息
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.file_processor.base import FileProcessor, ProcessResult

logger = logging.getLogger(__name__)


class ImageProcessor(FileProcessor):
    """图片文件处理器。"""

    def supported_types(self) -> list[str]:
        return ["image"]

    async def process(self, file_path: str, mime_type: str) -> ProcessResult:
        """
        处理图片文件：
        1. 获取图片基础信息（尺寸等）
        2. OCR 文字提取
        3. 生成图片描述（如果 VLM 可用）
        """
        if not os.path.exists(file_path):
            return ProcessResult(success=False, error=f"文件不存在: {file_path}")

        # 获取图片基础信息
        metadata = self._get_image_info(file_path)

        # OCR 文字提取
        ocr_text = await self._extract_text_ocr(file_path)

        # 生成描述（基于 OCR 结果和图片信息）
        description = self._generate_basic_description(metadata, ocr_text)

        return ProcessResult(
            success=True,
            text_content="",
            image_description=description,
            ocr_text=ocr_text,
            metadata=metadata,
        )

    def _get_image_info(self, file_path: str) -> dict[str, Any]:
        """获取图片基础信息。"""
        info: dict[str, Any] = {
            "file_size": os.path.getsize(file_path),
        }

        try:
            from PIL import Image
            with Image.open(file_path) as img:
                info["width"] = img.width
                info["height"] = img.height
                info["format"] = img.format
                info["mode"] = img.mode
        except ImportError:
            logger.debug("Pillow 未安装，跳过图片尺寸检测")
        except Exception as e:
            logger.warning(f"获取图片信息失败: {e}")

        return info

    async def _extract_text_ocr(self, file_path: str) -> str:
        """
        OCR 文字提取。
        优先级：PaddleOCR > pytesseract > 空
        """
        # 方案 1: PaddleOCR（中文效果最好）
        text = self._try_paddleocr(file_path)
        if text:
            return text

        # 方案 2: pytesseract
        text = self._try_pytesseract(file_path)
        if text:
            return text

        # 方案 3: 无 OCR 引擎可用
        logger.info("无可用 OCR 引擎，跳过文字提取")
        return ""

    def _try_paddleocr(self, file_path: str) -> str:
        """尝试使用 PaddleOCR 提取文字。"""
        try:
            from paddleocr import PaddleOCR

            # 使用轻量模型，只初始化一次
            if not hasattr(self, "_paddle_ocr"):
                self._paddle_ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang="ch",
                    show_log=False,
                )

            result = self._paddle_ocr.ocr(file_path, cls=True)
            if not result or not result[0]:
                return ""

            # 提取所有识别的文字行
            lines = []
            for line_info in result[0]:
                if line_info and len(line_info) >= 2:
                    text = line_info[1][0]  # (text, confidence)
                    confidence = line_info[1][1]
                    if confidence > 0.5:  # 置信度过滤
                        lines.append(text)

            return "\n".join(lines)
        except ImportError:
            return ""
        except Exception as e:
            logger.warning(f"PaddleOCR 处理失败: {e}")
            return ""

    def _try_pytesseract(self, file_path: str) -> str:
        """尝试使用 pytesseract 提取文字。"""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            # 使用中文+英文识别
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text.strip()
        except ImportError:
            return ""
        except Exception as e:
            logger.warning(f"pytesseract 处理失败: {e}")
            return ""

    def _generate_basic_description(self, metadata: dict, ocr_text: str) -> str:
        """基于图片信息和 OCR 结果生成基础描述。"""
        parts = []

        width = metadata.get("width")
        height = metadata.get("height")
        if width and height:
            parts.append(f"图片尺寸 {width}x{height}")

        fmt = metadata.get("format")
        if fmt:
            parts.append(f"格式 {fmt}")

        if ocr_text:
            char_count = len(ocr_text)
            line_count = len(ocr_text.split("\n"))
            parts.append(f"包含 {line_count} 行文字（共 {char_count} 字符）")
        else:
            parts.append("未检测到文字内容")

        return "，".join(parts) + "。" if parts else "图片信息不可用。"
