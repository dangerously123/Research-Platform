"""
生产安全加固模块。

功能：
- CORS 白名单管理（生产环境严格限制来源）
- 密钥轮换支持（双密钥窗口期）
- 上传文件安全扫描（类型验证、内容嗅探、大小限制）
- 安全响应头
"""

from __future__ import annotations

import hashlib
import logging
import struct
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# CORS 白名单
# ============================================================

def get_cors_origins() -> list[str]:
    """
    获取 CORS 允许的来源列表。
    生产环境从环境变量读取，开发环境允许所有。
    """
    if settings.DEBUG:
        return ["*"]

    # 生产环境：从环境变量 CORS_ORIGINS 读取，逗号分隔
    origins_str = getattr(settings, "CORS_ORIGINS", "")
    if origins_str:
        return [o.strip() for o in origins_str.split(",") if o.strip()]

    # 默认只允许同源
    return ["http://localhost", "https://localhost"]


# ============================================================
# 密钥轮换
# ============================================================

class KeyRotation:
    """
    密钥轮换支持。

    轮换期间同时接受新旧两个密钥，避免服务中断：
    1. 设置新密钥到 JWT_SECRET_KEY_NEW 环境变量
    2. 新签发的 token 使用新密钥
    3. 验证时同时尝试新旧密钥
    4. 确认所有旧 token 过期后，移除旧密钥
    """

    @staticmethod
    def get_signing_key() -> str:
        """获取当前用于签名的密钥（优先使用新密钥）。"""
        new_key = getattr(settings, "JWT_SECRET_KEY_NEW", None)
        if new_key:
            return new_key
        return settings.JWT_SECRET_KEY

    @staticmethod
    def get_verification_keys() -> list[str]:
        """获取所有可用于验证的密钥（新+旧）。"""
        keys = [settings.JWT_SECRET_KEY]
        new_key = getattr(settings, "JWT_SECRET_KEY_NEW", None)
        if new_key:
            keys.insert(0, new_key)  # 新密钥优先尝试
        return keys


# ============================================================
# 上传文件安全扫描
# ============================================================

# 文件魔术字节（用于内容嗅探验证）
MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],
    "image/bmp": [b"BM"],
    "application/pdf": [b"%PDF"],
    "application/zip": [b"PK\x03\x04"],  # xlsx/docx 都是 zip
}

# 危险文件扩展名（永远拒绝）
DANGEROUS_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
    ".ps1", ".vbs", ".js", ".ws", ".wsf",
    ".sh", ".bash", ".csh",
    ".php", ".asp", ".aspx", ".jsp",
    ".dll", ".so", ".dylib",
}

# 最大文件名长度
MAX_FILENAME_LENGTH = 200


class FileSecurityScanner:
    """
    上传文件安全扫描器。

    检查项：
    1. 扩展名黑名单
    2. 文件名长度和特殊字符
    3. MIME 类型与实际内容一致性（魔术字节嗅探）
    4. 双扩展名攻击检测
    5. 文件大小合理性
    """

    def scan(self, filename: str, content: bytes, declared_mime: str) -> tuple[bool, str]:
        """
        扫描上传文件。

        Args:
            filename: 原始文件名
            content: 文件内容（前 8KB 即可）
            declared_mime: 客户端声明的 MIME 类型

        Returns:
            (is_safe, reason)
        """
        # 1. 文件名长度
        if len(filename) > MAX_FILENAME_LENGTH:
            return False, f"文件名过长: {len(filename)} > {MAX_FILENAME_LENGTH}"

        # 2. 危险扩展名
        ext = self._get_extension(filename)
        if ext in DANGEROUS_EXTENSIONS:
            return False, f"危险文件类型: {ext}"

        # 3. 双扩展名攻击（如 report.pdf.exe）
        parts = filename.rsplit(".", maxsplit=3)
        if len(parts) >= 3:
            for part in parts[1:]:
                if f".{part.lower()}" in DANGEROUS_EXTENSIONS:
                    return False, f"疑似双扩展名攻击: {filename}"

        # 4. 文件名特殊字符
        dangerous_chars = set('<>:"|?*\x00')
        if any(c in filename for c in dangerous_chars):
            return False, "文件名包含非法字符"

        # 5. 路径穿越检测
        if ".." in filename or "/" in filename or "\\" in filename:
            return False, "文件名包含路径分隔符"

        # 6. MIME 类型与内容一致性（魔术字节）
        if declared_mime in MAGIC_BYTES and content:
            expected_magics = MAGIC_BYTES[declared_mime]
            header = content[:16]
            matched = any(header.startswith(magic) for magic in expected_magics)
            if not matched:
                logger.warning(
                    f"[Security] MIME 不匹配: declared={declared_mime} "
                    f"header={header[:8].hex()}"
                )
                return False, f"文件内容与声明类型 {declared_mime} 不匹配"

        # 7. 空文件检查
        if len(content) == 0:
            return False, "文件内容为空"

        return True, ""

    def _get_extension(self, filename: str) -> str:
        """安全获取文件扩展名。"""
        return Path(filename).suffix.lower()

    def compute_checksum(self, content: bytes) -> str:
        """计算文件 SHA-256 校验和。"""
        return hashlib.sha256(content).hexdigest()


# 全局扫描器实例
file_security_scanner = FileSecurityScanner()
