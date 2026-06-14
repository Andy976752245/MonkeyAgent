from __future__ import annotations

from typing import Any, Protocol

from monkey_agent.advice import (
    is_personal_advice_task,
    personal_advice_answer,
    should_use_personal_advice_template,
)
from monkey_agent.core.config import Settings


class ChatModel(Protocol):
    def generate(
        self,
        question: str,
        deterministic_results: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> str:
        ...

    def draft_learning_candidate(
        self,
        question: str,
        candidate_type: str,
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def classify_question(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        ...

    def draft_tool_builder(
        self,
        question: str,
        spec: dict[str, Any],
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def smoke(self, role: str) -> str:
        ...


class BailianChatModel:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for BailianChatModel") from exc
        if not settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required for BailianChatModel")
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.bailian_base_url,
        )

    def _completion(
        self,
        *,
        role: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model_for_role(role),
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def model_for_role(self, role: str) -> str:
        mapping = {
            "classifier": self.settings.classifier_model,
            "reasoning": self.settings.reasoning_model,
            "tool_builder": self.settings.tool_builder_model,
            "evaluator": self.settings.evaluator_model,
            "chat": self.settings.chat_model,
        }
        return mapping.get(role, self.settings.chat_model) or self.settings.chat_model

    def smoke(self, role: str) -> str:
        return self._completion(
            role=role,
            messages=[
                {
                    "role": "user",
                    "content": f"请用一句话回复：MonkeyAgent 百炼 {role} 模型连接测试成功。",
                }
            ],
            temperature=0.0,
        )

    def generate(
        self,
        question: str,
        deterministic_results: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> str:
        rules_text = "\n".join(str(item) for item in deterministic_results) or "无"
        skills_text = "\n".join(
            f"{item.get('name')}: {item.get('prompt', '')}" for item in skills
        ) or "无"
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 MonkeyAgent，一个 Rules-first 自学习 Agent。"
                    "沉淀 Rules 的结果是确定事实，不得覆盖或改写。"
                    "Skills 只作为方法论和表达辅助。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n\n"
                    f"确定性 Rules 执行结果：\n{rules_text}\n\n"
                    f"可用 Skills：\n{skills_text}\n\n"
                    f"上下文：{context}\n\n"
                    "如果上下文包含 memory.preferences，请遵守用户偏好。"
                    "如果包含 memory.counterexamples，请避免重复其中的错误。"
                    "请给出简洁、可执行、符合 Rules 的回答。"
                ),
            },
        ]
        return self._completion(
            role="reasoning",
            messages=messages,
            temperature=self.settings.reasoning_temperature,
        )

    def draft_learning_candidate(
        self,
        question: str,
        candidate_type: str,
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 MonkeyAgent 的自学习代码草案生成器。"
                    "只能生成待人工审核的候选内容，不要声称已上线。"
                    "请输出严格 JSON，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n"
                    f"候选类型：{candidate_type}\n"
                    f"公开/工具证据：{evidence}\n"
                    f"上下文：{context}\n\n"
                    "如果适合稳定代码化，生成 Python handler 草案；"
                    "如果不适合，生成 Skill prompt 草案。"
                    "JSON 字段：stability_decision, rule, handler_name, "
                    "handler_code_proposal, skill_prompt, fallback_reason, "
                    "required_human_review。"
                ),
            },
        ]
        text = self._completion(
            role="tool_builder",
            messages=messages,
            temperature=self.settings.tool_builder_temperature,
        )
        return _parse_json_object(text)

    def classify_question(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 MonkeyAgent 的问题分类器。请输出严格 JSON，不要 Markdown。"
                    "字段：deterministic, semi_deterministic, uncertain, intents, "
                    "required_tools, task_type, confidence, clarification_questions。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n上下文：{context}\n"
                    "请进行多标签分类。确定性内容包括 Python规则/SQL/API/工具函数；"
                    "半确定内容包括 RAG/历史案例/Skill库/公开搜索；"
                    "不确定内容包括 LLM推理和需要人工确认。"
                    "个人助理建议类问题请识别为 sales_support、meeting_preparation、"
                    "planning_advice、communication_advice 或 personal_advice，"
                    "这类问题通常应先给可执行建议，再提出必要澄清。"
                ),
            },
        ]
        text = self._completion(
            role="classifier",
            messages=messages,
            temperature=self.settings.classifier_temperature,
        )
        return _parse_json_object(text or "{}")

    def draft_tool_builder(
        self,
        question: str,
        spec: dict[str, Any],
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 MonkeyAgent 的受控 Tool Builder。"
                    "请输出严格 JSON，不要 Markdown。生成的代码必须实现 MonkeyAgent Tool 协议，"
                    "只能使用安全 import，不得包含 shell、文件删除、eval/exec 或真实写外部系统。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n"
                    f"工具规格：{spec}\n"
                    f"公开/本地证据：{evidence}\n"
                    f"上下文：{context}\n\n"
                    "JSON 字段：tool_id, name, description, kind, permission, risk, "
                    "read_only, learn_policy, input_schema, output_schema, keywords, "
                    "class_name, code, test_context。"
                ),
            },
        ]
        text = self._completion(
            role="tool_builder",
            messages=messages,
            temperature=self.settings.tool_builder_temperature,
        )
        return _parse_json_object(text or "{}")


