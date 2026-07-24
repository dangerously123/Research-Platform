"""Prompt 模板引擎：模板管理、变量替换、版本控制、场景匹配。"""

import re
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import PromptTemplate, PromptTemplateVersion


class PromptTemplateEngine:
    """
    Prompt 模板引擎。
    - 模板 CRUD 和版本管理
    - 变量替换（{{variable_name}}）
    - 按场景自动匹配模板
    """

    # 内置变量名称
    BUILTIN_VARIABLES = {
        "user_query": "用户的原始问题",
        "context_docs": "RAG 检索到的相关文档内容",
        "memory_context": "用户长期记忆中的相关历史问答",
        "conversation_history": "对话历史上下文",
        "tools_prompt": "可用工具描述（由工具注册中心生成）",
        "user_role": "当前用户的角色信息",
        "current_time": "当前时间戳",
    }

    # 默认模板内容
    DEFAULT_TEMPLATE = """你是一个企业内部知识助手。请基于以下检索到的文档内容回答用户的问题。

{% if tools_prompt %}
{{tools_prompt}}
{% endif %}

{% if memory_context %}
用户的历史相关问答（仅供参考，优先使用最新检索文档）：
{{memory_context}}
{% endif %}

检索文档：
{{context_docs}}

{% if conversation_history %}
对话历史：
{{conversation_history}}
{% endif %}

用户问题：{{user_query}}

请提供结构化回答，包含：
1. 摘要（一句话概括）
2. 关键要点（列表形式）
3. 详细说明
4. 参考来源（标注引用的文档）

如果检索文档中没有相关信息，请明确说明无法回答并建议用户调整问题。"""

    # 场景关键词映射
    CATEGORY_KEYWORDS = {
        "tech_doc": ["技术", "代码", "架构", "接口", "API", "部署", "配置", "Bug", "报错"],
        "data_analysis": ["数据", "报表", "统计", "分析", "指标", "趋势", "环比", "同比"],
        "process_guide": ["流程", "步骤", "如何", "怎么", "操作", "审批", "申请"],
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_template(
        self,
        name: str,
        category: str,
        template_content: str,
        variables: list[dict] | None,
        created_by: int,
        is_default: bool = False,
    ) -> PromptTemplate:
        """创建新模板。"""
        template = PromptTemplate(
            name=name,
            category=category,
            template_content=template_content,
            variables=variables,
            is_default=is_default,
            created_by=created_by,
        )
        self.db.add(template)
        await self.db.flush()

        # 保存初始版本
        version = PromptTemplateVersion(
            template_id=template.id,
            version=1,
            template_content=template_content,
            variables=variables,
            changed_by=created_by,
            change_description="初始创建",
        )
        self.db.add(version)
        await self.db.flush()

        return template

    async def update_template(
        self,
        template_id: int,
        changed_by: int,
        name: str | None = None,
        template_content: str | None = None,
        variables: list[dict] | None = None,
        is_active: bool | None = None,
        change_description: str = "",
    ) -> PromptTemplate | None:
        """更新模板并保存版本。"""
        stmt = select(PromptTemplate).where(PromptTemplate.id == template_id)
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()
        if not template:
            return None

        if name is not None:
            template.name = name
        if is_active is not None:
            template.is_active = is_active

        if template_content is not None:
            template.template_content = template_content
            template.version += 1

            # 保存版本历史
            version = PromptTemplateVersion(
                template_id=template.id,
                version=template.version,
                template_content=template_content,
                variables=variables or template.variables,
                changed_by=changed_by,
                change_description=change_description,
            )
            self.db.add(version)

        if variables is not None:
            template.variables = variables

        await self.db.flush()
        return template

    async def rollback_version(self, template_id: int, target_version: int) -> PromptTemplate | None:
        """回退模板到指定版本。"""
        # 获取目标版本
        stmt = select(PromptTemplateVersion).where(
            PromptTemplateVersion.template_id == template_id,
            PromptTemplateVersion.version == target_version,
        )
        result = await self.db.execute(stmt)
        version_record = result.scalar_one_or_none()
        if not version_record:
            return None

        # 更新当前模板
        stmt2 = select(PromptTemplate).where(PromptTemplate.id == template_id)
        result2 = await self.db.execute(stmt2)
        template = result2.scalar_one_or_none()
        if not template:
            return None

        template.template_content = version_record.template_content
        template.variables = version_record.variables
        template.version = version_record.version
        await self.db.flush()

        return template

    async def render(
        self, template_id: int | None, variables: dict[str, str]
    ) -> str:
        """
        渲染 Prompt 模板。
        如果 template_id 为 None，使用默认模板。
        """
        if template_id:
            stmt = select(PromptTemplate).where(
                PromptTemplate.id == template_id,
                PromptTemplate.is_active == True,
            )
            result = await self.db.execute(stmt)
            template = result.scalar_one_or_none()
            if template:
                return self._substitute_variables(template.template_content, variables)

        # 使用默认模板
        return self._substitute_variables(self.DEFAULT_TEMPLATE, variables)

    async def match_template(self, question: str, category: str | None = None) -> int | None:
        """
        自动匹配最合适的 Prompt 模板。
        1. 如果指定了 category，选该分类活跃模板
        2. 否则基于关键词检测分类
        3. 回退到默认模板（返回 None）
        """
        target_category = category or self._detect_category(question)

        if target_category:
            stmt = (
                select(PromptTemplate)
                .where(
                    PromptTemplate.category == target_category,
                    PromptTemplate.is_active == True,
                )
                .order_by(PromptTemplate.is_default.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            template = result.scalar_one_or_none()
            if template:
                return template.id

        # 回退到默认
        stmt = select(PromptTemplate).where(
            PromptTemplate.is_default == True,
            PromptTemplate.is_active == True,
        ).limit(1)
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()
        return template.id if template else None

    async def get_template_versions(self, template_id: int) -> list[PromptTemplateVersion]:
        """获取模板版本历史。"""
        stmt = (
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == template_id)
            .order_by(PromptTemplateVersion.version.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def preview(self, template_id: int, variables: dict[str, str]) -> tuple[str, int]:
        """预览渲染结果，返回 (rendered_content, token_count)。"""
        rendered = await self.render(template_id, variables)
        token_count = len(rendered) // 2  # 粗略估算
        return rendered, token_count

    def _substitute_variables(self, template: str, variables: dict[str, str]) -> str:
        """替换模板中的变量占位符 {{variable_name}}。"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))

        # 处理简单条件块 {% if variable %}...{% endif %}
        for key, value in variables.items():
            if value:
                result = re.sub(
                    rf"{{% if {key} %}}(.*?){{% endif %}}",
                    r"\1",
                    result,
                    flags=re.DOTALL,
                )
            else:
                result = re.sub(
                    rf"{{% if {key} %}}.*?{{% endif %}}",
                    "",
                    result,
                    flags=re.DOTALL,
                )

        # 清理未被替换的条件块
        result = re.sub(r"{{% if \w+ %}}.*?{{% endif %}}", "", result, flags=re.DOTALL)

        return result.strip()

    def _detect_category(self, question: str) -> str | None:
        """基于关键词检测问题类别。"""
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in question for kw in keywords):
                return category
        return "general"
