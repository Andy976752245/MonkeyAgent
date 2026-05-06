from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LearningDecision:
    should_create_candidate: bool
    repeat_count: int
    signature: str
    reason: str


class UsageMemory:
    def __init__(self, memory_dir: Path, repeat_threshold: int = 2) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.path = memory_dir / "_usage_observations.json"
        self.repeat_threshold = repeat_threshold

    def decide(
        self,
        question: str,
        task_type: str,
        candidate_type: str | None,
        stable_rule_candidate: bool,
        explicit_learning: bool = False,
    ) -> LearningDecision:
        signature = _signature(question, task_type, candidate_type)
        records = self._load()
        current = records.get(signature, {})
        repeat_count = int(current.get("count", 0)) + 1
        current.update(
            {
                "signature": signature,
                "task_type": task_type,
                "candidate_type": candidate_type,
                "count": repeat_count,
                "last_question": question,
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        records[signature] = current
        self._save(records)

        if stable_rule_candidate:
            return LearningDecision(
                True,
                repeat_count,
                signature,
                "stable_rule_candidate",
            )
        if explicit_learning:
            return LearningDecision(
                True,
                repeat_count,
                signature,
                "explicit_user_learning_intent",
            )
        if repeat_count >= self.repeat_threshold:
            return LearningDecision(
                True,
                repeat_count,
                signature,
                "repeated_similar_question",
            )
        return LearningDecision(
            False,
            repeat_count,
            signature,
            "one_off_observation_only",
        )

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, records: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _signature(question: str, task_type: str, candidate_type: str | None) -> str:
    normalized = question.lower()
    if task_type != "general":
        return f"{candidate_type or 'unknown'}:{task_type}"
    if "表达" in normalized and "方案" in normalized:
        return f"{candidate_type or 'unknown'}:方案表达"
    tokens = []
    for token in [
        "nba",
        "比赛",
        "赛程",
        "飞书",
        "天气",
        "搜索",
        "分析",
        "总结",
        "表达",
        "方案",
        "优化",
        "提升",
    ]:
        if token in normalized:
            tokens.append(token)
    if tokens:
        return f"{candidate_type or 'unknown'}:{','.join(tokens)}"
    compact = re.sub(r"\s+", "", normalized)
    return f"{candidate_type or 'unknown'}:{compact[:24]}"
