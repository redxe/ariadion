# Contributing

Ariadion is pre-alpha. Keep changes narrow, tested, and aligned with the dependency direction documented in `docs/architecture.md`.

## Local checks

```bash
python tools/test.py
python -m compileall -q packages apps examples
```

## Commit style

Use concise imperative messages, for example:

```text
Add controlled phase operation
Clarify basis semantics
Render measurement operations
```

## Architectural rule

Higher layers may depend on lower layers, never the reverse:

```text
language -> IR -> Daidalon -> runtime -> simulator/provider
                              -> Theonoe
                              -> visualization
```
