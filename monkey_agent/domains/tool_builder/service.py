from __future__ import annotations

import hashlib
import importlib.util
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monkey_agent.domains.tools.generated import GeneratedToolStore
from monkey_agent.domains.models.bailian import ChatModel
from monkey_agent.domains.tool_builder.safety import ToolCodeSafetyValidator
from monkey_agent.domains.tools import Permission, Tool, ToolExecutionResult, ToolRisk


TOOL_BUILDER_HINTS = (
    "API",
    "接口",
    "接入",
    "工具",
    "生成工具",
    "新增工具",
    "创建工具",
    "自动化",
    "消息",
    "机器人",
    "webhook",
    "Webhook",
    "转换",
    "提取",
    "抓取",
    "同步",
    "对接",
)

WRITE_HINTS = ("发送", "写入", "创建", "删除", "更新", "同步", "通知", "推送", "发一条")
EXTERNAL_WRITE_TARGET_HINTS = (
    "飞书",
    "Feishu",
    "Lark",
    "机器人",
    "webhook",
    "Webhook",
    "API",
    "接口",
    "消息",
    "通知",
)


@dataclass(frozen=True)
class ToolBuildResult:
    success: bool
    stage: str
    spec: dict[str, Any] | None = None
    draft: dict[str, Any] | None = None
    safety_report: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tool: Tool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "stage": self.stage,
            "spec": self.spec or {},
            "draft": _redact_code(self.draft or {}),
            "safety_report": self.safety_report or {},
            "test_result": self.test_result or {},
            "metadata": self.metadata or {},
            "error": self.error,
        }


