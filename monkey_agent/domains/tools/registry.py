from __future__ import annotations

from typing import Any

from .protocol import Permission, Tool, ToolExecutionResult, ToolRisk, validate_input


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self.tools = tools or []

    def match(self, question: str, context: dict[str, Any]) -> list[Tool]:
        preferred_tool_id = context.get("preferred_tool_id") or context.get("only_tool_id")
        if preferred_tool_id:
            return [
                tool
                for tool in self.tools
                if tool.id == preferred_tool_id and tool.can_handle(question, context)
            ]
        return [tool for tool in self.tools if tool.can_handle(question, context)]

    def add(self, tool: Tool) -> None:
        self.tools = [item for item in self.tools if item.id != tool.id]
        self.tools.append(tool)

    def explore(self, question: str, context: dict[str, Any]) -> ToolExecutionResult | None:
        for tool in self.match(question, context):
            issues = validate_input(tool, context)
            permission = getattr(tool, "permission", Permission.AUTO)
            risk = getattr(tool, "risk", None)
            read_only = getattr(tool, "read_only", True)
            learn_policy = getattr(tool, "learn_policy", None)
            if issues and permission == Permission.CONFIRM:
                return tool.execute(question, context)
            if permission == Permission.CONFIRM and not _confirmed(tool.id, context):
                return ToolExecutionResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    success=False,
                    content="工具需要用户确认后才能执行。",
                    error="permission_confirmation_required",
                    data={
                        "permission": permission.value,
                        "risk": getattr(risk, "value", "medium"),
                        "read_only": read_only,
                    },
                    stable_rule_candidate=learn_policy == "rule",
                    candidate_type="rule" if learn_policy == "rule" else "skill",
                    permission=permission,
                    risk=risk or ToolRisk.MEDIUM,
                    read_only=read_only,
                )
            return tool.execute(question, context)
        return None

    def execute_by_id(
        self,
        tool_id: str,
        question: str,
        context: dict[str, Any],
    ) -> ToolExecutionResult | None:
        for tool in self.tools:
            if tool.id != tool_id:
                continue
            return tool.execute(question, context)
        return None

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": tool.id,
                "name": tool.name,
                "description": tool.description,
                "permission": getattr(getattr(tool, "permission", Permission.AUTO), "value", "auto"),
                "risk": getattr(getattr(tool, "risk", ToolRisk.LOW), "value", "low"),
                "read_only": getattr(tool, "read_only", True),
                "learn_policy": getattr(tool, "learn_policy", ""),
                "input_schema": {
                    "required": getattr(getattr(tool, "input_schema", None), "required", []),
                    "properties": getattr(getattr(tool, "input_schema", None), "properties", {}),
                },
                "output_schema": {
                    "required": getattr(getattr(tool, "output_schema", None), "required", []),
                    "properties": getattr(getattr(tool, "output_schema", None), "properties", {}),
                },
            }
            for tool in self.tools
        ]


def build_default_tool_registry() -> ToolRegistry:
    from monkey_agent.domains.tools.builtin.feishu import FeishuSendMessageTool
    from monkey_agent.domains.tools.builtin.weather import OpenMeteoWeatherTool
    from monkey_agent.domains.tools.builtin.web_search import WebSearchTool

    return ToolRegistry(
        [
            OpenMeteoWeatherTool(),
            FeishuSendMessageTool(),
            WebSearchTool(),
        ]
    )


def _confirmed(tool_id: str, context: dict[str, Any]) -> bool:
    if context.get("confirm_tool_execution") is True:
        return True
    if context.get(f"confirm_{tool_id}") is True:
        return True
    confirmed = context.get("confirmed_tools", [])
    return isinstance(confirmed, list) and tool_id in confirmed
