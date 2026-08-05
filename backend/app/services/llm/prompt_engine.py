"""Prompt template engine."""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import PromptTemplate, PromptTemplateVersion


class PromptTemplateEngine:
    """Manage prompt templates, versions, rendering, and matching."""

    BUILTIN_VARIABLES = {
        "user_query": "Original user query",
        "context_docs": "Documents retrieved by RAG",
        "memory_context": "Relevant long-term memory context",
        "conversation_history": "Conversation history",
        "tools_prompt": "Available tool instructions",
        "user_role": "Current user role information",
        "current_time": "Current time",
    }

    DEFAULT_TEMPLATE = """You are an internal enterprise knowledge assistant.

{% if tools_prompt %}
{{tools_prompt}}
{% endif %}

{% if memory_context %}
Relevant user memory:
{{memory_context}}
{% endif %}

Retrieved documents:
{{context_docs}}

{% if conversation_history %}
Conversation history:
{{conversation_history}}
{% endif %}

User question:
{{user_query}}

Please provide a structured answer with:
1. Summary
2. Key points
3. Details
4. References when available

If the retrieved documents do not contain enough information, say so clearly and suggest how to refine the question.
"""

    CATEGORY_KEYWORDS = {
        "tech_doc": ["tech", "code", "architecture", "api", "deploy", "config", "bug", "error"],
        "data_analysis": ["data", "report", "metric", "analysis", "trend", "statistics"],
        "process_guide": ["process", "step", "how", "guide", "approval", "workflow"],
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
        self.db.add(
            PromptTemplateVersion(
                template_id=template.id,
                version=1,
                template_content=template_content,
                variables=variables,
                changed_by=created_by,
                change_description="Initial version",
            )
        )
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
        template = await self._get_template(template_id)
        if not template:
            return None

        if name is not None:
            template.name = name
        if is_active is not None:
            template.is_active = is_active
        if variables is not None:
            template.variables = variables

        if template_content is not None:
            template.template_content = template_content
            template.version += 1
            self.db.add(
                PromptTemplateVersion(
                    template_id=template.id,
                    version=template.version,
                    template_content=template.template_content,
                    variables=template.variables,
                    changed_by=changed_by,
                    change_description=change_description,
                )
            )

        await self.db.flush()
        return template

    async def rollback_version(self, template_id: int, target_version: int) -> PromptTemplate | None:
        template = await self._get_template(template_id)
        if not template:
            return None

        version_result = await self.db.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template_id,
                PromptTemplateVersion.version == target_version,
            )
        )
        version = version_result.scalar_one_or_none()
        if not version:
            return None

        template.version += 1
        template.template_content = version.template_content
        template.variables = version.variables
        self.db.add(
            PromptTemplateVersion(
                template_id=template.id,
                version=template.version,
                template_content=template.template_content,
                variables=template.variables,
                changed_by=0,
                change_description=f"Rollback to version {target_version}",
            )
        )
        await self.db.flush()
        return template

    async def render(self, template_id: int | None, variables: dict[str, str]) -> str:
        if template_id:
            template = await self._get_template(template_id, active_only=True)
            if template:
                return self._substitute_variables(template.template_content, variables)
        return self._substitute_variables(self.DEFAULT_TEMPLATE, variables)

    async def match_template(self, question: str, category: str | None = None) -> int | None:
        target_category = category or self._detect_category(question)
        if target_category:
            result = await self.db.execute(
                select(PromptTemplate)
                .where(PromptTemplate.category == target_category, PromptTemplate.is_active == True)
                .order_by(PromptTemplate.is_default.desc())
                .limit(1)
            )
            template = result.scalar_one_or_none()
            if template:
                return template.id

        result = await self.db.execute(
            select(PromptTemplate)
            .where(PromptTemplate.is_default == True, PromptTemplate.is_active == True)
            .limit(1)
        )
        template = result.scalar_one_or_none()
        return template.id if template else None

    async def get_template_versions(self, template_id: int) -> list[PromptTemplateVersion]:
        result = await self.db.execute(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == template_id)
            .order_by(PromptTemplateVersion.version.desc())
        )
        return list(result.scalars().all())

    async def preview(self, template_id: int, variables: dict[str, str]) -> tuple[str, int]:
        rendered = await self.render(template_id, variables)
        token_count = max(1, len(rendered) // 4)
        return rendered, token_count

    async def get_system_prompt(self, template_id: int | None = None) -> str:
        if template_id:
            template = await self._get_template(template_id, active_only=True)
            if template:
                return self._extract_system_instruction(template.template_content)
        return self._extract_system_instruction(self.DEFAULT_TEMPLATE)

    async def _get_template(self, template_id: int, active_only: bool = False) -> PromptTemplate | None:
        conditions = [PromptTemplate.id == template_id]
        if active_only:
            conditions.append(PromptTemplate.is_active == True)
        result = await self.db.execute(select(PromptTemplate).where(*conditions))
        return result.scalar_one_or_none()

    def _extract_system_instruction(self, template: str) -> str:
        result = re.sub(r"{% if \w+ %}.*?{% endif %}", "", template, flags=re.DOTALL)
        result = re.sub(r"\{\{\w+\}\}", "", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    def _substitute_variables(self, template: str, variables: dict[str, str]) -> str:
        result = self._apply_condition_blocks(template, variables)
        merged = {"current_time": datetime.now(timezone.utc).isoformat(), **variables}
        for key, value in merged.items():
            result = result.replace("{{" + key + "}}", str(value or ""))
        result = re.sub(r"\{\{\w+\}\}", "", result)
        return result.strip()

    def _apply_condition_blocks(self, template: str, variables: dict[str, str]) -> str:
        def replace_block(match: re.Match) -> str:
            key = match.group(1)
            content = match.group(2)
            return content if variables.get(key) else ""

        return re.sub(r"{% if (\w+) %}(.*?){% endif %}", replace_block, template, flags=re.DOTALL)

    def _detect_category(self, question: str) -> str | None:
        lowered = question.lower()
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return category
        return None
