from __future__ import annotations

from typing import Any

from monkey_agent.advice import is_personal_advice_task, personal_advice_answer
from monkey_agent.core.state import AgentState


def fast_rule_answer(state: AgentState) -> str | None:
    if state.get("route") != "rules":
        return None
    if state.get("matched_skills"):
        return None
    results = state.get("deterministic_results", [])
    if not results:
        return None
    parts = [_format_rule_result(item) for item in results]
    parts = [item for item in parts if item]
    if not parts:
        return None
    return "\n".join(parts)


def agent_skill_execution_content(execution: dict[str, Any]) -> str:
    if execution.get("success"):
        stdout = str(execution.get("stdout") or "").strip()
        artifacts = execution.get("artifacts") or []
        lines = ["Agent Skill 脚本执行成功。"]
        if stdout:
            lines.append(stdout)
        if artifacts:
            lines.append("Artifacts:")
            lines.extend(f"- {item}" for item in artifacts)
        return "\n".join(lines)
    error = execution.get("error") or "skill_script_failed"
    stderr = str(execution.get("stderr") or "").strip()
    return f"Agent Skill 脚本执行失败：{error}" + (f"\n{stderr}" if stderr else "")


def fallback_answer(state: AgentState, context: dict[str, Any]) -> str:
    if is_personal_advice_task(
        state.get("task_type", "general"),
        state.get("intent_keywords", []),
    ):
        return personal_advice_answer(
            state["question"],
            state.get("task_type", "general"),
            context,
        )
    results = state.get("deterministic_results", [])
    if results:
        lines = ["已优先执行沉淀 Rules："]
        for item in results:
            label = item.get("rule_name") or item.get("rule_id") or "rule"
            content = item.get("value") or item.get("content") or item.get("recommendation")
            lines.append(f"- {label}: {content}")
        return "\n".join(lines)
    skills = state.get("matched_skills", [])
    if skills:
        names = ", ".join(str(item.get("name")) for item in skills)
        return f"模型暂时不可用，已匹配 Skills：{names}。请补充更多上下文后可继续生成更完整答案。"
    return "模型暂时不可用，当前缺少可执行的沉淀 Rules 或 Skills，需要补充更多信息。"


def is_generic_missing_capability_answer(answer: str) -> bool:
    return any(
        marker in answer
        for marker in [
            "当前缺少可执行的沉淀 Rules 或 Skills",
            "需要补充更多业务信息",
            "请补充这个问题所属的业务场景",
        ]
    )


