"""Production security helpers."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_cors_origins() -> list[str]:
    """Return configured CORS origins."""
    if settings.DEBUG:
        return ["*"]

    origins_str = getattr(settings, "CORS_ORIGINS", "")
    if origins_str:
        return [origin.strip() for origin in origins_str.split(",") if origin.strip()]

    return ["http://localhost", "https://localhost"]


class KeyRotation:
    """JWT key-rotation helper."""

    @staticmethod
    def get_signing_key() -> str:
        new_key = getattr(settings, "JWT_SECRET_KEY_NEW", None)
        return new_key or settings.JWT_SECRET_KEY

    @staticmethod
    def get_verification_keys() -> list[str]:
        keys = [settings.JWT_SECRET_KEY]
        new_key = getattr(settings, "JWT_SECRET_KEY_NEW", None)
        if new_key:
            keys.insert(0, new_key)
        return keys


MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],
    "image/bmp": [b"BM"],
    "application/pdf": [b"%PDF"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [b"PK\x03\x04"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [b"PK\x03\x04"],
    "application/vnd.ms-excel": [b"\xd0\xcf\x11\xe0", b"PK\x03\x04"],
    "application/msword": [b"\xd0\xcf\x11\xe0", b"PK\x03\x04"],
}

DANGEROUS_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
    ".ps1", ".vbs", ".js", ".ws", ".wsf",
    ".sh", ".bash", ".csh",
    ".php", ".asp", ".aspx", ".jsp",
    ".dll", ".so", ".dylib",
}

MAX_FILENAME_LENGTH = 200


class FileSecurityScanner:
    """Lightweight upload safety scanner."""

    def scan(self, filename: str, content: bytes, declared_mime: str) -> tuple[bool, str]:
        if not filename or filename in {".", ".."}:
            return False, "Invalid filename"
        if len(filename) > MAX_FILENAME_LENGTH:
            return False, f"Filename too long: {len(filename)} > {MAX_FILENAME_LENGTH}"

        ext = self._get_extension(filename)
        if ext in DANGEROUS_EXTENSIONS:
            return False, f"Dangerous file extension: {ext}"

        parts = filename.rsplit(".", maxsplit=3)
        if len(parts) >= 3:
            for part in parts[1:]:
                if f".{part.lower()}" in DANGEROUS_EXTENSIONS:
                    return False, f"Suspicious double extension: {filename}"

        dangerous_chars = set('<>:"|?*\x00')
        if any(char in filename for char in dangerous_chars):
            return False, "Filename contains illegal characters"
        if ".." in filename or "/" in filename or "\\" in filename:
            return False, "Filename contains path separators"
        if not content:
            return False, "File is empty"

        if declared_mime in MAGIC_BYTES:
            header = content[:16]
            if not any(header.startswith(magic) for magic in MAGIC_BYTES[declared_mime]):
                logger.warning(
                    "[Security] MIME/header mismatch: declared=%s header=%s",
                    declared_mime,
                    header[:8].hex(),
                )
                return False, f"File content does not match declared type: {declared_mime}"

        return True, ""

    def _get_extension(self, filename: str) -> str:
        return Path(filename).suffix.lower()

    def compute_checksum(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


file_security_scanner = FileSecurityScanner()
