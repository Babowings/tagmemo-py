from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_project_path(raw_path: str | None, default_relative: str) -> str:
    candidate = (raw_path or "").strip()
    if not candidate:
        return str((PROJECT_ROOT / default_relative).resolve())

    path = Path(candidate).expanduser()
    if path.is_absolute():
        return str(path.resolve())

    return str((PROJECT_ROOT / path).resolve())