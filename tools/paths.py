from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source_paths() -> list[Path]:
    paths = [path for path in ROOT.glob("packages/*/src") if path.is_dir()]
    paths.extend(path for path in ROOT.glob("apps/*/src") if path.is_dir())
    return sorted(paths)
