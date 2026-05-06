from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import Rule


def _find_named_number(question: str, names: list[str]) -> Decimal | None:
    name_pattern = "|".join(re.escape(name) for name in names)
    patterns = [
        rf"(?:{name_pattern})\D{{0,8}}([0-9]+(?:\.[0-9]+)?)",
        rf"([0-9]+(?:\.[0-9]+)?)\D{{0,8}}(?:{name_pattern})",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return Decimal(match.group(1))
    return None


def pass_through(rule: Rule, question: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": rule.type,
        "content": rule.rule,
        "requires_more_info": False,
    }


def chart_recommendation(
    rule: Rule,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": "chart",
        "recommendation": rule.rule,
        "requires_more_info": False,
    }


def percentage_formula(
    rule: Rule,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    numerator = context.get("numerator")
    denominator = context.get("denominator")
    if numerator is None:
        numerator = _find_named_number(question, ["分子", "部分", "完成数", "已完成", "numerator"])
    else:
        numerator = Decimal(str(numerator))
    if denominator is None:
        denominator = _find_named_number(question, ["分母", "总数", "目标数", "总量", "denominator"])
    else:
        denominator = Decimal(str(denominator))

    result: dict[str, Any] = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": "formula",
        "formula": "百分比 = 分子 / 分母 * 100%",
        "requires_more_info": False,
    }
    if numerator is None or denominator is None:
        result["requires_more_info"] = True
        result["missing_fields"] = [
            field
            for field, value in [("numerator", numerator), ("denominator", denominator)]
            if value is None
        ]
        result["content"] = rule.rule
        return result
    if denominator == 0:
        result["requires_more_info"] = True
        result["error"] = "denominator cannot be zero"
        return result

    value = (numerator / denominator * Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    result["value"] = f"{value}%"
    result["inputs"] = {
        "numerator": str(numerator),
        "denominator": str(denominator),
    }
    return result


HANDLERS = {
    "pass_through": pass_through,
    "chart_recommendation": chart_recommendation,
    "percentage_formula": percentage_formula,
}


class RuleExecutor:
    def execute(
        self,
        rules: list[Rule],
        question: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for rule in rules:
            handler = HANDLERS.get(rule.handler, pass_through)
            results.append(handler(rule, question, context))
        return results
