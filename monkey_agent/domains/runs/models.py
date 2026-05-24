from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunRecord:
    id: str
    type: str
    status: str
    created_at: str
    updated_at: str
    input: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    route: str = ""
    execution_path: list[str] = field(default_factory=list)
    timings: list[dict[str, Any]] = field(default_factory=list)
    classification: dict[str, Any] = field(default_factory=dict)
    routing_policy: dict[str, Any] = field(default_factory=dict)
    matched_rules: list[dict[str, Any]] = field(default_factory=list)
    matched_skills: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    memory_used: list[dict[str, Any]] = field(default_factory=list)
    counterexamples_checked: list[dict[str, Any]] = field(default_factory=list)
    tool_builder: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    learning_candidate_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    answer_preview: str = ""
    raw_result_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input": self.input,
            "summary": self.summary,
            "route": self.route,
            "execution_path": self.execution_path,
            "timings": self.timings,
            "classification": self.classification,
            "routing_policy": self.routing_policy,
            "matched_rules": self.matched_rules,
            "matched_skills": self.matched_skills,
            "tools": self.tools,
            "memory_used": self.memory_used,
            "counterexamples_checked": self.counterexamples_checked,
            "tool_builder": self.tool_builder,
            "evaluation": self.evaluation,
            "learning_candidate_ids": self.learning_candidate_ids,
            "errors": self.errors,
            "answer_preview": self.answer_preview,
            "raw_result_path": self.raw_result_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            id=str(data.get("id") or ""),
            type=str(data.get("type") or ""),
            status=str(data.get("status") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            input=dict(data.get("input") or {}),
            summary=str(data.get("summary") or ""),
            route=str(data.get("route") or ""),
            execution_path=[str(item) for item in data.get("execution_path", [])],
            timings=_dict_list(data.get("timings")),
            classification=dict(data.get("classification") or {}),
            routing_policy=dict(data.get("routing_policy") or {}),
            matched_rules=_dict_list(data.get("matched_rules")),
            matched_skills=_dict_list(data.get("matched_skills")),
            tools=_dict_list(data.get("tools")),
            memory_used=_dict_list(data.get("memory_used")),
            counterexamples_checked=_dict_list(data.get("counterexamples_checked")),
            tool_builder=dict(data.get("tool_builder") or {}),
            evaluation=dict(data.get("evaluation") or {}),
            learning_candidate_ids=[
                str(item) for item in data.get("learning_candidate_ids", []) if item
            ],
            errors=[str(item) for item in data.get("errors", []) if item],
            answer_preview=str(data.get("answer_preview") or ""),
            raw_result_path=(
                str(data["raw_result_path"])
                if data.get("raw_result_path") is not None
                else None
            ),
        )


@dataclass
class RunSummary:
    id: str
    type: str
    status: str
    created_at: str
    updated_at: str
    summary: str
    route: str
    answer_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "route": self.route,
            "answer_preview": self.answer_preview,
        }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
