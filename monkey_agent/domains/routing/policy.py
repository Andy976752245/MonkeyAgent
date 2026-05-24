from __future__ import annotations

import re
from typing import Any


EXTERNAL_INFO_INTENTS = {"weather_query", "sports_query"}
PERSONAL_ADVICE_INTENTS = {
    "sales_support",
    "meeting_preparation",
    "planning_advice",
    "communication_advice",
    "personal_advice",
}
BASIC_DETERMINISTIC_TYPES = {"calculation", "date_calculation", "unit_conversion"}


class RoutingPolicy:
    """Central routing guard for common questions.

    This does not replace the classifier, rules, skills, or tools. It records a
    stable decision layer and blocks the common bad routes that have shown up in
    product testing.
    """

    def summarize(self, state: dict[str, Any]) -> dict[str, Any]:
        task_type = str(state.get("task_type") or "general")
        intents = [str(item) for item in state.get("intent_keywords", []) or []]
        category = self.category(task_type, intents, str(state.get("question") or ""))
        clarification_allowed, reason = self.clarification_allowed(state, category)
        return {
            "category": category,
            "task_type": task_type,
            "intents": intents,
            "clarification_allowed": clarification_allowed,
            "clarification_reason": reason,
            "prefer_general_reason": self.prefer_general_reason(state, category),
        }

    def category(self, task_type: str, intents: list[str], question: str) -> str:
        intent_set = set(intents)
        if task_type in BASIC_DETERMINISTIC_TYPES:
            return "deterministic_basic"
        if intent_set & EXTERNAL_INFO_INTENTS:
            return "external_info"
        if task_type == "integration" or "integration" in intent_set:
            return "business_missing_context"
        if intent_set & PERSONAL_ADVICE_INTENTS:
            return "personal_advice"
        if task_type == "general_knowledge" or "general_knowledge" in intent_set:
            return "general_knowledge"
        if _looks_like_business_missing_context(question):
            return "business_missing_context"
        return "general_knowledge"

    def filter_rule_matches(
        self,
        state: dict[str, Any],
        matches: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allowed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for match in matches:
            reason = self._blocked_rule_reason(state, match)
            if reason:
                blocked.append(
                    {
                        "rule_id": match.get("id"),
                        "rule_name": match.get("name"),
                        "handler": match.get("handler"),
                        "reason": reason,
                    }
                )
            else:
                allowed.append(match)
        return allowed, blocked

    def prefer_general_reason(self, state: dict[str, Any], category: str | None = None) -> bool:
        category = category or self.category(
            str(state.get("task_type") or "general"),
            [str(item) for item in state.get("intent_keywords", []) or []],
            str(state.get("question") or ""),
        )
        if _explicit_learning_requested(str(state.get("question") or "")):
            return False
        return category in {"general_knowledge", "personal_advice"}

    def clarification_allowed(
        self,
        state: dict[str, Any],
        category: str | None = None,
    ) -> tuple[bool, str]:
        question = str(state.get("question") or "")
        category = category or self.category(
            str(state.get("task_type") or "general"),
            [str(item) for item in state.get("intent_keywords", []) or []],
            question,
        )
        exploration = state.get("exploration")
        if isinstance(exploration, dict) and exploration.get("tool_found") and not exploration.get("success", True):
            return True, "tool_failed_or_missing_configuration"
        tool_builder = state.get("tool_builder")
        if (
            isinstance(tool_builder, dict)
            and tool_builder.get("error")
            and tool_builder.get("error") != "not_a_tool_builder_candidate"
        ):
            return True, "tool_builder_failed"
        if category == "business_missing_context":
            return True, "business_context_required"
        if category == "deterministic_basic" and _basic_input_missing(state):
            return True, "deterministic_input_missing"
        if _explicit_learning_requested(question):
            return True, "explicit_learning_or_rule_request"
        return False, f"{category}_should_answer_or_route_elsewhere"

    def _blocked_rule_reason(self, state: dict[str, Any], rule: dict[str, Any]) -> str | None:
        intents = {str(item) for item in state.get("intent_keywords", []) or []}
        handler = str(rule.get("handler") or "")
        source_tool = str(rule.get("source_tool") or rule.get("capability_tool_id") or "")
        if handler == "date_calculation" and intents & (EXTERNAL_INFO_INTENTS | PERSONAL_ADVICE_INTENTS | {"integration"}):
            return "date_rule_cannot_override_primary_intent"
        if handler == "arithmetic_formula" and not _looks_like_arithmetic_question(str(state.get("question") or "")):
            return "arithmetic_rule_requires_arithmetic_expression"
        if handler == "unit_conversion" and "unit_conversion" not in intents:
            return "unit_rule_requires_unit_conversion_intent"
        if source_tool and "weather" in source_tool and "weather_query" not in intents:
            return "weather_rule_requires_weather_intent"
        return None


def _looks_like_business_missing_context(question: str) -> bool:
    return any(
        token in question
        for token in [
            "分析",
            "数据",
            "字段",
            "口径",
            "报表",
            "损耗",
            "文件",
            "上传",
            "判断",
            "方案",
            "生成",
            "工具",
            "查询",
            "SQL",
            "API",
            "接口",
            "接入",
            "对接",
            "系统",
        ]
    )


def _basic_input_missing(state: dict[str, Any]) -> bool:
    results = state.get("deterministic_results") or []
    return any(
        isinstance(item, dict) and item.get("requires_more_info")
        for item in results
    )


def _explicit_learning_requested(question: str) -> bool:
    return any(token in question for token in ["沉淀", "记住", "以后", "规则", "复用"])


def _looks_like_arithmetic_question(question: str) -> bool:
    stripped = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", question)
    normalized = (
        stripped.replace("（", "(")
        .replace("）", ")")
        .replace("×", "*")
        .replace("÷", "/")
    )
    normalized = _normalize_chinese_arithmetic(normalized)
    return bool(
        re.search(r"\d", normalized)
        and re.search(r"\d\s*[\+\-\*/]\s*\d|\([0-9\+\-\*/\.\s]+\)|帮我算|计算", normalized)
    )


def _normalize_chinese_arithmetic(text: str) -> str:
    replacements = [
        ("加上", "+"),
        ("加", "+"),
        ("减去", "-"),
        ("减", "-"),
        ("乘以", "*"),
        ("乘", "*"),
        ("除以", "/"),
        ("除", "/"),
    ]
    normalized = text
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized
