from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monkey_agent.domains.agent_skills.models import registry_record
from monkey_agent.domains.agent_skills.parser import AgentSkillParser
from monkey_agent.domains.agent_skills.repository import AgentSkillRepository


class AgentSkillInstaller:
    def __init__(
        self,
        skills_dir: Path,
        repository: AgentSkillRepository,
        parser: AgentSkillParser | None = None,
    ) -> None:
        self.skills_dir = skills_dir
        self.repository = repository
        self.parser = parser or AgentSkillParser()

    def import_local(self, path: Path) -> dict[str, Any]:
        source = path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"agent skill path not found: {source}")
        return self._install_from_dir(source, source="local", source_url=str(source))

    def install(self, source: str, skill_name: str | None = None) -> dict[str, Any]:
        parsed = _parse_source(source, skill_name)
        if parsed["kind"] == "local":
            return self.import_local(Path(str(parsed["path"])))
        with tempfile.TemporaryDirectory() as raw:
            clone_dir = Path(raw) / "repo"
            _git_clone(str(parsed["repo_url"]), clone_dir)
            selected = self._select_skill_dir(clone_dir, parsed.get("skill_name"))
            return self._install_from_dir(
                selected,
                source="github",
                source_url=str(parsed["source_url"]),
            )

    def enable(self, skill_name: str) -> dict[str, Any]:
        return self.repository.set_enabled(skill_name, True)

    def disable(self, skill_name: str) -> dict[str, Any]:
        return self.repository.set_enabled(skill_name, False)

    def remove(self, skill_name: str) -> dict[str, Any]:
        record = self.repository.remove(skill_name)
        path = Path(str(record.get("path") or self.skills_dir / skill_name))
        if _is_within(path, self.skills_dir) and path.exists():
            shutil.rmtree(path)
        return record

    def _install_from_dir(self, source_dir: Path, source: str, source_url: str) -> dict[str, Any]:
        parsed = self.parser.parse(source_dir)
        target = self.skills_dir / str(parsed.frontmatter["name"])
        if target.exists():
            shutil.rmtree(target)
        _copy_tree(parsed.root, target)
        parsed_target = self.parser.parse(target)
        now = datetime.now(timezone.utc).isoformat()
        existing = self.repository.get(str(parsed_target.frontmatter["name"]))
        record = registry_record(
            root=target,
            frontmatter=parsed_target.frontmatter,
            source=source,
            source_url=source_url,
            checksum=parsed_target.checksum,
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
        )
        if existing and existing.status:
            record["status"] = existing.status
        return self.repository.upsert(record)

    def _select_skill_dir(self, repo_dir: Path, skill_name: str | None) -> Path:
        if skill_name:
            direct_candidates = [
                repo_dir / skill_name,
                repo_dir / "skills" / skill_name,
                repo_dir / ".claude" / "skills" / skill_name,
                repo_dir / ".codex" / "skills" / skill_name,
            ]
            for candidate in direct_candidates:
                if (candidate / "SKILL.md").exists():
                    return candidate
            for skill_md in repo_dir.rglob("SKILL.md"):
                if skill_md.parent.name == skill_name:
                    return skill_md.parent
            raise FileNotFoundError(f"skill not found in repository: {skill_name}")
        if (repo_dir / "SKILL.md").exists():
            return repo_dir
        found = [path.parent for path in repo_dir.rglob("SKILL.md")]
        if len(found) == 1:
            return found[0]
        if not found:
            raise FileNotFoundError("repository does not contain SKILL.md")
        raise ValueError("repository contains multiple skills; pass --skill")


def _parse_source(source: str, skill_name: str | None) -> dict[str, Any]:
    raw = source.strip()
    local = Path(raw).expanduser()
    if raw.startswith("file://"):
        return {"kind": "local", "path": raw.removeprefix("file://")}
    if local.exists():
        return {"kind": "local", "path": str(local)}
    if raw.startswith("https://github.com/"):
        normalized = raw.removesuffix(".git").rstrip("/")
        parts = normalized.split("/")
        if len(parts) < 5:
            raise ValueError("GitHub source must include owner and repo")
        repo_url = "/".join(parts[:5]) + ".git"
        embedded_skill = "/".join(parts[5:]) or None
        return {
            "kind": "github",
            "repo_url": repo_url,
            "skill_name": skill_name or embedded_skill,
            "source_url": raw,
        }
    parts = [part for part in raw.split("/") if part]
    if len(parts) == 2:
        owner, repo = parts
        return {
            "kind": "github",
            "repo_url": f"https://github.com/{owner}/{repo}.git",
            "skill_name": skill_name,
            "source_url": f"https://github.com/{owner}/{repo}",
        }
    if len(parts) == 3:
        owner, repo, embedded_skill = parts
        return {
            "kind": "github",
            "repo_url": f"https://github.com/{owner}/{repo}.git",
            "skill_name": skill_name or embedded_skill,
            "source_url": f"https://github.com/{owner}/{repo}/{embedded_skill}",
        }
    raise ValueError("unsupported agent skill source")


def _git_clone(repo_url: str, target: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git clone failed").strip())


def _copy_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
