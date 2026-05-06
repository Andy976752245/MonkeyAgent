from __future__ import annotations

import argparse
import json
from typing import Any

from monkey_agent.app import MonkeyAgent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="monkey")
    sub = parser.add_subparsers(dest="command", required=True)

    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--context", default="{}")
    ask_parser.add_argument("--feedback")

    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    rules_parser = sub.add_parser("rules")
    rules_sub = rules_parser.add_subparsers(dest="rules_command", required=True)
    rules_sub.add_parser("list")

    skills_parser = sub.add_parser("skills")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", required=True)
    skills_list = skills_sub.add_parser("list")
    skills_list.add_argument("--type", choices=["all", "yaml", "agent"], default="all")
    skills_install = skills_sub.add_parser("install")
    skills_install.add_argument("source")
    skills_install.add_argument("--skill")
    skills_import = skills_sub.add_parser("import")
    skills_import.add_argument("path")
    skills_inspect = skills_sub.add_parser("inspect")
    skills_inspect.add_argument("skill_name")
    skills_enable = skills_sub.add_parser("enable")
    skills_enable.add_argument("skill_name")
    skills_disable = skills_sub.add_parser("disable")
    skills_disable.add_argument("skill_name")
    skills_remove = skills_sub.add_parser("remove")
    skills_remove.add_argument("skill_name")

    memory_parser = sub.add_parser("memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_sub.add_parser("list")

    counter_parser = sub.add_parser("counterexamples")
    counter_sub = counter_parser.add_subparsers(dest="counter_command", required=True)
    counter_sub.add_parser("list")

    capabilities_parser = sub.add_parser("capabilities")
    capabilities_sub = capabilities_parser.add_subparsers(
        dest="capabilities_command",
        required=True,
    )
    capabilities_sub.add_parser("list")

    tools_parser = sub.add_parser("tools")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list")
    generated_parser = tools_sub.add_parser("generated")
    generated_sub = generated_parser.add_subparsers(
        dest="generated_command",
        required=True,
    )
    generated_sub.add_parser("list")
    inspect = generated_sub.add_parser("inspect")
    inspect.add_argument("tool_id")
    enable = generated_sub.add_parser("enable")
    enable.add_argument("tool_id")
    disable = generated_sub.add_parser("disable")
    disable.add_argument("tool_id")
    test = generated_sub.add_parser("test")
    test.add_argument("tool_id")

    review_parser = sub.add_parser("review")
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("list")
    approve = review_sub.add_parser("approve")
    approve.add_argument("candidate_id")
    reject = review_sub.add_parser("reject")
    reject.add_argument("candidate_id")

    adopt_parser = sub.add_parser("adopt")
    adopt_parser.add_argument("candidate_id")

    goal_parser = sub.add_parser("goal")
    goal_sub = goal_parser.add_subparsers(dest="goal_command", required=True)
    goal_start = goal_sub.add_parser("start")
    goal_start.add_argument("goal")
    goal_start.add_argument("--context", default="{}")
    goal_start.add_argument("--max-steps", type=int, default=5)
    goal_start.add_argument("--autonomy-policy", default="read_only_auto_write_confirm")
    goal_start.add_argument("--success-criteria", action="append", default=[])
    goal_start.add_argument("--force-learning", action="store_true")
    goal_step = goal_sub.add_parser("step")
    goal_step.add_argument("goal_id")
    goal_step.add_argument("--confirm", action="store_true")
    goal_status = goal_sub.add_parser("status")
    goal_status.add_argument("goal_id")
    goal_plan = goal_sub.add_parser("plan")
    goal_plan.add_argument("goal_id")
    goal_events = goal_sub.add_parser("events")
    goal_events.add_argument("goal_id")
    goal_pause = goal_sub.add_parser("pause")
    goal_pause.add_argument("goal_id")
    goal_resume = goal_sub.add_parser("resume")
    goal_resume.add_argument("goal_id")
    goal_sub.add_parser("list")

    runs_parser = sub.add_parser("runs")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list")
    runs_list.add_argument("--type", choices=["ask", "goal", "tool"])
    runs_list.add_argument("--limit", type=int, default=50)
    runs_inspect = runs_sub.add_parser("inspect")
    runs_inspect.add_argument("run_id")
    runs_latest = runs_sub.add_parser("latest")
    runs_latest.add_argument("--type", choices=["ask", "goal", "tool"])

    model_parser = sub.add_parser("model")
    model_sub = model_parser.add_subparsers(dest="model_command", required=True)
    smoke = model_sub.add_parser("smoke")
    smoke.add_argument(
        "--role",
        choices=["chat", "classifier", "reasoning", "tool_builder", "evaluator"],
        default="chat",
    )

    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("monkey_agent.interfaces.api.app:app", host=args.host, port=args.port)
        return

    agent = MonkeyAgent()
    if args.command == "ask":
        context = _load_json(args.context)
        result = agent.ask(
            args.question,
            context=context,
            feedback=args.feedback,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "rules":
        print(json.dumps(agent.list_rules(), ensure_ascii=False, indent=2))
    elif args.command == "skills":
        if args.skills_command == "list":
            print(json.dumps(agent.list_skills(args.type), ensure_ascii=False, indent=2))
        elif args.skills_command == "install":
            print(json.dumps(agent.install_agent_skill(args.source, args.skill), ensure_ascii=False, indent=2))
        elif args.skills_command == "import":
            print(json.dumps(agent.import_agent_skill(args.path), ensure_ascii=False, indent=2))
        elif args.skills_command == "inspect":
            print(json.dumps(agent.inspect_agent_skill(args.skill_name), ensure_ascii=False, indent=2))
        elif args.skills_command == "enable":
            print(json.dumps(agent.enable_agent_skill(args.skill_name), ensure_ascii=False, indent=2))
        elif args.skills_command == "disable":
            print(json.dumps(agent.disable_agent_skill(args.skill_name), ensure_ascii=False, indent=2))
        elif args.skills_command == "remove":
            print(json.dumps(agent.remove_agent_skill(args.skill_name), ensure_ascii=False, indent=2))
    elif args.command == "memory":
        print(json.dumps(agent.list_memory(), ensure_ascii=False, indent=2))
    elif args.command == "counterexamples":
        print(json.dumps(agent.list_counterexamples(), ensure_ascii=False, indent=2))
    elif args.command == "capabilities":
        print(json.dumps(agent.list_capabilities(), ensure_ascii=False, indent=2))
    elif args.command == "tools":
        if args.tools_command == "list":
            print(json.dumps(agent.list_capabilities(), ensure_ascii=False, indent=2))
        elif args.tools_command == "generated":
            if args.generated_command == "list":
                print(json.dumps(agent.list_generated_tools(), ensure_ascii=False, indent=2))
            elif args.generated_command == "inspect":
                print(json.dumps(agent.get_generated_tool(args.tool_id), ensure_ascii=False, indent=2))
            elif args.generated_command == "enable":
                print(json.dumps(agent.enable_generated_tool(args.tool_id), ensure_ascii=False, indent=2))
            elif args.generated_command == "disable":
                print(json.dumps(agent.disable_generated_tool(args.tool_id), ensure_ascii=False, indent=2))
            elif args.generated_command == "test":
                print(json.dumps(agent.test_generated_tool(args.tool_id), ensure_ascii=False, indent=2))
    elif args.command == "review":
        if args.review_command == "list":
            print(json.dumps(agent.list_pending(), ensure_ascii=False, indent=2))
        elif args.review_command == "approve":
            path = agent.approve(args.candidate_id)
            print(str(path))
        elif args.review_command == "reject":
            path = agent.reject(args.candidate_id)
            print(str(path))
    elif args.command == "adopt":
        path = agent.adopt(args.candidate_id)
        print(path)
    elif args.command == "goal":
        if args.goal_command == "start":
            context = _load_json(args.context)
            result = agent.start_goal(
                args.goal,
                context=context,
                max_steps=args.max_steps,
                autonomy_policy=args.autonomy_policy,
                success_criteria=args.success_criteria or None,
                force_learning=args.force_learning,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.goal_command == "step":
            result = agent.step_goal(
                args.goal_id,
                confirm=args.confirm,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.goal_command == "status":
            print(json.dumps(agent.get_goal(args.goal_id), ensure_ascii=False, indent=2))
        elif args.goal_command == "plan":
            print(json.dumps(agent.get_goal_plan(args.goal_id), ensure_ascii=False, indent=2))
        elif args.goal_command == "events":
            print(json.dumps(agent.get_goal_events(args.goal_id), ensure_ascii=False, indent=2))
        elif args.goal_command == "pause":
            print(json.dumps(agent.pause_goal(args.goal_id), ensure_ascii=False, indent=2))
        elif args.goal_command == "resume":
            print(json.dumps(agent.resume_goal(args.goal_id), ensure_ascii=False, indent=2))
        elif args.goal_command == "list":
            print(json.dumps(agent.list_goals(), ensure_ascii=False, indent=2))
    elif args.command == "runs":
        if args.runs_command == "list":
            print(
                json.dumps(
                    agent.list_runs(run_type=args.type, limit=args.limit),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.runs_command == "inspect":
            print(json.dumps(agent.get_run(args.run_id), ensure_ascii=False, indent=2))
        elif args.runs_command == "latest":
            print(json.dumps(agent.latest_run(run_type=args.type), ensure_ascii=False, indent=2))
    elif args.command == "model":
        if args.model_command == "smoke":
            if not agent.settings.dashscope_api_key:
                print(
                    "DASHSCOPE_API_KEY is not configured. Copy .env.bailian.example "
                    "to .env and fill DASHSCOPE_API_KEY before running this smoke test."
                )
                return
            if args.role in {"chat", "reasoning", "evaluator"}:
                result = agent.chat_model.smoke(args.role)
            elif args.role == "classifier":
                result = agent.chat_model.classify_question(
                    "请判断这个问题是否需要工具：明天上海天气怎么样？",
                    {},
                )
            elif args.role == "tool_builder":
                result = agent.chat_model.draft_tool_builder(
                    "生成一个只读查询工具",
                    {
                        "tool_id": "smoke_tool",
                        "name": "Smoke Tool",
                        "kind": "python_function",
                        "permission": "auto",
                        "risk": "low",
                        "read_only": True,
                        "keywords": ["查询"],
                    },
                    {},
                    {},
                )
            print(result)


def _load_json(value: str) -> dict[str, Any]:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("--context must be a JSON object")
    return data


if __name__ == "__main__":
    main()
