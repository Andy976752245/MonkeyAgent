from __future__ import annotations

import re

from .models import Rule, RuleMatch


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


CORE_KEYWORDS_BY_INTENT = {
    "weather_query": {"天气", "气温", "降水", "风速"},
}


class RuleMatcher:
    def match(
        self,
        question: str,
        intent_keywords: list[str],
        rules: list[Rule],
    ) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        intent_set = {item.lower() for item in intent_keywords}
        for rule in rules:
            score = rule.priority
            if rule.metadata.get("_source_layer") == "personal":
                score += 1000
            reasons: list[str] = []

            keyword_hits = [kw for kw in rule.keywords if _contains(question, kw)]
            intent_hits = [item for item in rule.intents if item.lower() in intent_set]

            if not _passes_core_keyword_gate(
                rule,
                question,
                keyword_hits,
                intent_hits,
                intent_set,
            ):
                continue

            if keyword_hits:
                score += 30 * len(keyword_hits)
                reasons.append("keyword:" + ",".join(keyword_hits))

            if intent_hits:
                score += 20 * len(intent_hits)
                reasons.append("intent:" + ",".join(intent_hits))

            if reasons:
                matches.append(RuleMatch(rule=rule, score=score, reasons=reasons))

        return sorted(matches, key=lambda item: item.score, reverse=True)


def _passes_core_keyword_gate(
    rule: Rule,
    question: str,
    keyword_hits: list[str],
    intent_hits: list[str],
    intent_set: set[str],
) -> bool:
    if rule.handler == "percentage_formula" and not keyword_hits:
        return False
    if rule.handler == "arithmetic_formula" and not _looks_like_arithmetic_question(question):
        return False
    if rule.handler == "date_calculation" and intent_set & {
        "weather_query",
        "sports_query",
        "integration",
        "sales_support",
        "meeting_preparation",
        "planning_advice",
        "communication_advice",
        "personal_advice",
    }:
        return False
    for intent in rule.intents:
        core_keywords = CORE_KEYWORDS_BY_INTENT.get(intent)
        if not core_keywords:
            continue
        if intent.lower() in {item.lower() for item in intent_hits}:
            return True
        if any(keyword in core_keywords for keyword in keyword_hits):
            return True
        return False
    return True


def _looks_like_arithmetic_question(question: str) -> bool:
    stripped = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", question)
    normalized = (
        stripped.replace("（", "(")
        .replace("）", ")")
        .replace("×", "*")
        .replace("÷", "/")
    )
    return bool(
        re.search(r"\d", normalized)
        and re.search(r"\d\s*[\+\-\*/]\s*\d|\([0-9\+\-\*/\.\s]+\)|帮我算|计算", normalized)
    )
