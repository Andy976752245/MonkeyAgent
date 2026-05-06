from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationCheck:
    name: str
    passed: bool
    message: str = ""
    severity: str = "info"
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
            "data": self.data,
        }


@dataclass
class EvaluationResult:
    status: str = "pass"
    score: float = 1.0
    passed_checks: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    revision_suggestions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    counterexample_hits: list[dict[str, Any]] = field(default_factory=list)
    checks: list[EvaluationCheck] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "risk_flags": self.risk_flags,
            "revision_suggestions": self.revision_suggestions,
            "requires_confirmation": self.requires_confirmation,
            "counterexample_hits": self.counterexample_hits,
            "checks": [check.to_dict() for check in self.checks],
            "summary": self.summary,
        }

    @classmethod
    def from_checks(
        cls,
        checks: list[EvaluationCheck],
        *,
        requires_confirmation: bool = False,
        counterexample_hits: list[dict[str, Any]] | None = None,
        summary: str = "",
    ) -> "EvaluationResult":
        failed = [check for check in checks if not check.passed]
        risk_flags = [check.name for check in failed if check.severity in {"warning", "error"}]
        hard_failures = [check for check in failed if check.severity == "error"]
        warnings = [check for check in failed if check.severity == "warning"]
        if requires_confirmation:
            status = "waiting_human"
        elif hard_failures:
            status = "needs_revision"
        elif warnings:
            status = "pass"
        else:
            status = "pass"
        passed_count = len([check for check in checks if check.passed])
        score = 1.0 if not checks else round(max(0.0, passed_count / len(checks)), 3)
        if hard_failures:
            score = min(score, 0.5)
        elif warnings:
            score = min(score, 0.75)
        return cls(
            status=status,
            score=score,
            passed_checks=[check.name for check in checks if check.passed],
            failed_checks=[check.name for check in failed],
            risk_flags=risk_flags,
            revision_suggestions=[check.message for check in failed if check.message],
            requires_confirmation=requires_confirmation,
            counterexample_hits=counterexample_hits or [],
            checks=checks,
            summary=summary or _summary(status, failed),
        )


def _summary(status: str, failed: list[EvaluationCheck]) -> str:
    if status == "waiting_human":
        return "评估发现该结果需要人工确认。"
    if failed:
        names = ", ".join(check.name for check in failed[:3])
        return f"评估发现需要关注的检查项：{names}。"
    return "评估通过。"
