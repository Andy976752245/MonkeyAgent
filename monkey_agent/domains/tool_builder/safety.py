from __future__ import annotations

import ast
from dataclasses import dataclass, field


ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "datetime",
    "json",
    "math",
    "monkey_agent",
    "re",
    "statistics",
    "typing",
    "urllib",
}

BANNED_IMPORT_ROOTS = {
    "builtins",
    "importlib",
    "io",
    "os",
    "pathlib",
    "shutil",
    "socket",
    "subprocess",
    "sys",
}

BANNED_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "input",
    "breakpoint",
}

BANNED_ATTRS = {
    "remove",
    "unlink",
    "rmdir",
    "rmtree",
    "system",
    "popen",
    "spawn",
    "fork",
    "kill",
    "write",
    "write_text",
    "write_bytes",
}


@dataclass(frozen=True)
class SafetyReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class ToolCodeSafetyValidator:
    def validate(self, code: str) -> SafetyReport:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return SafetyReport(False, [f"syntax_error:{exc}"], [])

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in BANNED_IMPORT_ROOTS or root not in ALLOWED_IMPORT_ROOTS:
                        errors.append(f"banned_import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".", 1)[0]
                if root in BANNED_IMPORT_ROOTS or root not in ALLOWED_IMPORT_ROOTS:
                    errors.append(f"banned_import:{module}")
            elif isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in BANNED_CALLS:
                    errors.append(f"banned_call:{name}")
                attr = name.rsplit(".", 1)[-1]
                if attr in BANNED_ATTRS:
                    errors.append(f"banned_call:{name}")
            elif isinstance(node, ast.Attribute):
                if node.attr in BANNED_ATTRS:
                    errors.append(f"banned_attribute:{node.attr}")

        if "urllib.request" in code and "Permission.CONFIRM" not in code:
            warnings.append("network_code_should_be_read_only_or_confirmed")
        return SafetyReport(passed=not errors, errors=sorted(set(errors)), warnings=warnings)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
