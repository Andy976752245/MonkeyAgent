from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from monkey_agent.domains.tools import Tool, ToolExecutionResult


@dataclass(frozen=True)
class GeneratedToolLoadResult:
    tool: Tool | None
    error: str | None = None


class GeneratedToolStore:
    def __init__(
        self,
        tools_dir: Path,
        registry_path: Path,
    ) -> None:
        self.tools_dir = tools_dir
        self.registry_path = registry_path
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        init_path = self.tools_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text('"""MonkeyAgent generated tools."""\n', encoding="utf-8")
        if not self.registry_path.exists():
            self._write_registry([])

    def list(self) -> list[dict[str, Any]]:
        return self._read_registry()

    def get(self, tool_id: str) -> dict[str, Any] | None:
        for item in self._read_registry():
            if item.get("id") == tool_id:
                return item
        return None

    def enabled_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for item in self._read_registry():
            if not item.get("enabled"):
                continue
            loaded = self.load(item["id"])
            if loaded.tool is not None:
                tools.append(loaded.tool)
        return tools

    def load(self, tool_id: str) -> GeneratedToolLoadResult:
        item = self.get(tool_id)
        if not item:
            return GeneratedToolLoadResult(None, f"generated tool not found: {tool_id}")
        path = Path(str(item.get("module_path") or ""))
        if not path.is_absolute():
            path = self.tools_dir / path
        if not path.exists():
            return GeneratedToolLoadResult(None, f"generated tool module missing: {path}")
        try:
            module_name = f"monkey_agent_generated_{tool_id}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return GeneratedToolLoadResult(None, f"cannot import generated tool: {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tool_class = getattr(module, "TOOL_CLASS", None)
            if tool_class is None:
                class_name = str(item.get("class_name") or "GeneratedTool")
                tool_class = getattr(module, class_name, None)
            if tool_class is None:
                return GeneratedToolLoadResult(None, "TOOL_CLASS is missing")
            tool = tool_class()
            return GeneratedToolLoadResult(tool)
        except Exception as exc:  # noqa: BLE001 - generated code boundary
            return GeneratedToolLoadResult(None, str(exc))

    def save(
        self,
        tool_id: str,
        code: str,
        metadata: dict[str, Any],
        enabled: bool,
    ) -> dict[str, Any]:
        module_name = _safe_module_name(tool_id)
        module_path = self.tools_dir / f"{module_name}.py"
        module_path.write_text(code, encoding="utf-8")
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "id": tool_id,
            "enabled": enabled,
            "module_path": module_path.name,
            "created_at": now,
            "updated_at": now,
            **metadata,
        }
        items = [entry for entry in self._read_registry() if entry.get("id") != tool_id]
        items.append(item)
        self._write_registry(sorted(items, key=lambda entry: str(entry.get("id"))))
        return item

    def set_enabled(self, tool_id: str, enabled: bool) -> dict[str, Any]:
        items = self._read_registry()
        for item in items:
            if item.get("id") != tool_id:
                continue
            item["enabled"] = enabled
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_registry(items)
            return item
        raise FileNotFoundError(f"generated tool not found: {tool_id}")

    def test(self, tool_id: str, question: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        item = self.get(tool_id)
        if not item:
            raise FileNotFoundError(f"generated tool not found: {tool_id}")
        loaded = self.load(tool_id)
        if loaded.tool is None:
            result = {"success": False, "error": loaded.error}
        else:
            try:
                output = loaded.tool.execute(
                    question or str(item.get("source_question") or "dry-run"),
                    {"dry_run": True, **(context or {})},
                )
                result = _result_to_dict(output)
            except Exception as exc:  # noqa: BLE001 - generated code boundary
                result = {"success": False, "error": str(exc)}
        item["last_test_result"] = result
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        items = [
            item if entry.get("id") == tool_id else entry for entry in self._read_registry()
        ]
        self._write_registry(items)
        return result

    def _read_registry(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or []
        if isinstance(data, dict):
            data = data.get("tools", [])
        return [dict(item) for item in data if isinstance(item, dict)]

    def _write_registry(self, items: list[dict[str, Any]]) -> None:
        self.registry_path.write_text(
            yaml.safe_dump(items, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _safe_module_name(tool_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in tool_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"tool_{cleaned}"
    return cleaned


def _result_to_dict(result: ToolExecutionResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "content": result.content,
        "data": result.data,
        "error": result.error,
        "permission": result.permission.value,
        "risk": result.risk.value,
        "read_only": result.read_only,
    }
