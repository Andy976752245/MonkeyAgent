from __future__ import annotations

import re
from typing import Any

from monkey_agent.advice import PERSONAL_ADVICE_INTENTS
from monkey_agent.domains.models.bailian import ChatModel

from .models import ClassificationResult


class QuestionClassifier:
    def __init__(self, chat_model: ChatModel, confidence_threshold: float = 0.7) -> None:
        self.chat_model = chat_model
        self.confidence_threshold = confidence_threshold

    def keyword_classify(self, question: str) -> ClassificationResult:
        intents = _intent_keywords(question)
        task_type = _task_type(intents)
        deterministic: list[str] = []
        semi_deterministic: list[str] = []
        uncertain: list[str] = []
        required_tools: list[str] = []

        if re.search(r"\d", question):
            deterministic.append("numeric")
        if any(word in question for word in ["公式", "计算", "百分比", "日期"]):
            deterministic.append("rule_candidate")
        if any(word in question for word in ["案例", "历史", "知识库", "经验", "Skill", "月报", "分析"]):
            semi_deterministic.append("rag_or_skill_candidate")
        if "weather_query" in intents:
            required_tools.append("open_meteo_weather")
            deterministic.append("api_tool")
        if "integration" in intents:
            required_tools.append("feishu_send_message")
            deterministic.append("api_tool")
        if "sports_query" in intents:
            required_tools.append("public_web_search")
            semi_deterministic.append("public_search")
        if set(intents) & PERSONAL_ADVICE_INTENTS:
            semi_deterministic.append("personal_assistant_skill_candidate")
        if any(word in question for word in ["判断", "推理", "可能", "为什么", "建议"]):
            uncertain.append("llm_reasoning_candidate")
        if not deterministic and not semi_deterministic:
            uncertain.append("human_confirmation_required")

        confidence = 0.85 if intents != ["general"] else 0.55
        return ClassificationResult(
            deterministic=deterministic,
            semi_deterministic=semi_deterministic,
            uncertain=uncertain,
            intents=intents,
            required_tools=required_tools,
            task_type=task_type,
            confidence=confidence,
            source="keyword",
        )

    def llm_classify(self, question: str, context: dict[str, Any]) -> ClassificationResult:
        try:
            data = self.chat_model.classify_question(question, context)
        except Exception:
            return ClassificationResult(source="llm", confidence=0.0)
        return ClassificationResult.from_dict(data, source="llm")

    def classify(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        keyword = self.keyword_classify(question)
        llm = self.llm_classify(question, context)
        merged = self.merge(keyword, llm)
        return {
            "classification": {
                "keyword": keyword.to_dict(),
                "llm": llm.to_dict(),
                "merged": merged.to_dict(),
            },
            "task_type": merged.task_type,
            "intent_keywords": merged.intents or ["general"],
            "deterministic_parts": merged.deterministic,
            "deterministic_content": merged.deterministic,
            "semi_deterministic_content": merged.semi_deterministic,
            "uncertain_content": merged.uncertain,
            "uncertain_parts": merged.uncertain,
            "required_tools": merged.required_tools,
            "classification_confidence": merged.confidence,
        }

    def merge(
        self,
        keyword: ClassificationResult,
        llm: ClassificationResult,
    ) -> ClassificationResult:
        if llm.confidence >= self.confidence_threshold:
            intents = _dedupe(llm.intents + keyword.intents)
            return ClassificationResult(
                deterministic=_dedupe(llm.deterministic + keyword.deterministic),
                semi_deterministic=_dedupe(llm.semi_deterministic + keyword.semi_deterministic),
                uncertain=_dedupe(llm.uncertain),
                intents=intents or keyword.intents,
                required_tools=_dedupe(llm.required_tools + keyword.required_tools),
                task_type=llm.task_type if llm.task_type != "general" else keyword.task_type,
                confidence=max(llm.confidence, keyword.confidence),
                clarification_questions=llm.clarification_questions,
                source="merged",
            )
        return ClassificationResult(
            deterministic=keyword.deterministic,
            semi_deterministic=keyword.semi_deterministic,
            uncertain=keyword.uncertain,
            intents=keyword.intents,
            required_tools=keyword.required_tools,
            task_type=keyword.task_type,
            confidence=keyword.confidence,
            clarification_questions=keyword.clarification_questions,
            source="merged",
        )


def _intent_keywords(question: str) -> list[str]:
    mapping = {
        "chart": ["图表", "趋势", "折线图", "柱状图", "环比", "同比"],
        "calculation": ["计算", "公式", "百分比", "%"],
        "report_writing": ["周报", "月报", "总结", "汇报", "复盘"],
        "sales_support": ["销售", "拜访", "客户", "甲方", "乙方", "商机"],
        "meeting_preparation": ["会议", "会前", "参会", "议程", "主持", "启动会"],
        "planning_advice": ["计划", "安排", "准备什么", "应该准备", "怎么准备"],
        "communication_advice": ["沟通", "谈判", "推进", "说服", "话术"],
        "personal_advice": ["建议", "怎么办", "应该怎么", "如何处理"],
        "weather_query": ["天气", "气温", "降水", "风速"],
        "integration": ["飞书", "Lark", "对接", "消息", "发送"],
        "sports_query": ["NBA", "比赛", "赛程", "球队", "赛事"],
    }
    found: list[str] = []
    for intent, words in mapping.items():
        if any(word in question for word in words):
            found.append(intent)
    return found or ["general"]


def _task_type(intents: list[str]) -> str:
    for intent, task_type in [
        ("chart", "chart_selection"),
        ("calculation", "calculation"),
        ("report_writing", "report_writing"),
        ("sales_support", "sales_support"),
        ("meeting_preparation", "meeting_preparation"),
        ("planning_advice", "planning_advice"),
        ("communication_advice", "communication_advice"),
        ("personal_advice", "personal_advice"),
        ("weather_query", "weather_query"),
        ("integration", "integration"),
        ("sports_query", "sports_query"),
    ]:
        if intent in intents:
            return task_type
    return "general"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
