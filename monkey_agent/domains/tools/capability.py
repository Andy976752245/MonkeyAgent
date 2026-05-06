from __future__ import annotations

from typing import Any, Protocol

from monkey_agent.domains.tools import ToolExecutionResult


ToolResult = ToolExecutionResult


class CapabilityTool(Protocol):
    id: str
    name: str
    description: str

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        ...

    def execute(self, question: str, context: dict[str, Any]) -> ToolResult:
        ...


class CapabilityRegistry:
    def __init__(self, tools: list[CapabilityTool] | None = None) -> None:
        self.tools = tools or []

    def add(self, tool: CapabilityTool) -> None:
        self.tools = [item for item in self.tools if item.id != tool.id]
        self.tools.append(tool)

    def explore(self, question: str, context: dict[str, Any]) -> ToolResult | None:
        for tool in self.tools:
            if not tool.can_handle(question, context):
                continue
            return tool.execute(question, context)
        return None

    def execute_by_id(
        self,
        tool_id: str,
        question: str,
        context: dict[str, Any],
    ) -> ToolResult | None:
        for tool in self.tools:
            if tool.id != tool_id:
                continue
            return tool.execute(question, context)
        return None

    def list(self) -> list[dict[str, str]]:
        return [
            {
                "id": tool.id,
                "name": tool.name,
                "description": tool.description,
            }
            for tool in self.tools
        ]


def build_default_registry() -> CapabilityRegistry:
    from monkey_agent.domains.tools.registry import build_default_tool_registry

    registry = build_default_tool_registry()
    return CapabilityRegistry(registry.tools)
