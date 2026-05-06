from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


GOAL_STATUSES = {"active", "waiting_human", "completed", "failed", "paused"}
TASK_STATUSES = {"pending", "running", "done", "blocked", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GoalTask:
    task_id: str
    title: str
    type: str
    status: str = "pending"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    risk: str = "low"
    depends_on: list[str] = field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 2
    executor: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    result_score: float = 0.0
    failure_reason: str | None = None
    priority: int = 50

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalTask":
        task_type = str(data.get("type") or "reasoning")
        return cls(
            task_id=str(data["task_id"]),
            title=str(data.get("title") or data["task_id"]),
            type=task_type,
            status=str(data.get("status") or "pending"),
            input=dict(data.get("input") or {}),
            output=dict(data.get("output") or {}),
            evidence=list(data.get("evidence") or []),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            risk=str(data.get("risk") or "low"),
            depends_on=[str(item) for item in data.get("depends_on", []) or []],
            attempts=int(data.get("attempts") or 0),
            max_attempts=int(data.get("max_attempts") or 2),
            executor=str(data.get("executor") or task_type),
            acceptance_criteria=[
                str(item) for item in data.get("acceptance_criteria", []) or []
            ],
            result_score=float(data.get("result_score") or 0.0),
            failure_reason=(
                None
                if data.get("failure_reason") is None
                else str(data.get("failure_reason"))
            ),
            priority=int(data.get("priority") or 50),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "type": self.type,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "evidence": self.evidence,
            "requires_confirmation": self.requires_confirmation,
            "risk": self.risk,
            "depends_on": self.depends_on,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "executor": self.executor or self.type,
            "acceptance_criteria": self.acceptance_criteria,
            "result_score": self.result_score,
            "failure_reason": self.failure_reason,
            "priority": self.priority,
        }


@dataclass
class Goal:
    id: str
    goal: str
    status: str = "active"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    max_steps: int = 5
    autonomy_policy: str = "read_only_auto_write_confirm"
    success_criteria: list[str] = field(default_factory=list)
    current_step: int = 0
    summary: str = ""
    waiting_reason: str | None = None
    last_evaluation: dict[str, Any] = field(default_factory=dict)
    plan_version: int = 1
    revision_count: int = 0
    max_revisions: int = 2
    force_learning: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Goal":
        return cls(
            id=str(data["id"]),
            goal=str(data.get("goal") or ""),
            status=str(data.get("status") or "active"),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            max_steps=int(data.get("max_steps") or 5),
            autonomy_policy=str(data.get("autonomy_policy") or "read_only_auto_write_confirm"),
            success_criteria=list(data.get("success_criteria") or []),
            current_step=int(data.get("current_step") or 0),
            summary=str(data.get("summary") or ""),
            waiting_reason=(
                None
                if data.get("waiting_reason") is None
                else str(data.get("waiting_reason"))
            ),
            last_evaluation=dict(data.get("last_evaluation") or {}),
            plan_version=int(data.get("plan_version") or 1),
            revision_count=int(data.get("revision_count") or 0),
            max_revisions=int(data.get("max_revisions") or 2),
            force_learning=bool(data.get("force_learning", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "max_steps": self.max_steps,
            "autonomy_policy": self.autonomy_policy,
            "success_criteria": self.success_criteria,
            "current_step": self.current_step,
            "summary": self.summary,
            "waiting_reason": self.waiting_reason,
            "last_evaluation": self.last_evaluation,
            "plan_version": self.plan_version,
            "revision_count": self.revision_count,
            "max_revisions": self.max_revisions,
            "force_learning": self.force_learning,
        }


@dataclass
class GoalEvent:
    event: str
    goal_id: str
    task_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "data": self.data,
            "created_at": self.created_at,
        }


@dataclass
class GoalRunResult:
    goal_id: str
    status: str
    summary: str
    current_task: dict[str, Any] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None
    learning_candidate_ids: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    execution_path: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    last_evaluation: dict[str, Any] = field(default_factory=dict)
    plan_version: int = 1
    revision_count: int = 0
    next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "status": self.status,
            "summary": self.summary,
            "current_task": self.current_task,
            "tasks": self.tasks,
            "events": self.events,
            "answer": self.answer,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
            "learning_candidate_ids": self.learning_candidate_ids,
            "artifacts": self.artifacts,
            "execution_path": self.execution_path,
            "evidence": self.evidence,
            "evaluations": self.evaluations,
            "last_evaluation": self.last_evaluation,
            "plan_version": self.plan_version,
            "revision_count": self.revision_count,
            "next_action": self.next_action,
        }
