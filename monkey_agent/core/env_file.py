from __future__ import annotations

from pathlib import Path


def update_env_file(path: Path, values: dict[str, str], overwrite: bool = False) -> list[str]:
    """Update simple KEY=value entries while preserving unrelated lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated: list[str] = []
    seen: set[str] = set()
    changed: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated.append(line)
            continue
        key, current = line.split("=", 1)
        key = key.strip()
        if key not in values:
            updated.append(line)
            continue
        seen.add(key)
        new_value = values[key]
        if current and current != new_value and not overwrite:
            updated.append(line)
            continue
        updated.append(f"{key}={new_value}")
        if current != new_value:
            changed.append(key)
    missing = [key for key in values if key not in seen]
    if missing and updated and updated[-1].strip():
        updated.append("")
    for key in missing:
        updated.append(f"{key}={values[key]}")
        changed.append(key)
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return changed


def ensure_env_file(path: Path, example_path: Path | None = None) -> bool:
    if path.exists():
        return False
    if example_path and example_path.exists():
        path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    return True
