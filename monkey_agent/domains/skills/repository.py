from __future__ import annotations

from pathlib import Path

import yaml

from .models import Skill


class SkillRepository:
    def __init__(self, skills_dir: Path, fallback_dirs: list[Path] | None = None) -> None:
        self.skills_dir = skills_dir
        self.fallback_dirs = fallback_dirs or []

    def list(self) -> list[Skill]:
        skills: list[Skill] = []
        seen: set[str] = set()
        for index, directory in enumerate([self.skills_dir, *self.fallback_dirs]):
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.yaml")):
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                data["_source_layer"] = "personal" if index == 0 else "global"
                skill = Skill.from_dict(data)
                if skill.id in seen:
                    continue
                seen.add(skill.id)
                skills.append(skill)
        return skills

    def active(self) -> list[Skill]:
        return [skill for skill in self.list() if skill.status == "active"]
