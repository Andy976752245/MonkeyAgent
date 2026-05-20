from __future__ import annotations

import ast
import operator
import re
from datetime import date, datetime, timedelta
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


def arithmetic_formula(
    rule: Rule,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    expression = str(context.get("expression") or _extract_arithmetic_expression(question) or "")
    result: dict[str, Any] = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": "formula",
        "formula": "安全四则运算",
        "requires_more_info": False,
    }
    if not expression:
        result["requires_more_info"] = True
        result["content"] = "请提供需要计算的算术表达式。"
        return result
    try:
        value = _safe_arithmetic_eval(expression)
    except ValueError as exc:
        result["requires_more_info"] = True
        result["error"] = str(exc)
        result["content"] = "算术表达式包含不支持或不安全的内容。"
        return result
    result["expression"] = expression
    result["value"] = _format_number(value)
    result["content"] = f"{expression} = {result['value']}"
    return result


def date_calculation(
    rule: Rule,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    today = _context_today(context)
    result: dict[str, Any] = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": "date",
        "requires_more_info": False,
    }
    dates = _extract_iso_dates(question)
    if len(dates) >= 2 and any(word in question for word in ["相差", "间隔", "多少天"]):
        delta = abs((dates[1] - dates[0]).days)
        result["value"] = f"{delta}天"
        result["content"] = f"{dates[0].isoformat()} 到 {dates[1].isoformat()} 相差 {delta} 天。"
        return result

    target = None
    label = ""
    match = re.search(r"(\d+)\s*天后", question)
    if match:
        days = int(match.group(1))
        target = today + timedelta(days=days)
        label = f"{days}天后"
    elif "后天" in question:
        target = today + timedelta(days=2)
        label = "后天"
    elif "明天" in question:
        target = today + timedelta(days=1)
        label = "明天"
    elif "昨天" in question:
        target = today - timedelta(days=1)
        label = "昨天"
    elif "今天" in question:
        target = today
        label = "今天"
    elif "下周" in question:
        target = today + timedelta(days=7)
        label = "下周同日"
    elif dates:
        target = dates[0]
        label = "指定日期"

    if target is None:
        result["requires_more_info"] = True
        result["content"] = "请提供明确日期或日期推算条件。"
        return result
    result["value"] = target.isoformat()
    result["content"] = f"{label}是 {target.isoformat()}。"
    return result


def unit_conversion(
    rule: Rule,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    conversion = _extract_unit_conversion(question, context)
    result: dict[str, Any] = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "type": "unit_conversion",
        "requires_more_info": False,
    }
    if conversion is None:
        result["requires_more_info"] = True
        result["content"] = "请提供数值、源单位和目标单位。"
        return result
    value, source_unit, target_unit = conversion
    converted = _convert_unit(value, source_unit, target_unit)
    if converted is None:
        result["requires_more_info"] = True
        result["content"] = f"暂不支持 {source_unit} 到 {target_unit} 的换算。"
        return result
    result["value"] = f"{_format_number(converted)}{target_unit}"
    result["content"] = f"{_format_number(value)}{source_unit} = {result['value']}。"
    result["inputs"] = {
        "value": _format_number(value),
        "source_unit": source_unit,
        "target_unit": target_unit,
    }
    return result


_ARITHMETIC_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _extract_arithmetic_expression(question: str) -> str | None:
    normalized = (
        question.replace("（", "(")
        .replace("）", ")")
        .replace("×", "*")
        .replace("x", "*")
        .replace("X", "*")
        .replace("÷", "/")
        .replace("％", "%")
    )
    normalized = re.sub(r"(等于|是多少|等于几|帮我算一下|帮我算|计算|请算一下|请算)", " ", normalized)
    candidates = re.findall(r"[0-9\.\+\-\*/%\(\)\s]+", normalized)
    candidates = [item.strip() for item in candidates if re.search(r"\d", item)]
    if not candidates:
        return None
    expression = max(candidates, key=len).strip()
    if "%" in expression:
        expression = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expression)
    return expression


def _safe_arithmetic_eval(expression: str) -> Decimal:
    if len(expression) > 120:
        raise ValueError("expression too long")
    if not re.fullmatch(r"[0-9\.\+\-\*/%\(\)\s]+", expression):
        raise ValueError("unsupported characters")
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid expression") from exc
    return Decimal(str(_eval_arithmetic_node(node.body)))


def _eval_arithmetic_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC_OPERATORS:
        left = _eval_arithmetic_node(node.left)
        right = _eval_arithmetic_node(node.right)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ValueError("division by zero")
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("exponent too large")
        return _ARITHMETIC_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITHMETIC_OPERATORS:
        return _ARITHMETIC_OPERATORS[type(node.op)](_eval_arithmetic_node(node.operand))
    raise ValueError("unsupported expression")


