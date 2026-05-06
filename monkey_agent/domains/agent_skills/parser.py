from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


MAX_SKILL_MD_BYTES = 1024 * 1024
MAX_DESCRIPTION_CHARS = 1024
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


@dataclass(frozen=True)
class ParsedAgentSkill:
    root: Path
    frontmatter: dict[str, Any]
    body: str
    checksum: str
    files: list[dict[str, Any]]


class AgentSkillParser:
    def parse(self, skill_dir: Path) -> ParsedAgentSkill:
        root = skill_dir.resolve()
        skill_md = root / "SKILL.md"
        if not skill_md.exists():
            raise ValueError("agent skill is missing SKILL.md")
        self._validate_no_symlink_escape(root)
        raw = skill_md.read_bytes()
        if len(raw) > MAX_SKILL_MD_BYTES:
            raise ValueError("SKILL.md is too large")
        text = raw.decode("utf-8")
        frontmatter, body = self._split_frontmatter(text)
        self._validate_frontmatter(frontmatter, root.name)
        return ParsedAgentSkill(
            root=root,
            frontmatter=frontmatter,
            body=body,
            checksum=hashlib.sha256(raw).hexdigest(),
            files=self.file_inventory(root),
        )

    def file_inventory(self, skill_dir: Path) -> list[dict[str, Any]]:
        root = skill_dir.resolve()
        items: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            relative = path.relative_to(root).as_posix()
            kind = relative.split("/", 1)[0] if "/" in relative else "root"
            items.append(
                {
                    "path": relative,
                    "kind": kind,
                    "size": path.stat().st_size,
                    "executable": bool(path.stat().st_mode & 0o111),
                }
            )
        return items

    def _split_frontmatter(self, text: str) -> tuple[dict[str, Any], str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("SKILL.md must start with YAML frontmatter")
        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            raise ValueError("SKILL.md frontmatter is not closed")
        raw_frontmatter = "\n".join(lines[1:end_index])
        try:
            frontmatter = yaml.safe_load(raw_frontmatter) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid SKILL.md frontmatter: {exc}") from exc
        if not isinstance(frontmatter, dict):
            raise ValueError("SKILL.md frontmatter must be a mapping")
        body = "\n".join(lines[end_index + 1 :]).strip()
        return frontmatter, body

    def _validate_frontmatter(self, frontmatter: dict[str, Any], directory_name: str) -> None:
        name = str(frontmatter.get("name") or "")
        description = str(frontmatter.get("description") or "")
        if not name:
            raise ValueError("SKILL.md frontmatter requires name")
        if not NAME_PATTERN.match(name):
            raise ValueError("agent skill name must be lowercase letters, numbers, and hyphens")
        if name != directory_name:
            raise ValueError("agent skill name must match its parent directory")
        if not description:
            raise ValueError("SKILL.md frontmatter requires description")
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise ValueError("agent skill description is too long")

    def _validate_no_symlink_escape(self, root: Path) -> None:
        root_resolved = root.resolve()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"agent skill contains symlink: {path.relative_to(root)}")
            try:
                path.resolve().relative_to(root_resolved)
            except ValueError as exc:
                raise ValueError(f"agent skill path escapes root: {path}") from exc
