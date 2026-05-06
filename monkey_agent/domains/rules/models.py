from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    name: str
    intents: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    priority: int = 0
    status: str = "active"
    rule: str = ""
    handler: str = "pass_through"
    output_format: str | None = None
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        intents = data.get("intent", data.get("intents", [])) or []
        if isinstance(intents, str):
            intents = [intents]
        keywords = data.get("keywords", []) or []
        if isinstance(keywords, str):
            keywords = [keywords]
        known = {
            "id",
            "type",
            "name",
            "intent",
            "intents",
            "keywords",
            "priority",
            "status",
            "rule",
            "handler",
            "output_format",
            "source",
        }
        metadata = {key: value for key, value in data.items() if key not in known}
        return cls(
            id=str(data["id"]),
            type=str(data.get("type", "business_definition")),
            name=str(data.get("name", data["id"])),
            intents=[str(item) for item in intents],
            keywords=[str(item) for item in keywords],
            priority=int(data.get("priority", 0)),
            status=str(data.get("status", "active")),
            rule=str(data.get("rule", "")),
            handler=str(data.get("handler", "pass_through")),
            output_format=data.get("output_format"),
            source=str(data.get("source", "manual")),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "intent": self.intents,
            "keywords": self.keywords,
            "priority": self.priority,
            "status": self.status,
            "rule": self.rule,
            "handler": self.handler,
            "output_format": self.output_format,
            "source": self.source,
            **self.metadata,
        }


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = self.rule.to_dict()
        data["match_score"] = self.score
        data["match_reasons"] = self.reasons
        return data
