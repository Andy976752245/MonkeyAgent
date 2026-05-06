from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClassificationResult:
    deterministic: list[str] = field(default_factory=list)
    semi_deterministic: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    task_type: str = "general"
    confidence: float = 0.5
    clarification_questions: list[str] = field(default_factory=list)
    source: str = "keyword"

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str) -> "ClassificationResult":
        return cls(
            deterministic=_list_of_str(data.get("deterministic", [])),
            semi_deterministic=_list_of_str(data.get("semi_deterministic", [])),
            uncertain=_list_of_str(data.get("uncertain", [])),
            intents=_list_of_str(data.get("intents", [])),
            required_tools=_list_of_str(data.get("required_tools", [])),
            task_type=str(data.get("task_type") or "general"),
            confidence=float(data.get("confidence", 0.5) or 0.5),
            clarification_questions=_list_of_str(data.get("clarification_questions", [])),
            source=source,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic,
            "semi_deterministic": self.semi_deterministic,
            "uncertain": self.uncertain,
            "intents": self.intents,
            "required_tools": self.required_tools,
            "task_type": self.task_type,
            "confidence": self.confidence,
            "clarification_questions": self.clarification_questions,
            "source": self.source,
        }


def _list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
