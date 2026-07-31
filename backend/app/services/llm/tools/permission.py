"""
工具权限治理：控制哪些用户/角色可以调用哪些工具。

设计原则：
- 每个工具有安全等级（safe / standard / sensitive / dangerous）
- 不同角色有工具调用权限上限
- 敏感工具需要二次确认（返回 confirmation_required）
- 所有调用记录审计日志
- 支持工具黑名单/白名单

权限矩阵：
  safe       → 所有用户
  standard   → 登录用户
  sensitive   → 需 data_analyst 或 admin 角色
  dangerous  → 仅 admin + 二次确认
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class ToolSecurityLevel(IntEnum):
    """工具安全等级。"""
    SAFE = 0          # 无副作用，纯计算（calculator, mean, date_diff）
    STANDARD = 1      # 信息查询，无外部影响（city_distance, current_time）
    SENSITIVE = 2     # 读取敏感数据或外部调用（数据库查询、API调用）
    DANGEROUS = 3     # 写操作或高风险（文件写入、外部推送、数据修改）


@dataclass
class ToolPermissionRule:
    """单个工具的权限规则。"""
    tool_name: str
    security_level: ToolSecurityLevel = ToolSecurityLevel.SAFE
    allowed_roles: list[str] = field(default_factory=lambda: ["*"])  # * 表示所有角色
    denied_roles: list[str] = field(default_factory=list)
    require_confirmation: bool = False    # 是否需要二次确认
    rate_limit_per_hour: int = 0          # 每小时调用限制（0=无限制）
    max_param_size: int = 10000           # 参数最大字符数
    audit_level: str = "info"             # 审计日志级别: info / warning / critical


@dataclass
class PermissionCheckResult:
    """权限检查结果。"""
    allowed: bool
    reason: str = ""
    confirmation_required: bool = False
    confirmation_message: str = ""


# ============================================================
# 默认工具安全等级配置
# ============================================================

DEFAULT_TOOL_LEVELS: dict[str, ToolSecurityLevel] = {
    # 数学类 — SAFE
    "calculator": ToolSecurityLevel.SAFE,
    "sum": ToolSecurityLevel.SAFE,
    "mean": ToolSecurityLevel.SAFE,
    "median": ToolSecurityLevel.SAFE,
    "std_deviation": ToolSecurityLevel.SAFE,
    "percentile": ToolSecurityLevel.SAFE,
    "percentage_change": ToolSecurityLevel.SAFE,
    "compound_growth": ToolSecurityLevel.SAFE,
    "linear_regression": ToolSecurityLevel.SAFE,

    # 地理类 — SAFE
    "haversine_distance": ToolSecurityLevel.SAFE,
    "get_city_location": ToolSecurityLevel.SAFE,
    "city_distance": ToolSecurityLevel.SAFE,
    "coordinate_to_dms": ToolSecurityLevel.SAFE,
    "bearing": ToolSecurityLevel.SAFE,
    "midpoint": ToolSecurityLevel.SAFE,

    # 时间类 — SAFE
    "current_time": ToolSecurityLevel.SAFE,
    "date_difference": ToolSecurityLevel.SAFE,
    "add_days": ToolSecurityLevel.SAFE,
    "is_workday": ToolSecurityLevel.SAFE,
    "workdays_between": ToolSecurityLevel.SAFE,
    "timestamp_convert": ToolSecurityLevel.SAFE,
    "month_calendar": ToolSecurityLevel.SAFE,

    # 文本类 — SAFE/STANDARD
    "word_count": ToolSecurityLevel.SAFE,
    "json_format": ToolSecurityLevel.SAFE,
    "url_encode": ToolSecurityLevel.SAFE,
    "url_decode": ToolSecurityLevel.SAFE,
    "hash_text": ToolSecurityLevel.SAFE,
    "unit_convert": ToolSecurityLevel.SAFE,
}

# 角色可访问的最高安全等级
ROLE_MAX_LEVEL: dict[str, ToolSecurityLevel] = {
    "admin": ToolSecurityLevel.DANGEROUS,
    "data_analyst": ToolSecurityLevel.SENSITIVE,
    "user": ToolSecurityLevel.STANDARD,
    "guest": ToolSecurityLevel.SAFE,
}


class ToolPermissionManager:
    """
    工具权限管理器。

    职责：
    1. 检查用户是否有权调用某工具
    2. 判断是否需要二次确认
    3. 检查调用频率限制
    4. 参数大小检查
    """

    def __init__(self):
        self._rules: dict[str, ToolPermissionRule] = {}
        self._tool_blacklist: set[str] = set()  # 全局禁用的工具
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        """初始化默认权限规则。"""
        for tool_name, level in DEFAULT_TOOL_LEVELS.items():
            self._rules[tool_name] = ToolPermissionRule(
                tool_name=tool_name,
                security_level=level,
                require_confirmation=(level >= ToolSecurityLevel.DANGEROUS),
            )

    def check_permission(
        self,
        tool_name: str,
        user_roles: list[str],
        params: dict | None = None,
    ) -> PermissionCheckResult:
        """
        检查用户是否有权调用指定工具。

        Args:
            tool_name: 工具名称
            user_roles: 用户角色列表
            params: 工具参数（用于参数安全检查）

        Returns:
            PermissionCheckResult
        """
        # 1. 全局黑名单检查
        if tool_name in self._tool_blacklist:
            return PermissionCheckResult(
                allowed=False,
                reason=f"工具 {tool_name} 已被全局禁用",
            )

        # 2. 获取工具规则
        rule = self._rules.get(tool_name)
        if not rule:
            # 未注册的工具默认为 STANDARD
            rule = ToolPermissionRule(
                tool_name=tool_name,
                security_level=ToolSecurityLevel.STANDARD,
            )

        # 3. 角色权限检查
        if rule.denied_roles:
            for role in user_roles:
                if role in rule.denied_roles:
                    return PermissionCheckResult(
                        allowed=False,
                        reason=f"角色 {role} 被禁止调用工具 {tool_name}",
                    )

        # 4. 安全等级检查
        user_max_level = self._get_user_max_level(user_roles)
        if rule.security_level > user_max_level:
            return PermissionCheckResult(
                allowed=False,
                reason=f"工具 {tool_name} 安全等级为 {rule.security_level.name}，"
                       f"您的最高权限为 {user_max_level.name}",
            )

        # 5. 允许角色检查（如果配置了白名单）
        if "*" not in rule.allowed_roles:
            has_allowed_role = any(r in rule.allowed_roles for r in user_roles)
            if not has_allowed_role:
                return PermissionCheckResult(
                    allowed=False,
                    reason=f"工具 {tool_name} 仅允许角色 {rule.allowed_roles} 调用",
                )

        # 6. 参数大小检查
        if params:
            param_str = str(params)
            if len(param_str) > rule.max_param_size:
                return PermissionCheckResult(
                    allowed=False,
                    reason=f"参数过大: {len(param_str)} 字符 > {rule.max_param_size} 上限",
                )

        # 7. 二次确认检查
        if rule.require_confirmation:
            return PermissionCheckResult(
                allowed=True,
                confirmation_required=True,
                confirmation_message=f"工具 {tool_name} 为高风险操作，确认执行？",
            )

        return PermissionCheckResult(allowed=True)

    def set_tool_level(self, tool_name: str, level: ToolSecurityLevel) -> None:
        """动态设置工具安全等级。"""
        if tool_name in self._rules:
            self._rules[tool_name].security_level = level
        else:
            self._rules[tool_name] = ToolPermissionRule(
                tool_name=tool_name,
                security_level=level,
            )

    def blacklist_tool(self, tool_name: str) -> None:
        """将工具加入全局黑名单。"""
        self._tool_blacklist.add(tool_name)
        logger.warning(f"[Permission] 工具 {tool_name} 已加入黑名单")

    def whitelist_tool(self, tool_name: str) -> None:
        """将工具移出黑名单。"""
        self._tool_blacklist.discard(tool_name)

    def get_tool_rule(self, tool_name: str) -> ToolPermissionRule | None:
        """获取工具的权限规则。"""
        return self._rules.get(tool_name)

    def list_rules(self) -> list[dict]:
        """列出所有权限规则。"""
        return [
            {
                "tool_name": r.tool_name,
                "security_level": r.security_level.name,
                "allowed_roles": r.allowed_roles,
                "require_confirmation": r.require_confirmation,
                "rate_limit_per_hour": r.rate_limit_per_hour,
            }
            for r in self._rules.values()
        ]

    def _get_user_max_level(self, roles: list[str]) -> ToolSecurityLevel:
        """获取用户角色对应的最高安全等级。"""
        max_level = ToolSecurityLevel.SAFE
        for role in roles:
            level = ROLE_MAX_LEVEL.get(role, ToolSecurityLevel.SAFE)
            if level > max_level:
                max_level = level
        return max_level


# 全局单例
tool_permission_manager = ToolPermissionManager()
