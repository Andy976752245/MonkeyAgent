from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from monkey_agent.domains.agent_skills.models import AgentSkill
from monkey_agent.domains.agent_skills.parser import AgentSkillParser


class AgentSkillRepository:
    def __init__(self, skills_dir: Path, registry_path: Path) -> None:
        self.skills_dir = skills_dir
        self.registry_path = registry_path
        self.parser = AgentSkillParser()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.registry_path.write_text("[]\n", encoding="utf-8")

    def list(self) -> list[AgentSkill]:
        skills: list[AgentSkill] = []
        for record in self._read_registry():
            try:
                root = Path(str(record.get("path") or self.skills_dir / str(record.get("id"))))
                parsed = self.parser.parse(root)
                skills.append(
                    AgentSkill.from_dict(
                        record,
                        body=parsed.body,
                        files=parsed.files,
                    )
                )
            except (OSError, ValueError):
                skills.append(AgentSkill.from_dict(record))
        return skills

    def active(self) -> list[AgentSkill]:
        return [skill for skill in self.list() if skill.status == "active"]

    def get(self, skill_name: str) -> AgentSkill | None:
        for skill in self.list():
            if skill.id == skill_name:
                return skill
        return None

    def inspect(self, skill_name: str) -> dict[str, Any] | None:
        skill = self.get(skill_name)
        if skill is None:
            return None
        return skill.to_dict(include_body=True)

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        items = self._read_registry()
        updated = False
        for index, item in enumerate(items):
            if item.get("id") == record.get("id"):
                preserved_status = item.get("status")
                merged = {**item, **record}
                if preserved_status and "status" not in record:
                    merged["status"] = preserved_status
                items[index] = merged
                updated = True
                record = merged
                break
        if not updated:
            items.append(record)
        self._write_registry(items)
        return record

    def set_enabled(self, skill_name: str, enabled: bool) -> dict[str, Any]:
        items = self._read_registry()
        for item in items:
            if item.get("id") == skill_name:
                item["status"] = "active" if enabled else "disabled"
                self._write_registry(items)
                return item
        raise FileNotFoundError(f"agent skill not found: {skill_name}")

    def remove(self, skill_name: str) -> dict[str, Any]:
        items = self._read_registry()
        removed = None
        remaining = []
        for item in items:
            if item.get("id") == skill_name:
                removed = item
            else:
                remaining.append(item)
        if removed is None:
            raise FileNotFoundError(f"agent skill not found: {skill_name}")
        self._write_registry(remaining)
        return removed

    def _read_registry(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or []
        if not isinstance(data, list):
            raise ValueError("agent skills registry must be a YAML list")
        return [item for item in data if isinstance(item, dict)]

    def _write_registry(self, items: list[dict[str, Any]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            yaml.safe_dump(items, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
