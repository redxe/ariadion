set shell := ["bash", "-cu"]

_sources := `find packages apps/cli -type d -name src | paste -sd: -`

example:
    PYTHONPATH={{_sources}} python examples/bell.py

test:
    python tools/test.py

check:
    python tools/test.py
    python -m compileall -q packages apps examples
