from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from monkey_agent.domains.execution import ExecutionResult


class Permission(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolSchema:
    required: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInputIssue:
    field: str
    message: str


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_id: str
    tool_name: str
    success: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stable_rule_candidate: bool = False
    candidate_type: str | None = None
    handler_name: str | None = None
    handler_code_proposal: str | None = None
    public_evidence: list[dict[str, Any]] = field(default_factory=list)
    permission: Permission = Permission.AUTO
    risk: ToolRisk = ToolRisk.LOW
    read_only: bool = True

    def to_deterministic_result(self) -> dict[str, Any]:
        return {
            "rule_id": f"capability:{self.tool_id}",
            "rule_name": self.tool_name,
            "type": "capability_tool",
            "requires_more_info": False,
            "content": self.content,
            "data": self.data,
            "source_tool": self.tool_id,
        }

    def to_execution_result(self) -> ExecutionResult:
        return ExecutionResult(
            kind="tool",
            success=self.success,
            content=self.content,
            data=self.data,
            evidence=self.public_evidence,
            requires_confirmation=self.permission == Permission.CONFIRM,
            error=self.error,
            risk=self.risk.value,
            metadata={
                "tool_id": self.tool_id,
                "tool_name": self.tool_name,
                "permission": self.permission.value,
                "read_only": self.read_only,
                "stable_rule_candidate": self.stable_rule_candidate,
                "candidate_type": self.candidate_type,
            },
        )


class Tool(Protocol):
    id: str
    name: str
    description: str
    input_schema: ToolSchema
    output_schema: ToolSchema
    permission: Permission
    risk: ToolRisk
    read_only: bool
    learn_policy: str

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        ...

    def execute(self, question: str, context: dict[str, Any]) -> ToolExecutionResult:
        ...


def validate_input(tool: Tool, context: dict[str, Any]) -> list[ToolInputIssue]:
    issues: list[ToolInputIssue] = []
    input_schema = getattr(tool, "input_schema", ToolSchema())
    for field in input_schema.required:
        if context.get(field) in (None, ""):
            issues.append(ToolInputIssue(field=field, message="required field is missing"))
    return issues
