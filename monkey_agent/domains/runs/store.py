from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from monkey_agent.domains.runs.models import RunRecord, RunSummary


class RunStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        for kind in ("ask", "goals", "tools"):
            (self.runs_dir / kind).mkdir(parents=True, exist_ok=True)

    def record_ask(
        self,
        question: str,
        context: dict[str, Any] | None,
        result: dict[str, Any] | None,
        status: str | None = None,
        errors: list[str] | None = None,
    ) -> RunRecord:
        result = dict(result or {})
        record = self._record_from_result(
            run_type="ask",
            input_data={"question": question, "context": _compact(context or {})},
            result=result,
            status=status or _ask_status(result),
            errors=errors,
            summary=_ask_summary(result),
        )
        return self.save(record)

    def record_tool(
        self,
        question: str,
        context: dict[str, Any] | None,
        result: dict[str, Any],
    ) -> RunRecord:
        tool_builder = _compact_tool_builder(result.get("tool_builder"))
        status = "completed" if tool_builder.get("success") else "failed"
        tool_result = dict(result)
        if isinstance(tool_builder.get("evaluation"), dict):
            tool_result["evaluation"] = tool_builder["evaluation"]
        record = self._record_from_result(
            run_type="tool",
            input_data={"question": question, "context": _compact(context or {})},
            result=tool_result,
            status=status,
            errors=[str(tool_builder.get("error"))] if tool_builder.get("error") else None,
            summary=_tool_summary(tool_builder),
            tool_builder=tool_builder,
        )
        return self.save(record)

    def record_goal(
        self,
        result: dict[str, Any],
        input_data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        existing = self.get(run_id) if run_id else None
        input_payload = dict(existing.input if existing else {})
        input_payload.update(input_data or {})
        raw_result_path = input_payload.pop("_raw_result_path", None)
        created_at = existing.created_at if existing else _now()
        record = RunRecord(
            id=run_id or _new_run_id(),
            type="goal",
            status=str(result.get("status") or "active"),
            created_at=created_at,
            updated_at=_now(),
            input=_compact(input_payload),
            summary=str(result.get("summary") or result.get("answer") or ""),
            route=str(result.get("next_action") or ""),
            execution_path=[str(item) for item in result.get("execution_path", [])],
            classification=_goal_summary(result),
            matched_rules=[],
            matched_skills=[],
            tools=_goal_tools(result),
            memory_used=[],
            counterexamples_checked=[],
            tool_builder=_goal_tool_builder(result),
            evaluation=_goal_evaluation(result),
            learning_candidate_ids=_learning_ids(result),
            errors=_errors(result),
            answer_preview=_preview(result.get("answer")),
            raw_result_path=str(raw_result_path) if raw_result_path else None,
        )
        return self.save(record)

    def save(self, record: RunRecord) -> RunRecord:
        directory = self._type_dir(record.type)
        path = directory / f"{record.id}.json"
        record.updated_at = _now()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        return record

    def list(self, run_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        items = [RunSummary(**_summary_data(record)).to_dict() for record in self._records(run_type)]
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)[:limit]

    def latest(self, run_type: str | None = None) -> dict[str, Any] | None:
        records = sorted(self._records(run_type), key=lambda item: item.updated_at, reverse=True)
        return records[0].to_dict() if records else None

    def get(self, run_id: str | None) -> RunRecord | None:
        if not run_id:
            return None
        for kind in ("ask", "goals", "tools"):
            path = self.runs_dir / kind / f"{run_id}.json"
            if path.exists():
                return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return None

    def get_dict(self, run_id: str) -> dict[str, Any] | None:
        record = self.get(run_id)
        return record.to_dict() if record else None

    def latest_goal_run_id(self, goal_id: str) -> str | None:
        matches = [
            record
            for record in self._records("goal")
            if record.input.get("goal_id") == goal_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)[0].id

    def _record_from_result(
        self,
        run_type: str,
        input_data: dict[str, Any],
        result: dict[str, Any],
        status: str,
        summary: str,
        errors: list[str] | None = None,
        tool_builder: dict[str, Any] | None = None,
    ) -> RunRecord:
        return RunRecord(
            id=_new_run_id(),
            type=run_type,
            status=status,
            created_at=_now(),
            updated_at=_now(),
            input=_compact(input_data),
            summary=summary,
            route=str(result.get("route") or result.get("next_action") or ""),
            execution_path=[str(item) for item in result.get("execution_path", [])],
            classification=dict(result.get("classification") or {}),
            routing_policy=_compact(result.get("routing_policy") or {}),
            matched_rules=_compact_list(result.get("matched_rules")),
            matched_skills=_compact_list(result.get("matched_skills")),
            tools=_tools(result),
            memory_used=_compact_list(result.get("memory_used")),
            counterexamples_checked=_compact_list(result.get("counterexamples_checked")),
            tool_builder=tool_builder or _compact_tool_builder(result.get("tool_builder")),
            evaluation=_compact(result.get("evaluation") or {}),
            learning_candidate_ids=_learning_ids(result),
            errors=(errors or []) + _errors(result),
            answer_preview=_preview(result.get("answer")),
            raw_result_path=None,
        )

    def _records(self, run_type: str | None = None) -> list[RunRecord]:
        records: list[RunRecord] = []
        dirs = [self._type_dir(run_type)] if run_type else [
            self.runs_dir / "ask",
            self.runs_dir / "goals",
            self.runs_dir / "tools",
        ]
        for directory in dirs:
            if not directory.exists():
                continue
            for path in directory.glob("run_*.json"):
                try:
                    records.append(RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue
        return records

    def _type_dir(self, run_type: str | None) -> Path:
        mapping = {"ask": "ask", "goal": "goals", "tool": "tools", "goals": "goals", "tools": "tools"}
        if run_type not in mapping:
            raise ValueError("run type must be ask, goal, or tool")
        return self.runs_dir / mapping[run_type]


def _new_run_id() -> str:
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(value: Any, limit: int = 1000) -> str:
    text = "" if value is None else str(value)
    return text[:limit]


def _ask_status(result: dict[str, Any]) -> str:
    if result.get("route") == "need_more_info" or result.get("clarification_questions"):
        return "waiting_human"
    if result.get("errors") and not result.get("answer"):
        return "failed"
    return "completed"


def _ask_summary(result: dict[str, Any]) -> str:
    route = result.get("route") or "unknown"
    answer = _preview(result.get("answer"), 160)
    return f"Ask routed to {route}. {answer}".strip()


def _tool_summary(tool_builder: dict[str, Any]) -> str:
    stage = tool_builder.get("stage") or "tool_builder"
    tool_id = tool_builder.get("tool_id") or tool_builder.get("generated_tool_id") or ""
    status = "succeeded" if tool_builder.get("success") else "failed"
    return " ".join(item for item in [f"Tool builder {status} at {stage}.", str(tool_id)] if item)


def _summary_data(record: RunRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "summary": record.summary,
        "route": record.route,
        "answer_preview": record.answer_preview,
    }


def _tools(result: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in result.get("deterministic_results", []) or []:
        if not isinstance(item, dict):
            continue
        tool_id = item.get("source_tool") or item.get("tool_id")
        if tool_id:
            tools.append(
                {
                    "tool_id": str(tool_id),
                    "success": not bool(item.get("error")),
                    "source": "deterministic_result",
                }
            )
    exploration = result.get("exploration")
    if isinstance(exploration, dict) and exploration.get("source_tool"):
        tools.append(
            {
                "tool_id": str(exploration["source_tool"]),
                "success": bool(exploration.get("success", True)),
                "source": "exploration",
            }
        )
    tool_builder = _compact_tool_builder(result.get("tool_builder"))
    if tool_builder:
        tools.append(
            {
                "tool_id": str(tool_builder.get("tool_id") or tool_builder.get("generated_tool_id") or "tool_builder"),
                "success": bool(tool_builder.get("success")),
                "source": "tool_builder",
                "risk": tool_builder.get("risk"),
                "permission": tool_builder.get("permission"),
            }
        )
    return _dedupe_tools(tools)


def _goal_tools(result: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for task in result.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        output = task.get("output") or {}
        if not isinstance(output, dict):
            continue
        for item in output.get("tools", []) or []:
            if isinstance(item, dict):
                tools.append(_compact(item))
        tool_id = output.get("tool_id") or output.get("generated_tool_id")
        if tool_id:
            tools.append({"tool_id": str(tool_id), "source": "goal_task"})
    return _dedupe_tools(tools)


def _goal_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal_id": result.get("goal_id"),
        "thread_id": result.get("thread_id"),
        "checkpointed": bool(result.get("checkpointed")),
        "checkpoint_backend": result.get("checkpoint_backend"),
        "last_checkpoint": result.get("last_checkpoint"),
        "resume_required": bool(result.get("resume_required")),
        "interrupted": bool(result.get("interrupted")),
        "current_task": _compact(result.get("current_task") or {}),
        "event_count": len(result.get("events", []) or []),
        "evaluation_count": len(result.get("evaluations", []) or []),
        "requires_confirmation": bool(result.get("requires_confirmation")),
        "plan_version": result.get("plan_version"),
        "revision_count": result.get("revision_count"),
    }


def _goal_tool_builder(result: dict[str, Any]) -> dict[str, Any]:
    for task in result.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if (task.get("executor") or task.get("type")) != "tool_builder":
            continue
        output = task.get("output")
        if isinstance(output, dict):
            return _compact_tool_builder(output.get("tool_builder") or output)
    return {}


def _goal_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    evaluations = result.get("evaluations")
    if isinstance(evaluations, list) and evaluations:
        latest = evaluations[-1]
        if isinstance(latest, dict):
            return _compact(latest)
    evaluation = result.get("last_evaluation") or result.get("evaluation")
    return _compact(evaluation) if isinstance(evaluation, dict) else {}


def _compact_tool_builder(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "stage",
        "success",
        "error",
        "tool_id",
        "generated_tool_id",
        "permission",
        "risk",
        "read_only",
        "source_question",
        "candidate_id",
        "learning_candidate_id",
        "safety",
        "test",
        "warnings",
        "path",
        "metadata_path",
        "metadata",
        "safety_report",
        "test_result",
        "spec",
        "evaluation",
    }
    compact = {key: _compact(value[key]) for key in allowed if key in value}
    if "code" in compact:
        compact.pop("code", None)
    if isinstance(compact.get("safety_report"), dict):
        compact["safety_report"] = _scrub_safety_report(compact["safety_report"])
    if isinstance(compact.get("evaluation"), dict):
        compact["evaluation"] = _scrub_tool_evaluation(compact["evaluation"])
    return compact


def _scrub_safety_report(report: dict[str, Any]) -> dict[str, Any]:
    scrubbed = dict(report)
    errors = []
    for error in scrubbed.get("errors", []) or []:
        text = str(error)
        if text.startswith("banned_call:"):
            errors.append("banned_call:<redacted>")
        elif text.startswith("banned_attribute:"):
            errors.append("banned_attribute:<redacted>")
        elif text.startswith("banned_import:"):
            errors.append("banned_import:<redacted>")
        else:
            errors.append(text)
    if errors:
        scrubbed["errors"] = sorted(set(errors))
    return scrubbed


def _scrub_tool_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    scrubbed = dict(evaluation)
    checks = []
    for check in scrubbed.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        item = dict(check)
        item.pop("data", None)
        checks.append(item)
    if checks:
        scrubbed["checks"] = checks
    return scrubbed


def _learning_ids(result: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("learning_candidate_id", "adopted_candidate_id"):
        if result.get(key):
            ids.append(str(result[key]))
    for item in result.get("learning_candidate_ids", []) or []:
        if item:
            ids.append(str(item))
    exploration = result.get("exploration")
    if isinstance(exploration, dict) and exploration.get("candidate_id"):
        ids.append(str(exploration["candidate_id"]))
    tool_builder = result.get("tool_builder")
    if isinstance(tool_builder, dict):
        for key in ("candidate_id", "learning_candidate_id"):
            if tool_builder.get(key):
                ids.append(str(tool_builder[key]))
    for task in result.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        output = task.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("learning_candidate_id"):
            ids.append(str(output["learning_candidate_id"]))
        ids.extend(str(item) for item in output.get("learning_candidate_ids", []) if item)
    return list(dict.fromkeys(ids))


def _errors(result: dict[str, Any]) -> list[str]:
    return [str(item) for item in result.get("errors", []) or [] if item]


def _compact_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_compact(item) for item in value if isinstance(item, dict)]


def _compact(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return _preview(value, 300)
    if isinstance(value, dict):
        return {
            str(key): _compact(item, depth + 1)
            for key, item in value.items()
            if str(key) not in {"prompt", "messages", "code", "handler_code"}
        }
    if isinstance(value, list):
        return [_compact(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]


def _dedupe_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in tools:
        key = (str(item.get("tool_id") or ""), str(item.get("source") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
