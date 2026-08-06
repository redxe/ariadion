from __future__ import annotations

import os
import subprocess
import sys

from paths import ROOT, source_paths


environment = os.environ.copy()
existing = environment.get("PYTHONPATH")
parts = [str(path) for path in source_paths()]
if existing:
    parts.append(existing)
environment["PYTHONPATH"] = os.pathsep.join(parts)

raise SystemExit(
    subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        env=environment,
    )
)
