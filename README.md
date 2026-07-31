# 内部数据分析工具

企业内部数据分析平台，集成 LLM 智能问答、RAG 知识检索、ReAct 工具调用、多模态文件处理等能力，支持多轮对话、长短期记忆、权限管控和审计日志。

## 技术栈

### 后端
- **框架**: FastAPI + Uvicorn
- **数据库**: MySQL 8.0 (async via aiomysql) + SQLAlchemy 2.0
- **缓存**: Redis (会话、熔断、Celery broker)
- **向量库**: ChromaDB / Milvus (RAG 检索 + 记忆存储)
- **LLM**: 多模型网关 (OpenAI / Qwen / 文心 / Ollama / vLLM)
- **异步任务**: Celery
- **迁移**: Alembic
- **认证**: JWT + RBAC 权限体系

### 前端
- **框架**: Vue 3 + TypeScript
- **构建**: Vite
- **状态**: Pinia
- **UI**: Element Plus
- **图表**: ECharts

## 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── api/            # API 路由层
│   │   ├── core/           # 配置、数据库、Redis、错误码
│   │   ├── models/         # SQLAlchemy 数据模型
│   │   ├── schemas/        # Pydantic 请求/响应 Schema
│   │   ├── services/       # 业务逻辑层
│   │   │   ├── auth/       # 认证授权
│   │   │   ├── file_processor/  # 多模态文件处理
│   │   │   ├── llm/        # LLM 核心服务
│   │   │   │   ├── adapters/    # 模型适配器
│   │   │   │   ├── intent/      # 意图识别
│   │   │   │   ├── react/       # ReAct 推理引擎
│   │   │   │   └── tools/       # 工具系统
│   │   │   └── permission/      # 权限服务
│   │   └── main.py         # 应用入口
│   ├── alembic/            # 数据库迁移
│   ├── requirements.txt
│   └── .env.example        # 环境变量模板
├── frontend/
│   ├── src/
│   │   ├── api/            # API 调用封装
│   │   ├── views/          # 页面视图
│   │   ├── stores/         # Pinia 状态
│   │   ├── router/         # 路由配置
│   │   ├── layouts/        # 布局组件
│   │   └── utils/          # 工具函数
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8.0+
- Redis 7+
- ChromaDB (可选，用于 RAG/记忆)

### 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际的数据库密码、JWT密钥等

# 创建数据库
mysql -u root -p -e "CREATE DATABASE data_analysis CHARACTER SET utf8mb4;"

# 运行数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.main:app --reload --port 8000
```

### 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 开发模式启动
npm run dev
# 访问 http://localhost:3000
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

## 环境变量说明

详见 `backend/.env.example`，关键配置项：

| 变量 | 说明 | 必须修改 |
|------|------|----------|
| `DATABASE_URL` | MySQL 连接串 | 是 |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 是（生产环境） |
| `AES_SECRET_KEY` | AES 加密密钥 | 是（生产环境） |
| `REDIS_URL` | Redis 连接地址 | 视部署环境 |
| `VECTOR_DB_TYPE` | 向量库类型 (chromadb/milvus) | 视需求 |
| `EMBEDDING_MODEL_NAME` | Embedding 模型 | 视需求 |

## 核心功能

- **智能对话**: 多轮对话 + 上下文管理 + Token 预算分配
- **ReAct 推理**: 工具调用循环 + 自检 + 链路复用
- **记忆系统**: 短期(会话级) + 长期(向量检索) + 推理链路记忆
- **多模态**: 图片 OCR + Excel/CSV 数据分析 + 文件上下文注入
- **工具系统**: @tool 装饰器自注册 + 意图匹配 + 预执行
- **安全**: Prompt 注入检测 + 输出过滤 + 配额限流 + 审计日志
- **权限**: RBAC 角色权限 + 部门数据隔离

## 数据库迁移

```bash
# 生成新迁移
alembic revision --autogenerate -m "描述"

# 执行迁移
alembic upgrade head

# 回退一步
alembic downgrade -1
```

## 添加 LLM 模型

模型配置通过管理员 API 动态管理（非静态配置文件）：

```bash
curl -X POST http://localhost:8000/api/v1/llm/models \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "qwen-turbo",
    "model_name": "通义千问 Turbo",
    "provider": "qwen",
    "endpoint_url": "https://dashscope.aliyuncs.com/api/v1",
    "api_key": "sk-xxx",
    "context_window": 8192,
    "max_tokens": 2048,
    "priority": 0
  }'
```

## 添加自定义工具

在 `backend/app/services/llm/tools/` 下新建 `*_tools.py` 文件即可：

```python
from app.services.llm.tools.decorator import tool

@tool(
    category="custom",
    description="工具功能描述",
    triggers=["触发关键词"],
)
async def my_tool(param: str) -> dict:
    """
    Args:
        param: 参数描述
    """
    return {"result": "..."}
```

应用启动时自动发现注册，无需修改其他文件。
