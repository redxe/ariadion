# Changelog

## Unreleased

- Reserved for post-`0.1.0rc1` changes.

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
