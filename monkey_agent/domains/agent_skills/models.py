from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentSkill:
    id: str
    name: str
    description: str
    status: str
    source: str
    source_url: str
    path: str
    installed_at: str
    updated_at: str
    version: str = ""
    license: str = ""
    compatibility: Any = ""
    allowed_tools: str = ""
    checksum: str = ""
    body: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], body: str = "", files: list[dict[str, Any]] | None = None) -> "AgentSkill":
        known = {
            "id",
            "name",
            "description",
            "status",
            "source",
            "source_url",
            "path",
            "installed_at",
            "updated_at",
            "version",
            "license",
            "compatibility",
            "allowed_tools",
            "checksum",
        }
        metadata = {key: value for key, value in data.items() if key not in known}
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            description=str(data.get("description") or ""),
            status=str(data.get("status") or "active"),
            source=str(data.get("source") or "local"),
            source_url=str(data.get("source_url") or ""),
            path=str(data.get("path") or ""),
            installed_at=str(data.get("installed_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            version=str(data.get("version") or ""),
            license=str(data.get("license") or ""),
            compatibility=data.get("compatibility") or "",
            allowed_tools=str(data.get("allowed_tools") or ""),
            checksum=str(data.get("checksum") or ""),
            body=body,
            files=files or [],
            metadata=metadata,
        )

    def to_dict(self, include_body: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "source": self.source,
            "source_url": self.source_url,
            "path": self.path,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            "checksum": self.checksum,
            "skill_kind": "agent",
            "files": self.files,
            **self.metadata,
        }
        if include_body:
            data["body"] = self.body
            data["prompt"] = self.prompt
        return data

    @property
    def prompt(self) -> str:
        files = "\n".join(
            f"- {item.get('path')} ({item.get('kind')}, {item.get('size')} bytes)"
            for item in self.files
        )
        return (
            f"Agent Skill: {self.name}\n"
            f"Description: {self.description}\n"
            f"Skill directory: {self.path}\n"
            "Instructions from SKILL.md:\n"
            f"{self.body.strip()}\n\n"
            "Bundled files available for reference only; scripts are not auto-executed:\n"
            f"{files or '- SKILL.md'}"
        )

    def match_text(self) -> str:
        metadata_tags = self.metadata.get("tags") or self.metadata.get("keywords") or []
        if isinstance(metadata_tags, str):
            metadata_tags = [metadata_tags]
        return " ".join(
            [
                self.id,
                self.name,
                self.description,
                " ".join(str(item) for item in metadata_tags),
            ]
        ).lower()


def registry_record(
    *,
    root: Path,
    frontmatter: dict[str, Any],
    source: str,
    source_url: str,
    checksum: str,
    installed_at: str,
    updated_at: str,
) -> dict[str, Any]:
    metadata = frontmatter.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {"raw_metadata": metadata}
    version = str(metadata.get("version") or frontmatter.get("version") or "")
    return {
        "id": str(frontmatter["name"]),
        "name": str(frontmatter["name"]),
        "description": str(frontmatter["description"]),
        "status": "active",
        "source": source,
        "source_url": source_url,
        "installed_at": installed_at,
        "updated_at": updated_at,
        "path": str(root),
        "version": version,
        "license": str(frontmatter.get("license") or ""),
        "compatibility": frontmatter.get("compatibility") or "",
        "allowed_tools": str(frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools") or ""),
        "checksum": checksum,
        **metadata,
    }
