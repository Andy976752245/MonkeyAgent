from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .models import Goal, GoalEvent, GoalTask


class GoalStore:
    def __init__(self, goals_dir: Path) -> None:
        self.goals_dir = goals_dir
        self.goals_dir.mkdir(parents=True, exist_ok=True)

    @property
    def checkpoint_path(self) -> Path:
        return self.goals_dir / "checkpoints.sqlite"

    def new_goal_id(self) -> str:
        return f"goal_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"

    def create(
        self,
        goal: str,
        tasks: list[GoalTask],
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
        success_criteria: list[str] | None = None,
        autonomy_policy: str = "read_only_auto_write_confirm",
        force_learning: bool = False,
    ) -> Goal:
        goal_id = self.new_goal_id()
        item = Goal(
            id=goal_id,
            goal=goal,
            max_steps=max_steps,
            autonomy_policy=autonomy_policy,
            success_criteria=success_criteria or ["完成目标并输出可验证结果。"],
            summary="目标已创建，等待分步执行。",
            force_learning=force_learning,
        )
        directory = self._dir(goal_id)
        (directory / "artifacts").mkdir(parents=True, exist_ok=True)
        (directory / "evidence").mkdir(parents=True, exist_ok=True)
        (directory / "learnings").mkdir(parents=True, exist_ok=True)
        self.save_goal(item)
        self.save_tasks(goal_id, tasks)
        self.append_event(
            goal_id,
            GoalEvent(
                event="goal_created",
                goal_id=goal_id,
                data={"goal": goal, "context": context or {}, "task_count": len(tasks)},
            ),
        )
        return item

    def write_projection(
        self,
        goal: Goal,
        tasks: list[GoalTask],
        events: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        evaluations: list[dict[str, Any]] | None = None,
    ) -> None:
        directory = self._dir(goal.id)
        (directory / "artifacts").mkdir(parents=True, exist_ok=True)
        (directory / "evidence").mkdir(parents=True, exist_ok=True)
        (directory / "learnings").mkdir(parents=True, exist_ok=True)
        self.save_goal(goal)
        self.save_tasks(goal.id, tasks)
        _write_jsonl(directory / "events.jsonl", events or [])
        _write_jsonl(
            directory / "evidence" / "evidence.jsonl",
            [_compact_evidence(item) for item in (evidence or [])],
        )
        _write_jsonl(directory / "evaluations.jsonl", evaluations or [])

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.goals_dir.glob("goal_*/goal.yaml")):
            goal = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            goal["task_count"] = len(self.load_tasks(str(goal.get("id"))))
            items.append(goal)
        return sorted(items, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def get(self, goal_id: str) -> dict[str, Any]:
        goal = self.load_goal(goal_id)
        return {
            **goal.to_dict(),
            "tasks": [task.to_dict() for task in self.load_tasks(goal_id)],
            "events": self.load_events(goal_id),
            "evidence": self.load_evidence(goal_id),
            "evaluations": self.load_evaluations(goal_id),
            "artifacts": self.list_artifacts(goal_id),
        }

    def load_goal(self, goal_id: str) -> Goal:
        path = self._dir(goal_id) / "goal.yaml"
        if not path.exists():
            raise FileNotFoundError(f"goal not found: {goal_id}")
        return Goal.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def save_goal(self, goal: Goal) -> None:
        goal.updated_at = datetime.now(timezone.utc).isoformat()
        directory = self._dir(goal.id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "goal.yaml").write_text(
            yaml.safe_dump(goal.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def load_tasks(self, goal_id: str) -> list[GoalTask]:
        path = self._dir(goal_id) / "tasks.yaml"
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return [GoalTask.from_dict(item) for item in raw]

    def save_tasks(self, goal_id: str, tasks: list[GoalTask]) -> None:
        directory = self._dir(goal_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tasks.yaml").write_text(
            yaml.safe_dump(
                [task.to_dict() for task in tasks],
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def append_event(self, goal_id: str, event: GoalEvent) -> None:
        path = self._dir(goal_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def append_evidence(self, goal_id: str, item: dict[str, Any]) -> None:
        path = self._dir(goal_id) / "evidence" / "evidence.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence = {
            "goal_id": goal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **_compact_evidence(item),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence, ensure_ascii=False) + "\n")

    def load_evidence(self, goal_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir(goal_id) / "evidence" / "evidence.jsonl")

    def append_evaluation(self, goal_id: str, evaluation: dict[str, Any]) -> None:
        path = self._dir(goal_id) / "evaluations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "goal_id": goal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **evaluation,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def load_evaluations(self, goal_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir(goal_id) / "evaluations.jsonl")

    def pause(self, goal_id: str) -> Goal:
        goal = self.load_goal(goal_id)
        goal.status = "paused"
        goal.summary = "目标已暂停。"
        self.save_goal(goal)
        self.append_event(goal_id, GoalEvent(event="goal_paused", goal_id=goal_id))
        return goal

    def resume(self, goal_id: str) -> Goal:
        goal = self.load_goal(goal_id)
        if goal.status == "paused":
            goal.status = "active"
            goal.summary = "目标已恢复。"
            self.save_goal(goal)
            self.append_event(goal_id, GoalEvent(event="goal_resumed", goal_id=goal_id))
        return goal

    def load_events(self, goal_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir(goal_id) / "events.jsonl")

    def list_artifacts(self, goal_id: str) -> list[str]:
        artifacts = self._dir(goal_id) / "artifacts"
        if not artifacts.exists():
            return []
        return [str(path) for path in sorted(artifacts.rglob("*")) if path.is_file()]

    def _dir(self, goal_id: str) -> Path:
        return self.goals_dir / goal_id


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(json.loads(line))
    return items


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    path.write_text(text, encoding="utf-8")


def _compact_evidence(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "task_id",
        "source",
        "title",
        "url",
        "summary",
        "content",
        "tool_id",
        "tool_name",
        "success",
        "risk",
        "permission",
        "created_at",
    }
    compact = {key: value for key, value in item.items() if key in allowed}
    for key in ("summary", "content"):
        value = compact.get(key)
        if isinstance(value, str) and len(value) > 1000:
            compact[key] = value[:1000] + "..."
    if not compact:
        compact = {"summary": str(item)[:1000]}
    return compact
