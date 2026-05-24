from __future__ import annotations

import ast
import re
from pathlib import Path

from monkey_agent.domains.agent_skills.runtime_models import AgentSkillSafetyReport


DANGEROUS_TEXT_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bsudo\b",
    r"\bcurl\b.+\|\s*(?:sh|bash)\b",
    r"\bwget\b.+\|\s*(?:sh|bash)\b",
    r">\s*/(?:etc|usr|bin|sbin|System|Library)\b",
]
DANGEROUS_PYTHON_IMPORTS = {"subprocess", "shutil", "socket", "ftplib"}
DANGEROUS_PYTHON_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_OS_ATTRS = {"remove", "unlink", "rmdir", "removedirs", "rename", "replace", "system"}


class AgentSkillSafetyChecker:
    def validate(self, skill_root: Path, script_path: str, artifacts_root: Path) -> AgentSkillSafetyReport:
        try:
            root = skill_root.resolve()
            script = (root / script_path).resolve()
            script.relative_to(root)
        except ValueError:
            return AgentSkillSafetyReport(
                passed=False,
                errors=["script_path_escapes_skill_root"],
                risk="high",
            )
        if not script.exists() or not script.is_file():
            return AgentSkillSafetyReport(
                passed=False,
                errors=["script_not_found"],
                risk="high",
            )
        if script.is_symlink():
            return AgentSkillSafetyReport(
                passed=False,
                errors=["script_is_symlink"],
                risk="high",
            )

        text = script.read_text(encoding="utf-8", errors="ignore")
        errors = []
        warnings = []
        for pattern in DANGEROUS_TEXT_PATTERNS:
            if re.search(pattern, text):
                errors.append(f"dangerous_pattern:{pattern}")
        if script.suffix == ".py":
            py_errors = _python_static_errors(text)
            errors.extend(py_errors)
        if not str(artifacts_root.resolve()).startswith(str(artifacts_root.parent.resolve())):
            errors.append("invalid_artifacts_root")
        if not script.stat().st_size:
            warnings.append("empty_script")
        return AgentSkillSafetyReport(
            passed=not errors,
            errors=errors,
            warnings=warnings,
            risk="high" if errors else "low",
        )


def _python_static_errors(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"python_syntax_error:{exc.msg}"]
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in DANGEROUS_PYTHON_IMPORTS:
                    errors.append(f"dangerous_import:{root_name}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_PYTHON_CALLS:
                errors.append(f"dangerous_call:{node.func.id}")
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in DANGEROUS_OS_ATTRS:
                    errors.append(f"dangerous_attr:{node.func.attr}")
    return errors
