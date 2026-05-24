from __future__ import annotations

from test_rules_first import *  # noqa: F401,F403

MonkeyAgentRulesFirstTest = None


class AgentSkillsTest(unittest.TestCase):
    def test_agent_skill_imports_and_matches_question(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "browser-testing",
                "Use when asked to create browser automation or pytest web tests.",
                "Always create a browser test plan before implementation.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            installed = agent.import_agent_skill(str(source))
            self.assertEqual(installed["id"], "browser-testing")
            self.assertTrue(
                (settings.runtime_dir / "personal" / "agent_skills" / "browser-testing" / "SKILL.md").exists()
            )
            self.assertEqual(len(agent.list_skills(skill_type="agent")), 1)

            result = agent.ask("帮我创建 browser automation pytest 测试方案")
            self.assertEqual(result["route"], "skills")
            self.assertEqual(result["matched_skills"][0]["id"], "browser-testing")
            self.assertEqual(result["matched_skills"][0]["skill_kind"], "agent")
            self.assertIn("Always create a browser test plan", result["matched_skills"][0]["prompt"])

    def test_agent_skill_inspect_lists_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "script-skill",
                "Use when asked to execute script skill tasks.",
            )
            scripts = source / "scripts"
            scripts.mkdir()
            scripts.joinpath("echo.py").write_text("print('hello')\n", encoding="utf-8")
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            inspected = agent.inspect_agent_skill("script-skill")
            self.assertTrue(any(item["path"] == "scripts/echo.py" for item in inspected["files"]))
            self.assertIn("scripts/echo.py", inspected["prompt"])

    def test_agent_skill_runtime_requires_confirmation_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "execute-skill",
                "Use when asked to execute script skill tasks.",
            )
            scripts = source / "scripts"
            scripts.mkdir()
            marker = settings.runtime_dir / "marker.txt"
            scripts.joinpath("run.py").write_text(
                (
                    "import os\n"
                    "from pathlib import Path\n"
                    "Path(os.environ['MONKEY_AGENT_ARTIFACTS_DIR']).joinpath('result.txt').write_text('done')\n"
                    f"Path({str(marker)!r}).write_text('bad')\n"
                    "print('done')\n"
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            result = agent.ask("请执行 script skill tasks")
            self.assertTrue(result["requires_confirmation"])
            self.assertEqual(result["agent_skill_runtime"]["execution"]["error"], "skill_execution_confirmation_required")
            self.assertFalse(marker.exists())

    def test_agent_skill_runtime_executes_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "execute-skill",
                "Use when asked to execute script skill tasks.",
            )
            scripts = source / "scripts"
            scripts.mkdir()
            scripts.joinpath("run.py").write_text(
                (
                    "import json, os, sys\n"
                    "from pathlib import Path\n"
                    "payload = json.loads(sys.stdin.read())\n"
                    "Path(os.environ['MONKEY_AGENT_ARTIFACTS_DIR']).joinpath('result.txt').write_text(payload['question'])\n"
                    "print('ran:' + payload['question'])\n"
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            result = agent.ask(
                "请执行 script skill tasks",
                context={"confirm_skill_execution": True},
            )
            execution = result["agent_skill_runtime"]["execution"]
            self.assertTrue(execution["success"])
            self.assertIn("ran:请执行 script skill tasks", execution["stdout"])
            self.assertTrue(execution["artifacts"])

    def test_agent_skill_cli_run_rejects_unsafe_script(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "unsafe-skill",
                "Use when asked to execute unsafe script skill tasks.",
            )
            scripts = source / "scripts"
            scripts.mkdir()
            scripts.joinpath("bad.py").write_text(
                "import os\nos.remove('x')\n",
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            result = agent.run_agent_skill("unsafe-skill", "scripts/bad.py", confirm=True)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "unsafe_skill_script")
            self.assertIn("dangerous_attr:remove", result["safety_report"]["errors"])

    def test_agent_skill_cli_run_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "escape-skill",
                "Use when asked to execute escape script skill tasks.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            result = agent.run_agent_skill("escape-skill", "../outside.py", confirm=True)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "unsafe_skill_script")
            self.assertIn("script_path_escapes_skill_root", result["safety_report"]["errors"])

    def test_agent_skill_install_from_github_style_source_uses_git_clone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            repo = tmp / "repo"
            write_agent_skill(
                repo / "skills",
                "github-skill",
                "Use when asked about GitHub style installed skills.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())

            def fake_clone(repo_url: str, target: Path) -> None:
                self.assertEqual(repo_url, "https://github.com/owner/repo.git")
                shutil.copytree(repo, target)

            with patch("monkey_agent.domains.agent_skills.installer._git_clone", fake_clone):
                installed = agent.install_agent_skill("owner/repo/github-skill")

            self.assertEqual(installed["id"], "github-skill")
            self.assertEqual(len(agent.list_agent_skills()), 1)
            self.assertIn("github-skill", agent.inspect_agent_skill("github-skill")["body"])

    def test_agent_skill_duplicate_install_updates_registry_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "repeat-skill",
                "Use when asked about repeatable skills.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            source.joinpath("SKILL.md").write_text(
                source.joinpath("SKILL.md")
                .read_text(encoding="utf-8")
                .replace("repeatable skills", "updated repeatable skills"),
                encoding="utf-8",
            )
            agent.import_agent_skill(str(source))
            skills = agent.list_agent_skills()
            self.assertEqual(len(skills), 1)
            self.assertIn("updated", skills[0]["description"])

    def test_agent_skill_disable_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "toggle-skill",
                "Use when asked about toggle skill matching.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            agent.disable_agent_skill("toggle-skill")
            result = agent.ask("toggle skill matching 怎么处理？")
            self.assertFalse(
                any(item.get("id") == "toggle-skill" for item in result.get("matched_skills", []))
            )
            agent.enable_agent_skill("toggle-skill")
            result = agent.ask("toggle skill matching 怎么处理？")
            self.assertTrue(
                any(item.get("id") == "toggle-skill" for item in result.get("matched_skills", []))
            )
            removed = agent.remove_agent_skill("toggle-skill")
            self.assertEqual(removed["id"], "toggle-skill")
            self.assertFalse((settings.runtime_dir / "personal" / "agent_skills" / "toggle-skill").exists())

    def test_agent_skill_import_rejects_invalid_or_unsafe_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())

            missing = tmp / "missing-skill"
            missing.mkdir()
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(missing))

            bad_name = tmp / "BadName"
            bad_name.mkdir()
            bad_name.joinpath("SKILL.md").write_text(
                "---\nname: BadName\ndescription: bad\n---\nBody\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(bad_name))

            long_desc = tmp / "long-desc"
            long_desc.mkdir()
            long_desc.joinpath("SKILL.md").write_text(
                "---\nname: long-desc\ndescription: " + ("x" * 1025) + "\n---\nBody\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(long_desc))

            linked = write_agent_skill(
                tmp / "source",
                "linked-skill",
                "Use when asked about symlink safety.",
            )
            linked.joinpath("escape").symlink_to(tmp / "outside")
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(linked))

