"""API 基础健康测试。"""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """测试基础 API 可达性。"""

    @pytest.mark.asyncio
    async def test_openapi_docs_accessible(self, client: AsyncClient):
        """OpenAPI 文档可访问。"""
        response = await client.get("/docs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json(self, client: AsyncClient):
        """OpenAPI JSON schema 可获取。"""
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "info" in data

    @pytest.mark.asyncio
    async def test_unknown_route_404(self, client: AsyncClient):
        """不存在的路由返回 404。"""
        response = await client.get("/api/v1/nonexistent")
        assert response.status_code == 404


class TestAuthEndpoints:
    """测试认证接口基本响应。"""

    @pytest.mark.asyncio
    async def test_login_missing_body(self, client: AsyncClient):
        """登录缺少请求体返回 422。"""
        response = await client.post("/api/v1/auth/login")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_protected_endpoint_no_token(self, client: AsyncClient):
        """未携带 Token 访问受保护端点返回 401/403。"""
        response = await client.get("/api/v1/llm/models")
        assert response.status_code in (401, 403)


class TestToolsEndpoint:
    """测试工具 API。"""

    @pytest.mark.asyncio
    async def test_list_tools_requires_auth(self, client: AsyncClient):
        """工具列表需要认证。"""
        response = await client.get("/api/v1/tools")
        assert response.status_code in (401, 403)
