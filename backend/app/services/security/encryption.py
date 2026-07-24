"""AES-256-GCM 数据加密模块。"""

import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import String, TypeDecorator

from app.core.config import settings


class DataEncryptor:
    """
    AES-256-GCM 加密器。
    用于敏感数据字段的加密存储和解密读取。
    """

    def __init__(self, key: bytes | None = None):
        """
        Args:
            key: 32 字节 AES-256 密钥。默认从配置中读取。
        """
        if key is None:
            key = bytes.fromhex(settings.AES_SECRET_KEY)
        assert len(key) == 32, "AES-256 密钥必须为 32 字节"
        self.key = key

    def encrypt(self, plaintext: str) -> str:
        """
        加密明文，返回 Base64 编码的密文（含 IV + Tag）。

        格式: base64(iv[16] + tag[16] + ciphertext[...])
        """
        if not plaintext:
            return ""

        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext.encode("utf-8")) + encryptor.finalize()

        # 拼接: iv + tag + ciphertext
        encrypted_data = iv + encryptor.tag + ciphertext
        return base64.b64encode(encrypted_data).decode("utf-8")

    def decrypt(self, encrypted: str) -> str:
        """
        解密 Base64 编码的密文。
        """
        if not encrypted:
            return ""

        data = base64.b64decode(encrypted)
        iv = data[:16]
        tag = data[16:32]
        ciphertext = data[32:]

        cipher = Cipher(algorithms.AES(self.key), modes.GCM(iv, tag))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.decode("utf-8")


# 全局加密器实例
_encryptor: DataEncryptor | None = None


def get_encryptor() -> DataEncryptor:
    """获取全局加密器实例（懒加载）。"""
    global _encryptor
    if _encryptor is None:
        _encryptor = DataEncryptor()
    return _encryptor


class EncryptedField(TypeDecorator):
    """
    SQLAlchemy 自定义类型：透明加解密字段。

    使用方式：
        sensitive_data: Mapped[str] = mapped_column(EncryptedField(length=512))
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.impl = String(length)

    def process_bind_param(self, value, dialect):
        """写入数据库前加密。"""
        if value is None:
            return None
        encryptor = get_encryptor()
        return encryptor.encrypt(value)

    def process_result_value(self, value, dialect):
        """从数据库读取后解密。"""
        if value is None:
            return None
        encryptor = get_encryptor()
        return encryptor.decrypt(value)
