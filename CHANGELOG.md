# Changelog

## Unreleased

- Reserved for post-`0.1.0rc2` changes.

## 0.1.0rc2 - Unreleased

RC2 packaging repair. Not tagged or published.

### Added
- SPDX `Apache-2.0` license expression in every distribution's metadata.
- `LICENSE` file included under each wheel's `.dist-info/licenses` directory and
  at each sdist root.
- Package-local `README.md` for the `ariadion` SDK and `ariadion-cli` distributions.
- Concise package-local `README.md` for all 13 supporting distributions.
- `authors`, `[project.urls]` (Homepage, Repository, Issues, Changelog), and
  PyPI classifiers in every distribution's metadata.
- Artifact validation in `tools/release_smoke.py`: exact wheel/sdist count, version
  uniformity, license payload presence, description/content-type metadata, import
  package verification, CLI entry-point check, and SHA-256 manifest generation.
- `--validate-artifacts` CLI option for `tools/release_smoke.py` that builds sdists,
  runs strict Twine checks, and validates the full 30-artifact set.
- Installed runtime/distribution version consistency check in `tools/release_smoke.py`.
- RC2 regression tests in `tests/test_release_foundations.py`.

### Changed
- Version bumped from `0.1.0rc1` to `0.1.0rc2` across all 15 publishable
  distributions and the root workspace.
- All internal dependency exact pins changed from `==0.1.0rc1` to `==0.1.0rc2`.
- Package build requirements raised from `setuptools>=68` to `setuptools>=77.0.3`,
  the first setuptools release with PEP 639 support.
- `ariadion.__version__` corrected from `"0.1.0"` to `"0.1.0rc2"`, resolving the
  runtime/metadata version mismatch identified in the RC1 audit.

## 0.1.0rc1 - 2026-08-08

Technical release candidate for release engineering validation. This is not a
production-ready `1.0` release.

### Added
- Local workspace packaging discovery for publishable Ariadion distributions.
- An end-to-end release smoke workflow that builds wheels, installs the public SDK
	and CLI from an isolated local wheelhouse, and executes both outside the checkout.
- Optional NumPy backend installation and explicit parity smoke validation.
- Repository-level release documentation and Python 3.11/3.12 CI coverage for
	packaging and installability.
- Deterministic exact, sampled, and density execution integration with explicit
	request/result-mode boundaries.
- Trace inspection and debugger contracts with schema-versioned serialized views.
- Immutable noise-impact reporting artifacts and runtime helper integration for
	density execution provenance.
- Bare-execution reliability reporting over supported density outputs with
	validated status and goal-verdict contracts.
- Protection-requirement reporting derived from bare reliability evidence with
	schema-stable serialization and public export coverage.
