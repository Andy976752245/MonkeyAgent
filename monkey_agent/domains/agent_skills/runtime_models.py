from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from monkey_agent.domains.execution import ExecutionResult


@dataclass(frozen=True)
class AgentSkillExecutionPlan:
    skill_id: str
    script_path: str
    input_data: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "script_path": self.script_path,
            "input": self.input_data,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AgentSkillSafetyReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "risk": self.risk,
        }


@dataclass(frozen=True)
class AgentSkillExecutionResult:
    skill_id: str
    script_path: str
    success: bool
    requires_confirmation: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error: str = ""
    artifacts: list[str] = field(default_factory=list)
    safety_report: AgentSkillSafetyReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "script_path": self.script_path,
            "success": self.success,
            "requires_confirmation": self.requires_confirmation,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
            "artifacts": self.artifacts,
            "safety_report": self.safety_report.to_dict() if self.safety_report else {},
        }

    def to_execution_result(self) -> ExecutionResult:
        return ExecutionResult(
            kind="agent_skill",
            success=self.success,
            content=self.stdout,
            artifacts=self.artifacts,
            requires_confirmation=self.requires_confirmation,
            error=self.error or None,
            risk=(self.safety_report.risk if self.safety_report else "low"),
            metadata={
                "skill_id": self.skill_id,
                "script_path": self.script_path,
                "stderr": self.stderr,
                "exit_code": self.exit_code,
                "safety_report": self.safety_report.to_dict()
                if self.safety_report
                else {},
            },
        )


def artifact_dir(root: Path, skill_id: str) -> Path:
    return root / "skills" / skill_id
