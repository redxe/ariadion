from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from paths import ROOT, source_paths


if len(sys.argv) != 2:
    raise SystemExit("usage: python tools/run_example.py examples/bell.py")

example = (ROOT / Path(sys.argv[1])).resolve()
if not example.is_relative_to(ROOT / "examples") or not example.exists():
    raise SystemExit(f"example not found: {sys.argv[1]}")

environment = os.environ.copy()
parts = [str(path) for path in source_paths()]
if environment.get("PYTHONPATH"):
    parts.append(environment["PYTHONPATH"])
environment["PYTHONPATH"] = os.pathsep.join(parts)

raise SystemExit(subprocess.call([sys.executable, str(example)], cwd=ROOT, env=environment))
