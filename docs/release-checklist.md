# Release checklist

## Pre-release

- [ ] Run the canonical test suite on Python 3.11 and 3.12 with `python tools/test.py`.
- [ ] Confirm the root workspace and all publishable distributions use `0.1.0rc3`.
- [ ] Confirm every direct internal Ariadion dependency in publishable metadata uses
	the exact RC pin `==0.1.0rc3`.
- [ ] Confirm every publishable build system requires `setuptools>=77.0.3` for
	PEP 639 support.
- [ ] Confirm `ariadion.__version__` equals `"0.1.0rc3"`.
- [ ] Confirm `importlib.metadata.version("ariadion")` equals `"0.1.0rc3"` in an
	installed environment (verified by release smoke runtime version check).
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-wheelhouse>`.
- [ ] Confirm every workspace distribution produced a wheel in that wheelhouse.
- [ ] Confirm `pip check` passes after `ariadion` and `ariadion-cli` install from
	only the local wheelhouse into a fresh environment outside the checkout.
- [ ] Confirm the installed SDK Bell-state smoke and `ariadion demo bell` both pass.
- [ ] Confirm the runtime version check passes (`ariadion.__version__` equals
	installed distribution metadata version).
- [ ] Confirm installed-wheel noise-impact reporting smoke passes.
- [ ] Confirm installed-wheel bare-reliability reporting smoke passes.
- [ ] Confirm installed-wheel protection-requirement reporting smoke passes.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-wheelhouse> --validate-artifacts <sdist-dir>`:
	- [ ] Exactly 15 wheels and 15 sdists produced.
	- [ ] No ariadion-workspace artifact present.
	- [ ] All 30 artifacts use version `0.1.0rc3`.
	- [ ] All internal dependency pins equal `==0.1.0rc3`.
	- [ ] Every artifact has Description and Description-Content-Type metadata.
	- [ ] Every wheel and sdist contains the Apache-2.0 LICENSE payload.
	- [ ] Every wheel and sdist contains the expected import package.
	- [ ] ariadion-cli wheel has the `ariadion` console script entry point.
	- [ ] Strict Twine check (`--strict`) passes for all 30 artifacts.
	- [ ] SHA-256 manifest generated and recorded for the complete 30-file set.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-numpy-wheelhouse> --with-numpy`.
- [ ] Run the same NumPy smoke with `--numpy-version 1.26.0` to validate the
	declared minimum compatible NumPy release.
- [ ] Confirm the optional release smoke currently pins `numpy==2.4.6` for
	reproducible gating; this pin is not the optional package compatibility limit.
- [ ] Confirm the optional package imports separately, selects NumPy `complex128`,
	and matches the reference Bell-state probabilities.
- [ ] Confirm the resolved NumPy version reported by optional smoke equals the pin
	`2.4.6` exactly.
- [ ] Confirm all 15 distribution import packages load together in both NumPy
	validation environments.

## Before tagging

- [ ] Record the exact reviewer-approved RC3 commit SHA.
- [ ] Confirm the artifact-build checkout has a clean tree at that approved SHA.
- [ ] Retain accepted artifact-build, strict-Twine, installation-smoke, and SHA-256
	manifest evidence for that approved SHA.

## During authorized tagging

- [ ] Create `v0.1.0rc3` at the exact approved SHA only after all release checks pass.
- [ ] Confirm that pushing the tag authorizes the immutable build and TestPyPI publication.
- [ ] Do not move `v0.1.0rc3` or substitute a later commit.

## Before publication

- [ ] Confirm `v0.1.0rc3` peels to the approved SHA.
- [ ] Confirm the tag, all 30 artifact versions, and the recorded SHA-256 manifest
	agree on `0.1.0rc3`.
- [ ] Confirm RC3 remains untagged and unpublished until this checklist is complete.
- [x] Confirm all 30 Trusted Publishers are registered for `redxe/ariadion`, workflow
	`publish.yml`: 15 with TestPyPI environment `testpypi`, and 15 with PyPI environment
	`pypi` (recorded user-confirmed on 2026-08-12).
- [ ] Confirm the `pypi` GitHub environment requires the intended manual production reviewer.
- [ ] Confirm [`.github/workflows/publish.yml`](../.github/workflows/publish.yml) is the
	only authorized publication workflow and triggers only from pushed version tags.
- [ ] Confirm the workflow rejects every tag other than `v0.1.0rc3`, validates the tag
	trigger, clean `HEAD`, `GITHUB_SHA`, and peeled tag commit before installing build tools;
	then validate the root project plus exactly the 15 approved publishable projects for their
	expected names and `0.1.0rc3` versions. Confirm it uses no password, API token, repository
	secret, or credential placeholder.
- [ ] Confirm the non-OIDC build job creates exactly 15 wheels and 15 sdists, runs strict
	Twine checks, and stores the distributions, provenance, validation evidence, and
	filename-sorted 30-entry manifest with safe RC3 filenames and lowercase SHA-256 digests as
	one immutable artifact.
- [ ] Confirm the 15 approved distributions are: `ariadion`, `ariadion-cli`,
	`ariadion-core`, `ariadion-frontend-python`, `ariadion-ir`, `ariadion-language`,
	`ariadion-noise`, `ariadion-runtime`, `ariadion-semantics`, `ariadion-simulator`,
	`ariadion-simulator-numpy`, `ariadion-syntax`, `ariadion-visualization`, `daidalon`,
	and `theonoe`.
- [ ] Confirm TestPyPI is published first through the `testpypi` environment with Trusted
	Publishing/OIDC and attestations, then remotely verified for exact filenames and hashes.
- [ ] Confirm non-OIDC preflights require RC3 to be absent from all 15 projects on both
	indexes before TestPyPI publication and again from PyPI after TestPyPI verification.
- [ ] Confirm neither publisher uses `skip-existing`. A partial upload requires a separately
	reviewed incident decision; missing, extra, redistributed, mismatched, or yanked files must
	stop the workflow.
- [ ] Confirm remote verification downloads the approved files, never uses
	`--extra-index-url`, accepts only fixed RC3 project/filename identities, lowercase digests,
	explicitly unyanked artifacts, approved HTTPS hosts and paths, bounded redirects and response
	sizes, and atomic streamed downloads with cleanup on every failure. Confirm all 15 installed
	distributions are pinned to `==0.1.0rc3`, NumPy 2.4.6 is obtained separately from production
	PyPI, and pip check, all-import, SDK Bell, CLI Bell, reporting-chain,
	runtime-version, and NumPy backend smokes.
- [ ] Confirm the manually approved `pypi` environment reuses the identical build artifact,
	does not use `skip-existing`, publishes with Trusted Publishing/OIDC and attestations,
	and has a final exact PyPI manifest verification.
- [ ] Confirm no GitHub Release is created automatically.

## Release notes

- [ ] Update the changelog with the ship-ready user-visible changes.
- [ ] Confirm the public README and contributor guide describe the supported install path.
- [ ] Verify CI covers Python 3.11/3.12, clean installation, SDK/CLI execution,
	  and the optional NumPy boundary.