class LocalHeuristicModel:
    """Deterministic fallback used when external model credentials are absent."""

    def generate(
        self,
        question: str,
        deterministic_results: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> str:
        if deterministic_results:
            if any(item.get("source_tool") == "public_web_search" for item in deterministic_results):
                return "\n".join(
                    str(item.get("content", "")) for item in deterministic_results
                )
            lines = ["已优先执行沉淀 Rules："]
            for item in deterministic_results:
                label = item.get("rule_name") or item.get("rule_id")
                if "value" in item:
                    lines.append(f"- {label}: {item['value']}")
                else:
                    content = item.get("content") or item.get("recommendation")
                    lines.append(f"- {label}: {content}")
            return "\n".join(lines)
        if skills:
            task_type = str(context.get("task_type") or "") if isinstance(context, dict) else ""
            intents = context.get("intent_keywords", []) if isinstance(context, dict) else []
            if should_use_personal_advice_template(question, task_type, intents) or any(
                "个人助理" in str(item.get("name", "")) for item in skills
            ):
                return personal_advice_answer(question, task_type, context)
            names = ", ".join(str(item.get("name")) for item in skills)
            memory = context.get("memory", {}) if isinstance(context, dict) else {}
            preferences = memory.get("preferences", []) if isinstance(memory, dict) else []
            suffix = ""
            if any("表格" in str(item) for item in preferences):
                suffix = "\n| 项目 | 内容 |\n| --- | --- |\n| 执行方式 | Skill |\n"
            return f"未命中沉淀 Rules，已按 Skills 执行：{names}。{suffix}"
        return "当前缺少可执行的沉淀 Rules 或 Skills，需要补充更多业务信息。"

    def draft_learning_candidate(
        self,
        question: str,
        candidate_type: str,
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if candidate_type == "rule":
            handler = evidence.get("handler_name") or "custom_tool_rule"
            return {
                "stability_decision": "llm_drafted_rule_candidate",
                "rule": "基于公开证据和现有能力生成待审核确定性执行规则。",
                "handler_name": handler,
                "handler_code_proposal": evidence.get("handler_code_proposal")
                or (
                    f"def {handler}(rule, question, context):\n"
                    "    \"\"\"LLM drafted handler; requires human review.\"\"\"\n"
                    "    raise NotImplementedError(\"Review and implement before enabling\")\n"
                ),
                "required_human_review": [
                    "确认公开文档与授权范围",
                    "确认输入输出结构",
                    "补充 mock 测试和失败兜底",
                ],
            }
        return {
            "stability_decision": "llm_drafted_skill_candidate",
            "skill_prompt": (
                "基于公开搜索结果回答时，需要列出来源、区分事实和推断，"
                "对无法验证的信息要求用户确认。"
            ),
            "fallback_reason": "该问题更适合作为可复用方法沉淀为 Skill，而不是稳定代码 Rule。",
        }

    def classify_question(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        # Local fallback deliberately returns low confidence so keyword classifier wins.
        return {
            "deterministic": [],
            "semi_deterministic": [],
            "uncertain": [],
            "intents": [],
            "required_tools": [],
            "task_type": "general",
            "confidence": 0.0,
            "clarification_questions": [],
        }

    def smoke(self, role: str) -> str:
        return f"MonkeyAgent 本地 fallback {role} 模型连接测试成功。"

    def draft_tool_builder(
        self,
        question: str,
        spec: dict[str, Any],
        evidence: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        import re

        keywords = spec.get("keywords") or _keywords_from_question(question)
        tool_id = spec.get("tool_id") or _safe_tool_id(question)
        name = spec.get("name") or "自动生成工具"
        permission = spec.get("permission") or "auto"
        risk = spec.get("risk") or "low"
        read_only = bool(spec.get("read_only", permission == "auto"))
        learn_policy = spec.get("learn_policy") or "rule"
        class_name = "GeneratedTool"
        keyword_literal = repr([str(item) for item in keywords[:8]])
        content = (
            "该能力已通过受控 Tool Builder 生成 dry-run 工具。"
            if permission == "confirm"
            else "该能力已通过受控 Tool Builder 自动生成并执行。"
        )
        code = f'''from __future__ import annotations

from typing import Any

from monkey_agent.domains.tools import Permission, ToolExecutionResult, ToolRisk, ToolSchema


class {class_name}:
    id = {tool_id!r}
    name = {name!r}
    description = {str(spec.get("description") or "由 MonkeyAgent Tool Builder 生成的受控工具。")!r}
    input_schema = ToolSchema(required=[], properties={{"dry_run": "是否仅执行安全演练"}})
    output_schema = ToolSchema(required=["content"], properties={{"content": "工具执行摘要"}})
    permission = Permission.{str(permission).upper()}
    risk = ToolRisk.{str(risk).upper()}
    read_only = {read_only!r}
    learn_policy = {learn_policy!r}
    keywords = {keyword_literal}

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
                "keywords": self.keywords,
                "evidence_count": {len(evidence.get("public_evidence", []) or evidence.get("results", []) or [])},
            }},
            permission=self.permission,
            risk=self.risk,
            read_only=self.read_only,
        )


TOOL_CLASS = {class_name}
'''
        return {
            "tool_id": tool_id,
            "name": name,
            "description": spec.get("description") or "由 MonkeyAgent Tool Builder 生成的受控工具。",
            "kind": spec.get("kind") or "python_function",
            "permission": permission,
            "risk": risk,
            "read_only": read_only,
            "learn_policy": learn_policy,
            "input_schema": {"required": [], "properties": {"dry_run": "是否仅执行安全演练"}},
            "output_schema": {"required": ["content"], "properties": {"content": "工具执行摘要"}},
            "keywords": keywords,
            "class_name": class_name,
            "code": code,
            "test_context": {"dry_run": True},
        }


def build_chat_model(settings: Settings) -> ChatModel:
    if settings.dashscope_api_key:
        return BailianChatModel(settings)
    return LocalHeuristicModel()


def _parse_json_object(text: str) -> dict[str, Any]:
    import json
    import re

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {"raw_text": text}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"raw_text": text}
    return data if isinstance(data, dict) else {"raw_text": text}


def _safe_tool_id(question: str) -> str:
    import hashlib

    if "飞书" in question or "Feishu" in question or "Lark" in question:
        base = "generated_feishu_tool"
    elif "API" in question or "接口" in question or "接入" in question:
        base = "generated_api_tool"
    elif "计算" in question or "转换" in question:
        base = "generated_function_tool"
    else:
        base = "generated_tool"
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def _keywords_from_question(question: str) -> list[str]:
    import re

    keywords = []
    for token in [
        "API",
        "接口",
        "接入",
        "工具",
        "查询",
        "搜索",
        "天气",
        "飞书",
        "消息",
        "发送",
        "机器人",
        "计算",
        "转换",
        "提取",
        "同步",
    ]:
        if re.search(re.escape(token), question, flags=re.I):
            keywords.append(token)
    return keywords or [question[:12]]
