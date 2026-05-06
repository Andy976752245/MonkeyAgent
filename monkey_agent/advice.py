from __future__ import annotations

from typing import Any


PERSONAL_ADVICE_INTENTS = {
    "sales_support",
    "meeting_preparation",
    "planning_advice",
    "communication_advice",
    "personal_advice",
}

PERSONAL_ADVICE_TASK_TYPES = set(PERSONAL_ADVICE_INTENTS)


def is_personal_advice_task(task_type: str | None, intents: list[str] | None = None) -> bool:
    intent_set = set(intents or [])
    return str(task_type or "") in PERSONAL_ADVICE_TASK_TYPES or bool(
        intent_set & PERSONAL_ADVICE_INTENTS
    )


def personal_advice_clarification_questions(task_type: str | None) -> list[str]:
    if task_type == "sales_support":
        return [
            "甲方的行业、角色和本次拜访对象是谁？",
            "这次拜访的目标是破冰、需求调研、方案推进、报价谈判还是续约？",
            "你已掌握哪些客户背景、痛点、现有系统和竞争对手信息？",
        ]
    if task_type == "meeting_preparation":
        return [
            "会议目标、参会角色和期望产出是什么？",
            "是否已有议程、材料、数据或需要提前同步的结论？",
            "会议后需要推动哪些责任人和下一步动作？",
        ]
    if task_type == "planning_advice":
        return [
            "这个计划的目标、截止时间和可用资源是什么？",
            "有哪些必须满足的约束、风险或优先级？",
            "你希望输出行动清单、时间表还是决策建议？",
        ]
    if task_type == "communication_advice":
        return [
            "沟通对象是谁，对方最关心什么？",
            "你希望达成共识、争取资源、推进决策还是处理分歧？",
            "有没有不能触碰的边界、敏感信息或既往沟通背景？",
        ]
    return [
        "这个问题的目标、对象和约束是什么？",
        "你希望我输出清单、话术、计划表还是风险提醒？",
        "有没有必须遵守的个人偏好、业务口径或背景信息？",
    ]


def personal_advice_answer(
    question: str,
    task_type: str | None,
    context: dict[str, Any] | None = None,
) -> str:
    questions = personal_advice_clarification_questions(task_type)
    memory = (context or {}).get("memory", {}) if isinstance(context, dict) else {}
    preferences = memory.get("preferences", []) if isinstance(memory, dict) else []
    prefer_table = any("表格" in str(item) for item in preferences)

    if task_type == "sales_support":
        items = [
            ("拜访目标", "先写清本次要拿到什么结果：建立信任、确认痛点、约下次方案会、拿到关键人或推进报价。"),
            ("客户画像", "准备甲方行业、业务模式、组织角色、现有系统、近期重点项目和可能的预算/决策链。"),
            ("痛点假设", "列 3-5 个你认为客户可能在效率、成本、协同、数据、交付或安全上的问题。"),
            ("方案素材", "准备 1 页公司介绍、2-3 个同行案例、产品能力清单、可演示场景和差异化价值。"),
            ("提问清单", "用开放问题确认现状：现在怎么做、哪里卡、谁受影响、成功标准是什么、何时需要解决。"),
            ("异议预案", "提前准备价格、周期、集成、数据安全、售后、竞品比较等常见问题的回答。"),
            ("下一步动作", "拜访结束前确认责任人、资料补充、下次会议主题、时间和双方待办。"),
        ]
        opening = "可以先按“目标、客户、痛点、方案、问题、异议、下一步”这 7 类准备。"
    elif task_type == "meeting_preparation":
        items = [
            ("会议目标", "明确会议要决策、同步、评审还是推进执行，避免只开成信息交换。"),
            ("参会角色", "标注每个人的关注点、决策权和你希望对方在会上完成的动作。"),
            ("材料准备", "提前准备结论页、背景数据、议题清单、风险项和需要拍板的问题。"),
            ("议程节奏", "把时间切成开场、关键议题、确认分歧、决议和下一步。"),
            ("会后闭环", "会前就设计好会议纪要、责任人、截止时间和追踪方式。"),
        ]
        opening = "可以先把会议当成一次“推动决策或行动”的小项目来准备。"
    elif task_type == "communication_advice":
        items = [
            ("沟通目标", "先确定你要争取共识、获得资源、澄清误解还是推动对方行动。"),
            ("对方关注", "换位写下对方最在意的收益、风险、成本和被评价方式。"),
            ("表达结构", "按背景、问题、建议、收益、风险兜底、需要对方确认的事项组织。"),
            ("话术准备", "准备一句开场、一段价值说明、三条证据和两个可选方案。"),
            ("收口动作", "最后明确下一步、时间点、责任人和确认方式。"),
        ]
        opening = "这类问题建议先从沟通目标倒推表达结构。"
    else:
        items = [
            ("目标", "先定义你想达成的结果，以及什么算完成。"),
            ("背景", "整理对象、约束、已有资源、时间窗口和不可触碰边界。"),
            ("行动", "拆成今天能准备、当场要确认、事后要跟进三类动作。"),
            ("风险", "提前列出最可能卡住的 3 个点，并准备备选方案。"),
            ("复盘", "结束后记录有效做法、对方反馈和下次可复用的模板。"),
        ]
        opening = "可以先给你一个通用、可执行的准备框架。"

    if prefer_table:
        rows = ["| 项目 | 准备内容 |", "| --- | --- |"]
        rows.extend(f"| {title} | {content} |" for title, content in items)
        body = "\n".join(rows)
    else:
        body = "\n".join(
            f"{index}. {title}：{content}"
            for index, (title, content) in enumerate(items, start=1)
        )

    follow_up = "\n".join(f"- {item}" for item in questions)
    return (
        f"{opening}\n\n"
        f"{body}\n\n"
        "如果时间很紧，优先准备：拜访目标/会议目标、对方背景、3 个关键问题、1 个可落地下一步。\n\n"
        f"为了把建议进一步贴合你的场景，我还需要确认：\n{follow_up}"
    )
