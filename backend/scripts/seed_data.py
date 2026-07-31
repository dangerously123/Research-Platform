#!/usr/bin/env python3
"""
初始化种子数据脚本。

创建：
- 默认角色（admin / data_analyst / user）
- 默认部门
- 管理员用户
- 默认 Prompt 模板
- Token 配额示例

使用方式:
  python scripts/seed_data.py
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.database import async_session_factory, engine, Base
from app.models.user import User, Role, Permission, Department, UserRole
from app.models.llm import PromptTemplate, TokenQuota


async def seed():
    """执行种子数据初始化。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        try:
            # === 部门 ===
            dept = await _ensure(db, Department, name="总部", path="/总部")
            print(f"[Seed] 部门: {dept.name}")

            # === 角色 ===
            admin_role = await _ensure(
                db, Role, name="admin", description="系统管理员，拥有全部权限"
            )
            analyst_role = await _ensure(
                db, Role, name="data_analyst", description="数据分析师"
            )
            user_role = await _ensure(
                db, Role, name="user", description="普通用户"
            )
            print(f"[Seed] 角色: admin, data_analyst, user")

            # === 管理员用户 ===
            from app.services.auth.password import hash_password
            admin_user = await _ensure_user(
                db, username="admin",
                password_hash=hash_password("admin123"),
                department_id=dept.id,
            )
            # 分配 admin 角色
            await _ensure_user_role(db, admin_user.id, admin_role.id)
            print(f"[Seed] 管理员: admin / admin123")

            # === 默认 Prompt 模板 ===
            await _ensure_template(db, name="通用问答", category="general")
            await _ensure_template(db, name="数据分析", category="data_analysis")
            await _ensure_template(db, name="技术文档", category="tech_doc")
            print("[Seed] 模板: 通用问答, 数据分析, 技术文档")

            # === Token 配额 ===
            await _ensure_quota(db, target_type="user", target_id=admin_user.id,
                                monthly_token_limit=10_000_000)
            print("[Seed] 配额: admin 每月 1000 万 token")

            await db.commit()
            print("\n[Seed] 种子数据初始化完成!")

        except Exception as e:
            await db.rollback()
            print(f"[Seed] 失败: {e}", file=sys.stderr)
            sys.exit(1)


async def _ensure(db, model_class, **kwargs):
    """确保记录存在（不重复创建）。"""
    name = kwargs.get("name", "")
    stmt = select(model_class).where(model_class.name == name)
    result = await db.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = model_class(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def _ensure_user(db, username: str, password_hash: str, department_id: int):
    """确保用户存在。"""
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user
    user = User(username=username, password_hash=password_hash, department_id=department_id)
    db.add(user)
    await db.flush()
    return user


async def _ensure_user_role(db, user_id: int, role_id: int):
    """确保用户角色关联存在。"""
    stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        return
    db.add(UserRole(user_id=user_id, role_id=role_id, assigned_by=user_id))
    await db.flush()


async def _ensure_template(db, name: str, category: str):
    """确保模板存在。"""
    stmt = select(PromptTemplate).where(PromptTemplate.name == name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        return
    db.add(PromptTemplate(
        name=name, category=category,
        template_content="{{user_query}}", created_by=1, is_default=(category == "general"),
    ))
    await db.flush()


async def _ensure_quota(db, target_type: str, target_id: int, monthly_token_limit: int):
    """确保配额存在。"""
    stmt = select(TokenQuota).where(
        TokenQuota.target_type == target_type, TokenQuota.target_id == target_id
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        return
    db.add(TokenQuota(
        target_type=target_type, target_id=target_id,
        monthly_token_limit=monthly_token_limit,
    ))
    await db.flush()


if __name__ == "__main__":
    asyncio.run(seed())
