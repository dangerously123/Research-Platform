"""应用配置管理，基于 Pydantic Settings。"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """全局配置，通过环境变量或 .env 文件加载。"""

    # 应用基础配置
    APP_NAME: str = "内部数据分析工具"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # 数据库配置
    DATABASE_URL: str = Field(
        default="mysql+aiomysql://root:password@localhost:3306/data_analysis",
        description="MySQL 异步连接 URL",
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis 配置
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接 URL",
    )
    REDIS_MAX_CONNECTIONS: int = 50
    AUTO_START_LOCAL_REDIS: bool = True
    REDIS_SERVER_PATH: str = ""

    # JWT 认证配置
    JWT_SECRET_KEY: str = Field(
        default="change-me-in-production",
        description="JWT 签名密钥",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 会话配置
    SESSION_TIMEOUT_MINUTES: int = 30
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    # 加密配置
    AES_SECRET_KEY: str = Field(
        default="0" * 64,  # 32 bytes hex
        description="AES-256 加密密钥（64 位十六进制字符串）",
    )

    # LLM 配置
    LLM_DEFAULT_MAX_TOKENS: int = 4096
    LLM_DEFAULT_TEMPERATURE: float = 0.7
    LLM_RATE_LIMIT_PER_HOUR: int = 100
    LLM_CONTEXT_MAX_TURNS: int = 20
    LLM_CONTEXT_TOKEN_RATIO: float = 0.6
    LLM_CONVERSATION_ARCHIVE_HOURS: int = 24

    # ReAct Agent 配置
    REACT_MAX_ITERATIONS: int = 5           # 最大推理循环轮数
    REACT_QUALITY_THRESHOLD: float = 0.8    # 自检质量阈值
    REACT_ENABLE_SELF_CHECK: bool = True    # 是否启用自检
    REACT_TIMEOUT_SECONDS: int = 60         # 总超时时间（秒）

    # 向量数据库配置
    VECTOR_DB_TYPE: str = Field(
        default="chromadb",
        description="向量数据库类型: chromadb 或 milvus",
    )
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8000
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530

    # Embedding 模型配置
    EMBEDDING_MODEL_NAME: str = "shibing624/text2vec-base-chinese"
    EMBEDDING_DIMENSION: int = 768

    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": True}


settings = Settings()