def general_knowledge_fallback(question: str) -> str:
    if "长期加班" in question or ("加班" in question and any(marker in question for marker in ["怎么看", "看待", "你觉得", "你认为"])):
        return (
            "我会把团队长期加班视为一个管理信号，而不是单纯的个人努力问题。"
            "短期冲刺可以接受，但如果长期常态化，通常说明目标排期、资源配置、需求变更、流程效率或管理预期存在失衡。\n\n"
            "更合理的判断维度是：\n"
            "1. 是否有明确阶段性目标：临时攻坚和长期透支要分开看。\n"
            "2. 是否真的提升产出：长期加班往往会带来效率递减、质量下降和返工增加。\n"
            "3. 是否资源不足或排期失真：如果靠加班填坑，说明计划和人力模型需要重估。\n"
            "4. 是否有健康与流失风险：持续加班会损害士气、稳定性和团队信任。\n"
            "5. 是否有补偿与边界：调休、优先级裁剪、需求冻结和负责人决策要配套。\n\n"
            "我的建议是先量化问题：连续加班多久、每周工时、任务来源、延期原因、返工比例和人员状态。"
            "如果数据证明是常态化问题，就应该优先调整范围、优先级、资源和流程，而不是默认让团队继续硬扛。"
        )
    if any(marker in question for marker in ["料箱", "补货", "FTC", "WMS", "WCS", "仓储"]):
        return (
            "这类料箱补货问题应优先围绕“补得准、补得快、不断供、少搬运、可追踪”来分析。\n\n"
            "1. 补货触发：明确按库存下限、订单/波次需求、产线缺料或任务优先级触发，避免过早或过晚补货。\n"
            "2. 库存与库位准确：料箱、库存、库位、占用状态和容器状态要实时一致，否则补货任务会失真。\n"
            "3. 任务优先级：优先保障紧急订单、关键产线、缺口最大的 SKU 或即将影响履约的任务。\n"
            "4. 路径与效率：减少无效搬运、重复补货和交叉等待，关注补货路径、设备可用性和作业节拍。\n"
            "5. 异常闭环：缺货、空箱、任务失败、库位占用、设备异常要有兜底策略和人工介入入口。\n"
            "6. 系统协同：WMS/WCS/设备任务状态需要闭环，关键指标建议看缺货率、补货及时率、任务失败率和平均补货耗时。\n\n"
            "如果你说的“FTC 料箱库补货”有固定业务口径，我可以继续帮你沉淀成一个仓储补货分析 Skill。"
        )
    if any(marker in question for marker in ["介绍你自己", "说明你的能力", "你是谁", "你的能力"]):
        return (
            "我是 MonkeyAgent，一个面向个人独立部署的本地助理 Agent。"
            "我优先使用已沉淀的 Rules 处理确定性问题，例如计算、日期、单位换算和固定业务口径；"
            "其次使用 YAML Skills / Agent Skills 处理可复用的方法、模板和技能包；"
            "需要实时或外部信息时会尝试调用工具，例如天气、搜索或已生成工具；"
            "遇到可复用经验时会先生成 pending 候选，经过你确认后再沉淀为 Rule、Skill、Memory 或反例。"
            "你也可以通过 CLI、Telegram、API 和 Goal Engine 让我进行连续目标执行。"
        )
    if "LangGraph" in question or "Harness" in question or "Harness Engineering" in question:
        return (
            "MonkeyAgent 中 LangGraph 主要用于把 Ask 和 Goal 流程编排成节点化工作流："
            "分类、匹配 Rules、匹配 Skills、调用工具、推理、评估和学习沉淀都可以作为节点被追踪。"
            "Goal Engine 则借鉴 Harness-style Agent Engineering 的目标驱动思路："
            "给定目标后进行任务拆解、探索能力、执行下一步、评估进展、必要时请求人工确认，并把成功路径沉淀为个人能力。"
            "当前实现强调本地可控：只读探索自动执行，外部写操作和正式沉淀必须确认。"
        )
    if "水" in question and "结冰" in question:
        return (
            "水结冰是因为温度降低后，水分子的热运动减弱，分子之间更容易形成稳定的氢键结构。"
            "在标准大气压下，纯水通常在 0°C 左右凝固成冰。"
        )
    if "Python" in question and "Java" in question and "区别" in question:
        return (
            "Python 更强调简洁和开发效率，常用于脚本、数据分析、AI 和自动化；"
            "Java 更强调工程化、类型约束和大型服务端生态，常用于企业后端、Android 和大型系统。"
            "简单说，Python 上手快、表达短，Java 结构更严谨、长期维护能力强。"
        )
    return (
        "这是一个基础常识问题，不需要补充业务字段或外部系统配置。"
        "当前模型不可用时，我只能给出保守回答：请围绕定义、原因、例子和适用边界来理解这个问题；"
        "如果你希望更准确，我可以在模型或搜索能力可用后继续补充。"
    )


def _format_rule_result(item: dict[str, Any]) -> str:
    if item.get("requires_more_info"):
        return str(item.get("content") or item.get("error") or "需要补充更多信息。")
    if item.get("content"):
        return str(item["content"])
    if item.get("recommendation"):
        return str(item["recommendation"])
    if item.get("value") is not None:
        return str(item["value"])
    return ""