def _context_today(context: dict[str, Any]) -> date:
    raw = context.get("today")
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            pass
    return date.today()


def _extract_iso_dates(question: str) -> list[date]:
    result: list[date] = []
    for raw in re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", question):
        try:
            result.append(date.fromisoformat(raw.replace("/", "-")))
        except ValueError:
            continue
    for raw in re.findall(r"\d{4}年\d{1,2}月\d{1,2}日?", question):
        try:
            result.append(datetime.strptime(raw.rstrip("日"), "%Y年%m月%d").date())
        except ValueError:
            continue
    return result


_UNIT_ALIASES = {
    "公里": "公里",
    "千米": "公里",
    "km": "公里",
    "米": "米",
    "m": "米",
    "厘米": "厘米",
    "cm": "厘米",
    "毫米": "毫米",
    "mm": "毫米",
    "千克": "千克",
    "公斤": "千克",
    "kg": "千克",
    "克": "克",
    "g": "克",
    "吨": "吨",
    "t": "吨",
    "升": "升",
    "l": "升",
    "毫升": "毫升",
    "ml": "毫升",
    "摄氏度": "摄氏度",
    "摄氏": "摄氏度",
    "℃": "摄氏度",
    "华氏度": "华氏度",
    "华氏": "华氏度",
    "℉": "华氏度",
}

_LINEAR_UNITS = {
    "公里": ("length", Decimal("1000")),
    "米": ("length", Decimal("1")),
    "厘米": ("length", Decimal("0.01")),
    "毫米": ("length", Decimal("0.001")),
    "吨": ("mass", Decimal("1000000")),
    "千克": ("mass", Decimal("1000")),
    "克": ("mass", Decimal("1")),
    "升": ("volume", Decimal("1000")),
    "毫升": ("volume", Decimal("1")),
}


def _extract_unit_conversion(
    question: str,
    context: dict[str, Any],
) -> tuple[Decimal, str, str] | None:
    if all(context.get(key) is not None for key in ["value", "source_unit", "target_unit"]):
        source = _canonical_unit(str(context["source_unit"]))
        target = _canonical_unit(str(context["target_unit"]))
        if source and target:
            return Decimal(str(context["value"])), source, target
    unit_pattern = "|".join(sorted((re.escape(unit) for unit in _UNIT_ALIASES), key=len, reverse=True))
    patterns = [
        rf"([0-9]+(?:\.[0-9]+)?)\s*({unit_pattern})\s*(?:等于|是多少|转换成|换算成|是多少)\s*(?:多少)?\s*({unit_pattern})",
        rf"([0-9]+(?:\.[0-9]+)?)\s*({unit_pattern}).*?多少\s*({unit_pattern})",
        rf"({unit_pattern})\s*([0-9]+(?:\.[0-9]+)?)\s*度?.*?(?:等于|是多少|转换成|换算成|多少)\s*({unit_pattern})",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.I)
        if match:
            if len(match.groups()) == 3 and re.match(r"^[0-9]", match.group(1)):
                value = Decimal(match.group(1))
                source = _canonical_unit(match.group(2))
                target = _canonical_unit(match.group(3))
            else:
                value = Decimal(match.group(2))
                source = _canonical_unit(match.group(1))
                target = _canonical_unit(match.group(3))
            if source and target:
                return value, source, target
    return None


def _canonical_unit(raw: str) -> str | None:
    return _UNIT_ALIASES.get(raw.lower(), _UNIT_ALIASES.get(raw))


def _convert_unit(value: Decimal, source_unit: str, target_unit: str) -> Decimal | None:
    if source_unit in {"摄氏度", "华氏度"} or target_unit in {"摄氏度", "华氏度"}:
        if source_unit == "摄氏度" and target_unit == "华氏度":
            return value * Decimal("9") / Decimal("5") + Decimal("32")
        if source_unit == "华氏度" and target_unit == "摄氏度":
            return (value - Decimal("32")) * Decimal("5") / Decimal("9")
        return value if source_unit == target_unit else None
    source = _LINEAR_UNITS.get(source_unit)
    target = _LINEAR_UNITS.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    base = value * source[1]
    return base / target[1]


def _format_number(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return format(quantized.normalize(), "f")


HANDLERS = {
    "pass_through": pass_through,
    "chart_recommendation": chart_recommendation,
    "percentage_formula": percentage_formula,
    "arithmetic_formula": arithmetic_formula,
    "date_calculation": date_calculation,
    "unit_conversion": unit_conversion,
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
