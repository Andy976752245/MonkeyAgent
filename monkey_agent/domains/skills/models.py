from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    task_types: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    priority: int = 0
    status: str = "active"
    prompt: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        task_types = data.get("task_types", []) or []
        if isinstance(task_types, str):
            task_types = [task_types]
        keywords = data.get("keywords", []) or []
        if isinstance(keywords, str):
            keywords = [keywords]
        known = {
            "id",
            "name",
            "description",
            "task_types",
            "keywords",
            "priority",
            "status",
            "prompt",
            "examples",
            "version",
        }
        metadata = {key: value for key, value in data.items() if key not in known}
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            description=str(data.get("description", "")),
            task_types=[str(item) for item in task_types],
            keywords=[str(item) for item in keywords],
            priority=int(data.get("priority", 0)),
            status=str(data.get("status", "active")),
            prompt=str(data.get("prompt", "")),
            examples=data.get("examples", []) or [],
            version=str(data.get("version", "1.0.0")),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_types": self.task_types,
            "keywords": self.keywords,
            "priority": self.priority,
            "status": self.status,
            "prompt": self.prompt,
            "examples": self.examples,
            "version": self.version,
            **self.metadata,
        }
