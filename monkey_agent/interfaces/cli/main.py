from __future__ import annotations

import argparse
import json
import os
import platform
from typing import Any
from pathlib import Path

from monkey_agent.app import MonkeyAgent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="monkey")
    sub = parser.add_subparsers(dest="command", required=True)

    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--context", default="{}")
    ask_parser.add_argument("--feedback")
    ask_parser.add_argument("--pretty", action="store_true")
    ask_parser.add_argument("--trace", action="store_true")
    ask_parser.add_argument("--debug", action="store_true")

    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--smoke", action="store_true")

    quickstart_parser = sub.add_parser("quickstart")
    quickstart_parser.add_argument("--debug", action="store_true")

    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--trace", action="store_true")

    telegram_parser = sub.add_parser("telegram")
    telegram_sub = telegram_parser.add_subparsers(dest="telegram_command", required=True)
    telegram_start = telegram_sub.add_parser("start")
    telegram_start.add_argument("--trace", action="store_true")
    telegram_start.add_argument("--once", action="store_true")

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
    skills_run = skills_sub.add_parser("run")
    skills_run.add_argument("skill_name")
    skills_run.add_argument("--script", required=True)
    skills_run.add_argument("--input", default="{}")
    skills_run.add_argument("--confirm", action="store_true")

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
    review_sub.add_parser("latest")
    review_inspect = review_sub.add_parser("inspect")
    review_inspect.add_argument("candidate_id")
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
        _print_ask_result(result, debug=args.debug, trace=args.trace)
    elif args.command == "doctor":
        _print_doctor(_run_doctor(agent, smoke=args.smoke))
    elif args.command == "quickstart":
        _print_quickstart(_run_quickstart(agent), debug=args.debug)
    elif args.command == "chat":
        _run_chat(agent, trace=args.trace)
    elif args.command == "telegram":
        if args.telegram_command == "start":
            _run_telegram(agent, trace=args.trace, once=args.once)
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
        elif args.skills_command == "run":
            print(
                json.dumps(
                    agent.run_agent_skill(
                        args.skill_name,
                        args.script,
                        input_data=_load_json(args.input),
                        confirm=args.confirm,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
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
        elif args.review_command == "latest":
            latest = agent.latest_pending()
            _print_pending(latest)
        elif args.review_command == "inspect":
            item = agent.inspect_pending(args.candidate_id)
            _print_pending(item)
        elif args.review_command == "approve":
            try:
                path = agent.approve(args.candidate_id)
                print(str(path))
            except FileNotFoundError as exc:
                _print_pending_error(args.candidate_id, exc)
        elif args.review_command == "reject":
            try:
                path = agent.reject(args.candidate_id)
                print(str(path))
            except FileNotFoundError as exc:
                _print_pending_error(args.candidate_id, exc)
    elif args.command == "adopt":
        try:
            path = agent.adopt(args.candidate_id)
            print(path)
        except FileNotFoundError as exc:
            _print_pending_error(args.candidate_id, exc)
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


def _print_ask_result(result: dict[str, Any], debug: bool = False, trace: bool = False) -> None:
    if debug:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if trace:
        print(_format_trace(result))
        return
    answer = str(result.get("answer") or "").strip()
    print(answer or "没有生成回答。")
    adoption_prompt = result.get("adoption_prompt")
    if adoption_prompt:
        print()
        print(str(adoption_prompt))


def _format_trace(result: dict[str, Any]) -> str:
    lines = [f"答案：{str(result.get('answer') or '').strip() or '没有生成回答。'}", ""]
    lines.append(f"路由：{result.get('route') or 'unknown'}")
    rules = result.get("matched_rules") or []
    if rules:
        lines.append("命中规则：" + ", ".join(str(item.get("name") or item.get("id")) for item in rules))
    skills = result.get("matched_skills") or []
    if skills:
        lines.append("命中技能：" + ", ".join(str(item.get("name") or item.get("id")) for item in skills))
    exploration = result.get("exploration") or {}
    if exploration.get("tool_id"):
        lines.append(f"工具：{exploration.get('tool_name') or exploration.get('tool_id')}")
    evaluation = result.get("evaluation") or {}
    if evaluation:
        lines.append(
            "评估："
            + str(evaluation.get("status") or "unknown")
            + f" score={evaluation.get('score', '')}"
        )
    lines.append(f"置信度：{result.get('confidence', 0.0)}")
    if result.get("run_id"):
        lines.append(f"Run ID：{result['run_id']}")
    if result.get("tool_run_id"):
        lines.append(f"Tool Run ID：{result['tool_run_id']}")
    routing = result.get("routing_policy") or {}
    if routing:
        lines.append(f"路由策略：{routing.get('category')} / clarification_allowed={routing.get('clarification_allowed')}")
    return "\n".join(lines)


def _run_doctor(agent: MonkeyAgent, smoke: bool = False) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    checks.append(_check("Python", "PASS", platform.python_version()))
    runtime = agent.personal_workspace.root
    checks.append(_check_path("Runtime", runtime, writable=True))
    checks.append(_check_path("Global rules", agent.settings.rules_dir, writable=False))
    checks.append(_check_path("Global skills", agent.settings.skills_dir, writable=False))
    env_path = Path.cwd() / ".env"
    checks.append(_check(".env", "PASS" if env_path.exists() else "WARN", str(env_path) if env_path.exists() else "not found"))
    api_key = agent.settings.dashscope_api_key or os.getenv("DASHSCOPE_API_KEY", "")
    checks.append(_check("DASHSCOPE_API_KEY", "PASS" if api_key else "WARN", "configured" if api_key else "not configured; local fallback may be used"))
    backend = getattr(agent.goal_workflow, "checkpoint_backend", "unknown")
    checks.append(_check("Goal checkpoint", "PASS" if backend == "sqlite" else "WARN", str(backend)))
    feishu_missing = [
        name
        for name, value in [
            ("FEISHU_APP_ID", agent.settings.feishu_app_id),
            ("FEISHU_APP_SECRET", agent.settings.feishu_app_secret),
        ]
        if not value
    ]
    checks.append(_check("Feishu", "WARN" if feishu_missing else "PASS", "optional missing: " + ", ".join(feishu_missing) if feishu_missing else "configured"))
    telegram_detail = (
        "configured"
        if agent.settings.telegram_bot_token and agent.settings.telegram_allowed_chat_ids
        else "optional missing: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_CHAT_IDS"
    )
    checks.append(
        _check(
            "Telegram",
            "PASS"
            if agent.settings.telegram_bot_token and agent.settings.telegram_allowed_chat_ids
            else "WARN",
            telegram_detail,
        )
    )
    if smoke and api_key:
        for role in ["chat", "classifier", "reasoning", "tool_builder", "evaluator"]:
            checks.append(_model_smoke_check(agent, role))
    elif smoke:
        checks.append(_check("Model smoke", "WARN", "skipped because DASHSCOPE_API_KEY is not configured"))
    return checks


def _check_path(name: str, path: Path, writable: bool) -> dict[str, str]:
    if not path.exists():
        return _check(name, "FAIL", f"not found: {path}")
    if writable:
        try:
            probe = path / ".doctor_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return _check(name, "FAIL", f"not writable: {exc}")
    return _check(name, "PASS", str(path))


def _model_smoke_check(agent: MonkeyAgent, role: str) -> dict[str, str]:
    try:
        if role in {"chat", "reasoning", "evaluator"}:
            agent.chat_model.smoke(role)
        elif role == "classifier":
            agent.chat_model.classify_question("明天上海天气怎么样？", {})
        elif role == "tool_builder":
            agent.chat_model.draft_tool_builder(
                "生成一个只读查询工具",
                {
                    "tool_id": "doctor_smoke_tool",
                    "name": "Doctor Smoke Tool",
                    "kind": "python_function",
                    "permission": "auto",
                    "risk": "low",
                    "read_only": True,
                    "keywords": ["查询"],
                },
                {},
                {},
            )
    except Exception as exc:  # noqa: BLE001 - CLI diagnostics should report all roles
        return _check(f"Model {role}", "FAIL", str(exc))
    return _check(f"Model {role}", "PASS", "ok")


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _print_doctor(checks: list[dict[str, str]]) -> None:
    print("MonkeyAgent Doctor")
    for item in checks:
        print(f"[{item['status']}] {item['name']}: {item['detail']}")
    failed = sum(1 for item in checks if item["status"] == "FAIL")
    warned = sum(1 for item in checks if item["status"] == "WARN")
    passed = sum(1 for item in checks if item["status"] == "PASS")
    print(f"\nSummary: PASS={passed} WARN={warned} FAIL={failed}")


def _run_quickstart(agent: MonkeyAgent) -> list[dict[str, Any]]:
    scenarios = [
        ("基础计算", "1+1等于几", lambda r: r.get("route") == "rules"),
        ("日期推算", "明天是几号", lambda r: r.get("route") == "rules"),
        ("常识回答", "水为什么会结冰", lambda r: r.get("route") == "general_reason"),
        ("个人助理建议", "我明天拜访客户应该准备什么", lambda r: r.get("route") in {"skills", "general_reason"}),
        ("记忆候选", "以后默认用表格输出，这是我的偏好", lambda r: bool(r.get("learning_candidate_id") or r.get("adoption_prompt") or r.get("exploration"))),
    ]
    results: list[dict[str, Any]] = []
    for name, question, predicate in scenarios:
        try:
            result = agent.ask(question)
            ok = bool(predicate(result))
            results.append(
                {
                    "name": name,
                    "question": question,
                    "status": "PASS" if ok else "WARN",
                    "route": result.get("route"),
                    "run_id": result.get("run_id"),
                    "answer": result.get("answer", ""),
                    "result": result,
                }
            )
        except Exception as exc:  # noqa: BLE001 - quickstart should continue
            results.append({"name": name, "question": question, "status": "FAIL", "error": str(exc)})
    return results


def _print_quickstart(results: list[dict[str, Any]], debug: bool = False) -> None:
    if debug:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    print("MonkeyAgent Quickstart")
    for item in results:
        print(f"[{item['status']}] {item['name']}: {item['question']}")
        if item.get("route"):
            print(f"  route={item['route']} run_id={item.get('run_id')}")
        if item.get("error"):
            print(f"  error={item['error']}")
    passed = sum(1 for item in results if item["status"] == "PASS")
    warned = sum(1 for item in results if item["status"] == "WARN")
    failed = sum(1 for item in results if item["status"] == "FAIL")
    print(f"\nSummary: PASS={passed} WARN={warned} FAIL={failed}")


def _run_chat(agent: MonkeyAgent, trace: bool = False) -> None:
    print("MonkeyAgent Chat. Type exit or quit to leave.")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            print()
            return
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            return
        result = agent.ask(question)
        _print_ask_result(result, trace=trace)


def _run_telegram(agent: MonkeyAgent, trace: bool = False, once: bool = False) -> None:
    if not agent.settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN is not configured. Create a bot with BotFather and add the token to .env.")
        return
    from monkey_agent.domains.integrations.telegram import (
        TelegramClient,
        TelegramMessageHandler,
        TelegramPollingRunner,
    )

    client = TelegramClient(
        agent.settings.telegram_bot_token,
        request_timeout=agent.settings.telegram_request_timeout,
    )
    handler = TelegramMessageHandler(
        agent.settings,
        lambda question, context: agent.ask(question, context=context),
        client,
        trace_default=trace,
    )
    runner = TelegramPollingRunner(agent.settings, client, handler)
    mode = "once" if once else "polling"
    print(f"MonkeyAgent Telegram {mode} started.")
    if not agent.settings.telegram_allowed_chat_ids:
        print("Setup mode: only /start and /whoami are enabled until TELEGRAM_ALLOWED_CHAT_IDS is configured.")
    result = runner.run(once=once)
    if once or result.get("status") != "stopped":
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _print_pending(item: dict[str, Any] | None) -> None:
    if not item:
        print("当前没有待审核候选。")
        return
    print(json.dumps(item, ensure_ascii=False, indent=2))


def _print_pending_error(candidate_id: str, exc: FileNotFoundError) -> None:
    if candidate_id == "latest":
        print("当前没有待审核候选。")
        return
    print(str(exc))


if __name__ == "__main__":
    main()
