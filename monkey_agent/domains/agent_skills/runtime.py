from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from monkey_agent.domains.agent_skills.models import AgentSkill
from monkey_agent.domains.agent_skills.runtime_models import (
    AgentSkillExecutionPlan,
    AgentSkillExecutionResult,
    artifact_dir,
)
from monkey_agent.domains.agent_skills.safety import AgentSkillSafetyChecker


class AgentSkillRuntime:
    def __init__(
        self,
        artifacts_root: Path,
        timeout_seconds: int = 30,
        safety_checker: AgentSkillSafetyChecker | None = None,
    ) -> None:
        self.artifacts_root = artifacts_root
        self.timeout_seconds = timeout_seconds
        self.safety_checker = safety_checker or AgentSkillSafetyChecker()

    def validate(
        self,
        skill: AgentSkill,
        plan: AgentSkillExecutionPlan,
    ) -> dict[str, Any]:
        artifacts_dir = artifact_dir(self.artifacts_root, skill.id)
        report = self.safety_checker.validate(
            Path(skill.path),
            plan.script_path,
            artifacts_dir,
        )
        return {
            "plan": plan.to_dict(),
            "safety_report": report.to_dict(),
            "artifacts_dir": str(artifacts_dir),
        }

    def execute(
        self,
        skill: AgentSkill,
        plan: AgentSkillExecutionPlan,
        confirm: bool = False,
    ) -> AgentSkillExecutionResult:
        artifacts_dir = artifact_dir(self.artifacts_root, skill.id)
        safety_report = self.safety_checker.validate(Path(skill.path), plan.script_path, artifacts_dir)
        if not safety_report.passed:
            return AgentSkillExecutionResult(
                skill_id=skill.id,
                script_path=plan.script_path,
                success=False,
                error="unsafe_skill_script",
                safety_report=safety_report,
            )
        if not confirm:
            return AgentSkillExecutionResult(
                skill_id=skill.id,
                script_path=plan.script_path,
                success=False,
                requires_confirmation=True,
                error="skill_execution_confirmation_required",
                safety_report=safety_report,
            )

        skill_root = Path(skill.path).resolve()
        script = (skill_root / plan.script_path).resolve()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        before = _artifact_snapshot(artifacts_dir)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as raw:
            json.dump(plan.input_data, raw, ensure_ascii=False)
            input_path = Path(raw.name)
        try:
            completed = subprocess.run(
                _command_for(script),
                cwd=skill_root,
                input=json.dumps(plan.input_data, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env={
                    **os.environ,
                    "MONKEY_AGENT_SKILL_INPUT": str(input_path),
                    "MONKEY_AGENT_ARTIFACTS_DIR": str(artifacts_dir),
                },
            )
        except subprocess.TimeoutExpired as exc:
            return AgentSkillExecutionResult(
                skill_id=skill.id,
                script_path=plan.script_path,
                success=False,
                stderr=str(exc),
                error="skill_script_timeout",
                safety_report=safety_report,
            )
        finally:
            try:
                input_path.unlink()
            except OSError:
                pass
        artifacts = sorted(str(path) for path in _artifact_snapshot(artifacts_dir) - before)
        return AgentSkillExecutionResult(
            skill_id=skill.id,
            script_path=plan.script_path,
            success=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            error="" if completed.returncode == 0 else "skill_script_failed",
            artifacts=artifacts,
            safety_report=safety_report,
        )


def _command_for(script: Path) -> list[str]:
    if script.suffix == ".py":
        return [sys.executable, str(script)]
    return [str(script)]


def _artifact_snapshot(path: Path) -> set[Path]:
    if not path.exists():
        return set()
    return {item for item in path.rglob("*") if item.is_file()}