class ToolBuilderService:
    def __init__(
        self,
        chat_model: ChatModel,
        generated_store: GeneratedToolStore,
        local_root: Path,
    ) -> None:
        self.chat_model = chat_model
        self.generated_store = generated_store
        self.local_root = local_root
        self.validator = ToolCodeSafetyValidator()

    def should_build(self, question: str, context: dict[str, Any]) -> bool:
        if context.get("disable_tool_builder"):
            return False
        if context.get("force_tool_builder"):
            return True
        return _explicit_tool_build_goal(question)

    def discover_tool_spec(
        self,
        question: str,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        context = state.get("context", {})
        if not self.should_build(question, context):
            return None
        is_write = _is_external_write_goal(question)
        kind = "http_api" if _looks_like_http_api(question) else "python_function"
        permission = "confirm" if is_write else "auto"
        risk = "medium" if is_write else "low"
        keywords = _keywords_from_question(question)
        return {
            "tool_id": _tool_id(question),
            "name": _tool_name(question, kind),
            "description": "由 MonkeyAgent 根据问题、公开资料和本地 Tool 协议自动生成。",
            "kind": kind,
            "permission": permission,
            "risk": risk,
            "read_only": not is_write,
            "learn_policy": "rule",
            "keywords": keywords,
            "source_question": question,
            "local_code_context": _local_code_context(self.local_root),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def draft_tool_code(
        self,
        question: str,
        spec: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = {
            "public_evidence": context.get("public_evidence", []),
            "local_code_context": spec.get("local_code_context", {}),
        }
        try:
            draft = self.chat_model.draft_tool_builder(question, spec, evidence, context)
        except Exception as exc:  # noqa: BLE001 - model boundary
            draft = {
                "tool_id": spec["tool_id"],
                "name": spec["name"],
                "description": spec["description"],
                "kind": spec["kind"],
                "permission": spec["permission"],
                "risk": spec["risk"],
                "read_only": spec["read_only"],
                "learn_policy": spec["learn_policy"],
                "keywords": spec["keywords"],
                "class_name": "GeneratedTool",
                "draft_fallback_reason": f"model_error:{exc}",
            }
        draft.setdefault("tool_id", spec["tool_id"])
        draft.setdefault("name", spec["name"])
        draft.setdefault("description", spec["description"])
        draft.setdefault("kind", spec["kind"])
        draft.setdefault("permission", spec["permission"])
        draft.setdefault("risk", spec["risk"])
        draft.setdefault("read_only", spec["read_only"])
        draft.setdefault("learn_policy", spec["learn_policy"])
        draft.setdefault("keywords", spec["keywords"])
        draft.setdefault("class_name", "GeneratedTool")
        if not draft.get("code"):
            draft["code"] = _fallback_tool_code(question, spec, draft, evidence)
            draft.setdefault("draft_fallback_reason", "model_missing_code")
        return draft

    def validate_tool_code(self, draft: dict[str, Any]) -> dict[str, Any]:
        code = str(draft.get("code") or "")
        report = self.validator.validate(code).to_dict()
        if not code:
            report["passed"] = False
            report.setdefault("errors", []).append("missing_code")
        return report

    def sandbox_test_tool(
        self,
        question: str,
        draft: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        code = str(draft.get("code") or "")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "generated_tool.py"
            path.write_text(code, encoding="utf-8")
            loaded = _load_tool_from_path(path, str(draft.get("class_name") or "GeneratedTool"))
            if loaded["tool"] is None:
                return {"success": False, "error": loaded["error"]}
            tool = loaded["tool"]
            protocol_errors = _protocol_errors(tool)
            if protocol_errors:
                return {"success": False, "error": "protocol_error", "details": protocol_errors}
            try:
                output = tool.execute(
                    question,
                    {"dry_run": True, **dict(draft.get("test_context") or {}), **context},
                )
            except Exception as exc:  # noqa: BLE001 - generated code boundary
                return {"success": False, "error": str(exc)}
            return _tool_result_to_dict(output)

    def register_generated_tool(
        self,
        question: str,
        spec: dict[str, Any],
        draft: dict[str, Any],
        test_result: dict[str, Any],
        safety_report: dict[str, Any],
    ) -> ToolBuildResult:
        permission = _permission_value(draft.get("permission") or spec.get("permission"))
        risk = _risk_value(draft.get("risk") or spec.get("risk"))
        read_only = bool(draft.get("read_only", spec.get("read_only", True)))
        auto_enable = (
            permission == Permission.AUTO.value
            and risk == ToolRisk.LOW.value
            and read_only
            and bool(test_result.get("success"))
            and bool(safety_report.get("passed"))
        )
        metadata = {
            "name": draft.get("name") or spec.get("name"),
            "description": draft.get("description") or spec.get("description"),
            "kind": draft.get("kind") or spec.get("kind"),
            "permission": permission,
            "risk": risk,
            "read_only": read_only,
            "learn_policy": draft.get("learn_policy") or spec.get("learn_policy") or "rule",
            "keywords": draft.get("keywords") or spec.get("keywords") or [],
            "class_name": draft.get("class_name") or "GeneratedTool",
            "source_question": question,
            "source": "tool_builder",
            "auto_enabled": auto_enable,
            "safety_report": safety_report,
            "last_test_result": test_result,
            "version": "0.1.0",
        }
        saved = self.generated_store.save(
            tool_id=str(draft.get("tool_id") or spec["tool_id"]),
            code=str(draft["code"]),
            metadata=metadata,
            enabled=auto_enable or permission == Permission.CONFIRM.value,
        )
        loaded = self.generated_store.load(str(saved["id"]))
        return ToolBuildResult(
            success=loaded.tool is not None,
            stage="register_generated_tool",
            spec=spec,
            draft=draft,
            safety_report=safety_report,
            test_result=test_result,
            metadata=saved,
            tool=loaded.tool,
            error=loaded.error,
        )

    def build(
        self,
        question: str,
        state: dict[str, Any],
    ) -> ToolBuildResult:
        spec = self.discover_tool_spec(question, state)
        if spec is None:
            return ToolBuildResult(False, "discover_tool_spec", error="not_a_tool_builder_candidate")
        draft = self.draft_tool_code(question, spec, state.get("context", {}))
        safety = self.validate_tool_code(draft)
        if not safety.get("passed"):
            return ToolBuildResult(False, "validate_tool_code", spec, draft, safety, error="unsafe_code")
        test_result = self.sandbox_test_tool(question, draft, state.get("context", {}))
        if not test_result.get("success"):
            return ToolBuildResult(False, "sandbox_test_tool", spec, draft, safety, test_result, error="test_failed")
        return self.register_generated_tool(question, spec, draft, test_result, safety)


def _load_tool_from_path(path: Path, class_name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.spec_from_file_location("monkey_agent_tool_builder_sandbox", path)
        if spec is None or spec.loader is None:
            return {"tool": None, "error": "cannot_import_module"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tool_class = getattr(module, "TOOL_CLASS", None) or getattr(module, class_name, None)
        if tool_class is None:
            return {"tool": None, "error": "TOOL_CLASS is missing"}
        return {"tool": tool_class(), "error": None}
    except Exception as exc:  # noqa: BLE001 - generated code boundary
        return {"tool": None, "error": str(exc)}


def _protocol_errors(tool: Any) -> list[str]:
    errors = []
    for attr in [
        "id",
        "name",
        "description",
        "input_schema",
        "output_schema",
        "permission",
        "risk",
        "read_only",
        "learn_policy",
        "can_handle",
        "execute",
    ]:
        if not hasattr(tool, attr):
            errors.append(f"missing:{attr}")
    return errors


def _tool_result_to_dict(result: ToolExecutionResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "content": result.content,
        "data": result.data,
        "error": result.error,
        "permission": result.permission.value,
        "risk": result.risk.value,
        "read_only": result.read_only,
    }


def _looks_like_http_api(question: str) -> bool:
    return any(hint in question for hint in ("API", "接口", "接入", "webhook", "Webhook", "机器人", "飞书"))


def _explicit_tool_build_goal(question: str) -> bool:
    text = question.strip()
    if any(hint in text for hint in TOOL_BUILDER_HINTS):
        return True
    if any(phrase in text for phrase in ("生成一个", "做一个", "开发一个", "实现一个", "增加一个", "新增一个")):
        return True
    if "天气" in text:
        return True
    return _is_external_write_goal(text)


def _is_external_write_goal(question: str) -> bool:
    has_write = any(hint in question for hint in WRITE_HINTS)
    has_external_target = any(hint in question for hint in EXTERNAL_WRITE_TARGET_HINTS)
    return has_write and has_external_target


def _tool_id(question: str) -> str:
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    prefix = "generated_api_tool" if _looks_like_http_api(question) else "generated_function_tool"
    return f"{prefix}_{digest}"


def _tool_name(question: str, kind: str) -> str:
    if "飞书" in question:
        return "自动生成飞书能力工具"
    if "天气" in question:
        return "自动生成天气查询工具"
    if kind == "http_api":
        return "自动生成 API 工具"
    return "自动生成 Python 函数工具"


def _keywords_from_question(question: str) -> list[str]:
    keywords = [hint for hint in TOOL_BUILDER_HINTS if hint in question]
    if "天气" in question:
        keywords.extend(["天气", "气温", "降水", "风速"])
    if "飞书" in question:
        keywords.extend(["飞书", "消息", "发送"])
    return list(dict.fromkeys(keywords))[:8] or [question[:12]]


def _local_code_context(root: Path) -> dict[str, Any]:
    relevant = [
        "tools/protocol.py",
        "tools/registry.py",
        "capabilities/weather.py",
        "capabilities/feishu.py",
        "capabilities/web_search.py",
    ]
    existing = []
    for rel in relevant:
        path = root / rel
        if path.exists():
            existing.append(rel)
    return {
        "tool_protocol": "Tool protocol requires schema, permission, risk, can_handle, execute.",
        "reference_files": existing,
    }


def _permission_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return raw if raw in {item.value for item in Permission} else Permission.CONFIRM.value


def _risk_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return raw if raw in {item.value for item in ToolRisk} else ToolRisk.MEDIUM.value


def _redact_code(draft: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(draft)
    code = redacted.get("code")
    if code:
        redacted["code"] = f"<{len(str(code).splitlines())} lines>"
    return redacted


def _fallback_tool_code(
    question: str,
    spec: dict[str, Any],
    draft: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    permission = _permission_value(draft.get("permission") or spec.get("permission"))
    risk = _risk_value(draft.get("risk") or spec.get("risk"))
    read_only = bool(draft.get("read_only", spec.get("read_only", True)))
    keywords = [str(item) for item in (draft.get("keywords") or spec.get("keywords") or [])][:8]
    if not keywords:
        keywords = [question[:12]]
    tool_id = str(draft.get("tool_id") or spec["tool_id"])
    name = str(draft.get("name") or spec["name"])
    description = str(draft.get("description") or spec["description"])
    learn_policy = str(draft.get("learn_policy") or spec.get("learn_policy") or "rule")
    evidence_count = len(evidence.get("public_evidence", []) or [])
    content = (
        "已生成只读 dry-run 工具。该工具先沉淀为可复用能力骨架；"
        "接入真实数据源、鉴权和失败兜底后，可升级为正式查询工具。"
    )
    return f'''from __future__ import annotations

from typing import Any

from monkey_agent.domains.tools import Permission, ToolExecutionResult, ToolRisk, ToolSchema


class GeneratedTool:
    id = {tool_id!r}
    name = {name!r}
    description = {description!r}
    input_schema = ToolSchema(required=[], properties={{"dry_run": "是否仅执行安全演练"}})
    output_schema = ToolSchema(required=["content"], properties={{"content": "工具执行摘要"}})
    permission = Permission.{permission.upper()}
    risk = ToolRisk.{risk.upper()}
    read_only = {read_only!r}
    learn_policy = {learn_policy!r}
    keywords = {keywords!r}

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        if context.get("tool_id") == self.id:
            return True
        return any(keyword and keyword in question for keyword in self.keywords)

    def execute(self, question: str, context: dict[str, Any]) -> ToolExecutionResult:
        dry_run = bool(context.get("dry_run", True))
        return ToolExecutionResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=True,
            candidate_type="rule",
            content={content!r},
            data={{
                "question": question,
                "dry_run": dry_run,
                "generated": True,
                "fallback_generated": True,
                "keywords": self.keywords,
                "evidence_count": {evidence_count},
                "next_review": [
                    "确认真实数据源/API",
                    "补充输入输出 schema",
                    "补充失败兜底与测试样例"
                ],
            }},
            permission=self.permission,
            risk=self.risk,
            read_only=self.read_only,
        )


TOOL_CLASS = GeneratedTool
'''
