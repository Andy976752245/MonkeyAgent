from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


RULE_HINTS = ("公式", "计算", "规则", "口径", "必须", "不得", "不能", "优先", "图表")
MEMORY_HINTS = ("我喜欢", "我偏好", "以后", "默认", "习惯", "我的")
COUNTEREXAMPLE_HINTS = ("错误", "反例", "失败", "不应该", "不要这样", "错在")


class ReviewStore:
    def __init__(
        self,
        pending_dir: Path,
        rules_dir: Path,
        skills_dir: Path,
        memory_dir: Path,
        counterexamples_dir: Path,
    ) -> None:
        self.pending_dir = pending_dir
        self.rules_dir = rules_dir
        self.skills_dir = skills_dir
        self.memory_dir = memory_dir
        self.counterexamples_dir = counterexamples_dir
        for kind in ("rules", "skills", "memory", "counterexamples"):
            (pending_dir / kind).mkdir(parents=True, exist_ok=True)
        rules_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)
        memory_dir.mkdir(parents=True, exist_ok=True)
        counterexamples_dir.mkdir(parents=True, exist_ok=True)

    def list_pending(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for kind in ("rules", "skills", "memory", "counterexamples"):
            for path in sorted((self.pending_dir / kind).glob("*.yaml")):
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                data["_path"] = str(path)
                data["candidate_kind"] = _singular(kind)
                items.append(data)
        return items

    def latest_pending(self) -> dict[str, Any] | None:
        items = self.list_pending()
        if not items:
            return None
        return max(items, key=lambda item: Path(str(item["_path"])).stat().st_mtime)

    def create_candidate(
        self,
        question: str,
        feedback: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        kind = self._classify_candidate(feedback)
        candidate_id = f"{_singular(kind)}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
        data = self._candidate_metadata(
            self._candidate_payload(candidate_id, kind, question, feedback, context or {})
        )
        path = self.pending_dir / kind / f"{candidate_id}.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return candidate_id

    def create_exploration_candidate(
        self,
        question: str,
        task_type: str,
        intent_keywords: list[str],
        context: dict[str, Any] | None = None,
        llm_draft: dict[str, Any] | None = None,
        preferred_kind: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        kind = _plural(preferred_kind) if preferred_kind else self._classify_exploration_kind(question, task_type)
        candidate_id = f"{_singular(kind)}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
        data = self._exploration_payload(
            candidate_id,
            kind,
            question,
            task_type,
            intent_keywords,
            context or {},
            llm_draft or {},
        )
        data = self._candidate_metadata(data)
        path = self.pending_dir / kind / f"{candidate_id}.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return candidate_id, data

    def create_capability_candidate(
        self,
        question: str,
        task_type: str,
        intent_keywords: list[str],
        tool_result: Any,
        context: dict[str, Any] | None = None,
        llm_draft: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        candidate_type = tool_result.candidate_type
        if not candidate_type:
            candidate_type = "rule" if tool_result.stable_rule_candidate else "skill"
        kind = _plural(candidate_type)
        candidate_id = f"{candidate_type}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
        if candidate_type == "skill":
            data = self._capability_skill_payload(
                candidate_id,
                question,
                task_type,
                intent_keywords,
                tool_result,
                context or {},
                llm_draft or {},
            )
            data = self._candidate_metadata(data)
            path = self.pending_dir / "skills" / f"{candidate_id}.yaml"
            path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return candidate_id, data

        data = {
            "id": candidate_id,
            "candidate_type": "rule",
            "status": "pending_review",
            "type": "api_tool",
            "name": f"待审核能力沉淀：{tool_result.tool_name}",
            "intent": intent_keywords,
            "keywords": _extract_keywords(question)
            or _extract_keywords(str(tool_result.data)),
            "priority": 80,
            "handler": tool_result.handler_name or tool_result.tool_id,
            "rule": (
                f"当用户提出同类问题时，优先调用已验证能力 {tool_result.tool_name} "
                "获取确定结果；不得由大模型编造实时或外部事实。"
            ),
            "source_question": question,
            "source_tool": tool_result.tool_id,
            "stability_decision": "stable_existing_capability",
            "public_support": tool_result.data.get("public_support", False),
            "docs_url": tool_result.data.get("docs_url"),
            "endpoint": tool_result.data.get("endpoint"),
            "can_generate_rule_code": bool(tool_result.handler_code_proposal),
            "handler_code_proposal": tool_result.handler_code_proposal or "",
            "sample_result": tool_result.data,
            "sample_answer": tool_result.content,
            "sample_error": tool_result.error,
            "code_promotion_policy": (
                "工具已被探索调用。人工审核适用范围、输入输出、失败兜底和测试后，"
                "可以沉淀为正式 Rule。若样例调用失败，需要先修复配置或网络。"
            ),
            "context": context or {},
        }
        data = _generalize_capability_candidate(data, tool_result)
        data = _merge_llm_draft(data, llm_draft or {})
        data = self._candidate_metadata(data)
        path = self.pending_dir / "rules" / f"{candidate_id}.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return candidate_id, data

    def approve(self, candidate_id: str) -> Path:
        source = self._find_candidate(candidate_id)
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        kind = _plural(str(data.get("candidate_type", "skill")))
        target_dir = self._target_dir(kind)
        promoted = self._promote_payload(data)
        target = target_dir / f"{promoted['id']}.yaml"
        target.write_text(
            yaml.safe_dump(promoted, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        source.unlink()
        return target

    def _candidate_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        item = dict(data)
        context = item.get("context")
        if isinstance(context, dict):
            evaluation = context.pop("_evaluation", None)
            if evaluation:
                item["evaluation"] = evaluation
        return item

    def reject(self, candidate_id: str) -> Path:
        source = self._find_candidate(candidate_id)
        rejected_dir = self.pending_dir / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        target = rejected_dir / source.name
        shutil.move(str(source), str(target))
        return target

    def _find_candidate(self, candidate_id: str) -> Path:
        for kind in ("rules", "skills", "memory", "counterexamples"):
            path = self.pending_dir / kind / f"{candidate_id}.yaml"
            if path.exists():
                return path
        raise FileNotFoundError(f"candidate not found: {candidate_id}")

    def _classify_candidate(self, feedback: str) -> str:
        if any(hint in feedback for hint in COUNTEREXAMPLE_HINTS):
            return "counterexamples"
        if any(hint in feedback for hint in MEMORY_HINTS):
            return "memory"
        if any(hint in feedback for hint in RULE_HINTS):
            return "rules"
        return "skills"

    def _classify_exploration_kind(self, question: str, task_type: str) -> str:
        if any(hint in question for hint in MEMORY_HINTS):
            return "memory"
        api_hints = ("天气", "实时", "查询", "搜索", "API", "接口", "今天", "当日")
        rule_hints = ("计算", "公式", "规则", "口径", "SQL")
        if any(hint in question for hint in api_hints + rule_hints):
            return "rules"
        if task_type in {"general", "analysis"}:
            return "skills"
        return "skills"

    def _target_dir(self, kind: str) -> Path:
        if kind == "rules":
            return self.rules_dir
        if kind == "skills":
            return self.skills_dir
        if kind == "memory":
            return self.memory_dir
        if kind == "counterexamples":
            return self.counterexamples_dir
        raise ValueError(f"unknown candidate kind: {kind}")

    def _candidate_payload(
        self,
        candidate_id: str,
        kind: str,
        question: str,
        feedback: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if kind == "rules":
            return {
                "id": candidate_id,
                "candidate_type": "rule",
                "status": "pending_review",
                "type": "business_definition",
                "name": "待审核沉淀规则",
                "intent": [],
                "keywords": _extract_keywords(question + " " + feedback),
                "priority": 50,
                "handler": "pass_through",
                "rule": feedback,
                "source_question": question,
                "source_feedback": feedback,
                "context": context,
            }
        if kind == "memory":
            return {
                "id": candidate_id,
                "candidate_type": "memory",
                "status": "pending_review",
                "name": "待审核用户偏好",
                "keywords": _extract_keywords(question + " " + feedback),
                "preference": feedback,
                "source_question": question,
                "context": context,
            }
        if kind == "counterexamples":
            return {
                "id": candidate_id,
                "candidate_type": "counterexample",
                "status": "pending_review",
                "name": "待审核错误案例",
                "keywords": _extract_keywords(question + " " + feedback),
                "bad_case": question,
                "correction": feedback,
                "context": context,
            }
        return {
            "id": candidate_id,
            "candidate_type": "skill",
            "status": "pending_review",
            "name": "待审核技能",
            "description": feedback[:120],
            "task_types": [],
            "keywords": _extract_keywords(question + " " + feedback),
            "priority": 50,
            "prompt": feedback,
            "examples": [{"question": question, "feedback": feedback}],
            "context": context,
            "version": "0.1.0",
        }

    def _exploration_payload(
        self,
        candidate_id: str,
        kind: str,
        question: str,
        task_type: str,
        intent_keywords: list[str],
        context: dict[str, Any],
        llm_draft: dict[str, Any],
    ) -> dict[str, Any]:
        keywords = _extract_keywords(question)
        if kind == "rules":
            is_weather = "天气" in question
            proposed_handler = "weather_query" if is_weather else "custom_tool_rule"
            data = {
                "id": candidate_id,
                "candidate_type": "rule",
                "status": "pending_review",
                "type": "api_tool" if is_weather else "tool_or_rule",
                "name": "待审核外部查询能力" if is_weather else "待审核确定性执行能力",
                "intent": intent_keywords,
                "keywords": keywords or ["查询"],
                "priority": 70,
                "handler": proposed_handler,
                "rule": (
                    "当用户询问实时天气时，应调用天气 API 或工具函数获取实时数据，"
                    "不得由大模型编造天气。"
                    if is_weather
                    else "该问题需要沉淀为确定性 Rule、SQL、API 或工具函数后执行。"
                ),
                "stability_decision": "stable_code_candidate",
                "can_generate_rule_code": True,
                "proposed_handler_name": proposed_handler,
                "handler_code_proposal": _handler_code_proposal(proposed_handler),
                "code_promotion_policy": (
                    "该代码只是待审核草案。人工确认 API/SQL/工具配置、输入输出结构、"
                    "异常兜底和测试后，才能写入正式 handler 并启用。"
                ),
                "source_question": question,
                "exploration_reason": "当前未命中已沉淀 Rules 或 Skills，系统自动发现能力缺口。",
                "required_human_review": [
                    "确认业务意图和适用范围",
                    "确认是否需要新增 Python handler、SQL、API 或工具函数",
                    "确认输入字段、输出结构和失败兜底",
                ],
                "context": context,
            }
            return _merge_llm_draft(data, llm_draft)
        if kind == "memory":
            return {
                "id": candidate_id,
                "candidate_type": "memory",
                "status": "pending_review",
                "name": "待审核用户操作习惯",
                "keywords": _extract_keywords(question),
                "preference": question,
                "source_question": question,
                "stability_decision": "user_preference",
                "fallback_reason": "该内容不适合沉淀为稳定代码，适合保存为用户 Memory。",
                "context": context,
            }
        data = {
            "id": candidate_id,
            "candidate_type": "skill",
            "status": "pending_review",
            "name": "待审核探索 Skill",
            "description": "当前问题未命中 Rules/Skills，建议沉淀为可复用 Skill。",
            "task_types": [task_type],
            "keywords": keywords,
            "priority": 50,
            "stability_decision": "unstable_code_candidate",
            "can_generate_rule_code": False,
            "fallback_reason": (
                "当前信息不足以生成稳定 Rule 代码；先沉淀为 Skill，后续根据用户确认、"
                "反例和重复使用情况再升级为 Rule。"
            ),
            "prompt": (
                "当遇到类似问题时，先澄清目标、输入数据、输出格式和验收标准；"
                "不得编造缺失事实。"
            ),
            "examples": [{"question": question, "context": context}],
            "version": "0.1.0",
        }
        return _merge_llm_draft(data, llm_draft)

    def _capability_skill_payload(
        self,
        candidate_id: str,
        question: str,
        task_type: str,
        intent_keywords: list[str],
        tool_result: Any,
        context: dict[str, Any],
        llm_draft: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = tool_result.public_evidence or tool_result.data.get("results", [])
        data = {
            "id": candidate_id,
            "candidate_type": "skill",
            "status": "pending_review",
            "name": f"待审核公开信息 Skill：{tool_result.tool_name}",
            "description": "基于公开网络搜索或公开资料形成的可复用处理方法。",
            "task_types": [task_type],
            "intent": intent_keywords,
            "keywords": _extract_keywords(question + " " + str(tool_result.data)),
            "priority": 50,
            "stability_decision": "public_evidence_skill_candidate",
            "can_generate_rule_code": False,
            "fallback_reason": (
                "公开信息可支持回答或方法沉淀，但不构成稳定可执行代码 Rule。"
            ),
            "prompt": (
                "基于公开搜索结果回答同类问题时，先列出可验证来源，"
                "再给出结论；对实时性或无法验证部分明确说明不确定性。"
            ),
            "public_evidence": evidence,
            "sample_answer": tool_result.content,
            "source_question": question,
            "source_tool": tool_result.tool_id,
            "context": context,
            "version": "0.1.0",
        }
        return _merge_llm_draft(data, llm_draft)

    def _promote_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        promoted = dict(data)
        promoted.pop("candidate_type", None)
        promoted.pop("_path", None)
        promoted.pop("candidate_kind", None)
        promoted = _generalize_promoted_candidate(promoted)
        promoted["status"] = "active"
        promoted["source"] = "reviewed_learning"
        if promoted.get("type") == "api_tool" and promoted.get("source_tool"):
            promoted["handler"] = "capability_tool"
            promoted["capability_tool_id"] = promoted["source_tool"]
        return promoted


def _extract_keywords(text: str) -> list[str]:
    candidates = []
    for token in [
        "趋势",
        "月度",
        "周报",
        "月报",
        "总结",
        "摘要",
        "格式",
        "晨会",
        "环比",
        "同比",
        "图表",
        "公式",
        "百分比",
        "计算",
        "天气",
        "查询",
        "实时",
        "API",
        "飞书",
        "消息",
        "发送",
        "对接",
        "Lark",
        "Feishu",
    ]:
        if token.lower() in text.lower():
            candidates.append(token)
    return candidates[:8]


def _singular(kind: str) -> str:
    if kind == "rules":
        return "rule"
    if kind == "skills":
        return "skill"
    if kind == "counterexamples":
        return "counterexample"
    return kind


def _plural(kind: str) -> str:
    if kind == "rule":
        return "rules"
    if kind == "skill":
        return "skills"
    if kind == "counterexample":
        return "counterexamples"
    return kind


def _handler_code_proposal(handler_name: str) -> str:
    if handler_name == "weather_query":
        return '''def weather_query(rule, question, context):
    """Draft handler for a reviewed weather API rule.

    Required review before production use:
    - choose weather provider and credentials
    - define location/date extraction
    - define timeout, retry, and no-data behavior
    - add tests with mocked API responses
    """
    location = context.get("location")
    date = context.get("date", "today")
    if not location:
        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "type": "api_tool",
            "requires_more_info": True,
            "missing_fields": ["location"],
        }
    raise NotImplementedError("Weather API provider is not configured yet")
'''
    return '''def custom_tool_rule(rule, question, context):
    """Draft handler for a reviewed deterministic rule/tool."""
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": rule.type,
        "requires_more_info": True,
        "missing_fields": ["reviewed_handler_implementation"],
    }
'''


def _merge_llm_draft(data: dict[str, Any], llm_draft: dict[str, Any]) -> dict[str, Any]:
    if not llm_draft:
        return data
    merged = dict(data)
    merged["llm_draft"] = llm_draft
    for source_key, target_key in [
        ("stability_decision", "stability_decision"),
        ("rule", "rule"),
        ("handler_name", "handler"),
        ("handler_code_proposal", "handler_code_proposal"),
        ("skill_prompt", "prompt"),
        ("fallback_reason", "fallback_reason"),
    ]:
        value = llm_draft.get(source_key)
        if value:
            merged[target_key] = value
    if llm_draft.get("required_human_review"):
        merged["required_human_review"] = llm_draft["required_human_review"]
    return merged


def _generalize_capability_candidate(
    data: dict[str, Any],
    tool_result: Any,
) -> dict[str, Any]:
    if tool_result.tool_id == "open_meteo_weather":
        generalized = dict(data)
        generalized.update(
            {
                "name": "天气查询能力规则",
                "intent": ["weather_query"],
                "keywords": ["天气", "气温", "降水", "风速", "今天", "明天", "后天"],
                "priority": 90,
                "rule": (
                    "当用户询问任意城市的今天、明天或后天天气时，"
                    "优先调用天气查询能力获取实时/预报数据；不得复用某一次样例城市或日期。"
                ),
                "generalization": {
                    "scope": "任意可被天气服务解析的地点",
                    "time_range": ["今天", "明天", "后天"],
                    "do_not_match_on_sample_city": True,
                    "input_extraction": ["location", "date"],
                },
                "examples": [
                    "今天上海天气怎么样？",
                    "今天合肥天气怎么样？",
                    "明天上海天气怎么样？",
                ],
            }
        )
        return generalized
    return data


def _generalize_promoted_candidate(data: dict[str, Any]) -> dict[str, Any]:
    source_tool = data.get("source_tool")
    if source_tool == "open_meteo_weather":
        generalized = dict(data)
        generalized.update(
            {
                "name": "天气查询能力规则",
                "intent": ["weather_query"],
                "keywords": ["天气", "气温", "降水", "风速", "今天", "明天", "后天"],
                "priority": 90,
                "rule": (
                    "当用户询问任意城市的今天、明天或后天天气时，"
                    "优先调用天气查询能力获取实时/预报数据；不得复用某一次样例城市或日期。"
                ),
            }
        )
        return generalized
    return data
