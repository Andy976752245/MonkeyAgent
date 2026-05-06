from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MemoryContext:
    preferences: list[dict[str, Any]] = field(default_factory=list)
    counterexamples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferences": self.preferences,
            "counterexamples": self.counterexamples,
        }


class PersonalMemoryStore:
    def __init__(
        self,
        memory_dir: Path,
        counterexamples_dir: Path,
        fallback_memory_dirs: list[Path] | None = None,
        fallback_counterexamples_dirs: list[Path] | None = None,
    ) -> None:
        self.memory_dir = memory_dir
        self.counterexamples_dir = counterexamples_dir
        self.fallback_memory_dirs = fallback_memory_dirs or []
        self.fallback_counterexamples_dirs = fallback_counterexamples_dirs or []

    def retrieve(self, question: str, context: dict[str, Any]) -> MemoryContext:
        return MemoryContext(
            preferences=_matching_yaml_many(
                [self.memory_dir, *self.fallback_memory_dirs],
                question,
            ),
            counterexamples=_matching_yaml_many(
                [self.counterexamples_dir, *self.fallback_counterexamples_dirs],
                question,
            ),
        )


def _matching_yaml_many(paths: list[Path], question: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for item in _matching_yaml(path, question):
            item_id = str(item.get("id") or item.get("_path"))
            if item_id in seen:
                continue
            seen.add(item_id)
            items.append(item)
            if len(items) >= 5:
                return items
    return items


def _matching_yaml(path: Path, question: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for item in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(item.read_text(encoding="utf-8")) or {}
        keywords = data.get("keywords", []) or []
        if isinstance(keywords, str):
            keywords = [keywords]
        if not keywords or any(str(keyword).lower() in question.lower() for keyword in keywords):
            data["_path"] = str(item)
            items.append(data)
    return items[:5]
