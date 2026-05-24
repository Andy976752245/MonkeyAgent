from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    kind: str
    success: bool
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    error: str | None = None
    risk: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "success": self.success,
            "content": self.content,
            "data": self.data,
            "artifacts": self.artifacts,
            "evidence": self.evidence,
            "requires_confirmation": self.requires_confirmation,
            "error": self.error,
            "risk": self.risk,
            "metadata": self.metadata,
        }
