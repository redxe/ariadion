# Contributing

Ariadion is pre-alpha. Keep changes narrow, tested, and aligned with the dependency direction documented in `docs/architecture.md`.

## Local checks

```bash
python tools/test.py
python -m compileall -q packages apps examples
python tools/release_smoke.py --wheelhouse <new-empty-wheelhouse>
python tools/release_smoke.py --wheelhouse <new-empty-numpy-wheelhouse> --with-numpy
```

The release smoke workflow is the packaging-installation proof for the public SDK
and CLI. It rejects a nonempty wheelhouse, creates its fresh environment outside
the checkout, runs SDK and CLI behavior, and optionally checks the separately
installed NumPy backend. Use it before cutting a release candidate.

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
