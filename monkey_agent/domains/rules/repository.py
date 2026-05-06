from __future__ import annotations

from pathlib import Path

import yaml

from .models import Rule


class RuleRepository:
    def __init__(self, rules_dir: Path, fallback_dirs: list[Path] | None = None) -> None:
        self.rules_dir = rules_dir
        self.fallback_dirs = fallback_dirs or []

    def list(self) -> list[Rule]:
        rules: list[Rule] = []
        seen: set[str] = set()
        for index, directory in enumerate([self.rules_dir, *self.fallback_dirs]):
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.yaml")):
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                data["_source_layer"] = "personal" if index == 0 else "global"
                rule = Rule.from_dict(data)
                if rule.id in seen:
                    continue
                seen.add(rule.id)
                rules.append(rule)
        return rules

    def active(self) -> list[Rule]:
        return [rule for rule in self.list() if rule.status == "active"]
