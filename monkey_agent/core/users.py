from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PersonalWorkspace:
    root: Path
    rules_dir: Path
    skills_dir: Path
    agent_skills_dir: Path
    agent_skills_registry: Path
    memory_dir: Path
    counterexamples_dir: Path
    generated_tools_dir: Path
    generated_tools_registry: Path
    pending_review_dir: Path
    goals_dir: Path
    runs_dir: Path
    artifacts_dir: Path

    @classmethod
    def from_runtime(cls, runtime_dir: Path) -> "PersonalWorkspace":
        root = runtime_dir / "personal"
        return cls(
            root=root,
            rules_dir=root / "rules",
            skills_dir=root / "skills",
            agent_skills_dir=root / "agent_skills",
            agent_skills_registry=root / "agent_skills.yaml",
            memory_dir=root / "memory",
            counterexamples_dir=root / "counterexamples",
            generated_tools_dir=root / "generated_tools",
            generated_tools_registry=root / "generated_tools.yaml",
            pending_review_dir=root / "pending_review",
            goals_dir=root / "goals",
            runs_dir=root / "runs",
            artifacts_dir=root / "artifacts",
        )

    def ensure(self) -> None:
        for path in [
            self.rules_dir,
            self.skills_dir,
            self.agent_skills_dir,
            self.memory_dir,
            self.counterexamples_dir,
            self.generated_tools_dir,
            self.goals_dir,
            self.artifacts_dir / "skills",
            self.runs_dir / "ask",
            self.runs_dir / "goals",
            self.runs_dir / "tools",
            self.pending_review_dir / "rules",
            self.pending_review_dir / "skills",
            self.pending_review_dir / "memory",
            self.pending_review_dir / "counterexamples",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        if not self.agent_skills_registry.exists():
            self.agent_skills_registry.write_text("[]\n", encoding="utf-8")
