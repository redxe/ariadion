# Release checklist

## Pre-release

- [ ] Run the canonical test suite on Python 3.11 and 3.12 with `python tools/test.py`.
- [ ] Confirm the root workspace and all publishable distributions use `0.1.0rc2`.
- [ ] Confirm every direct internal Ariadion dependency in publishable metadata uses
	the exact RC pin `==0.1.0rc2`.
- [ ] Confirm every publishable build system requires `setuptools>=77.0.3` for
	PEP 639 support.
- [ ] Confirm `ariadion.__version__` equals `"0.1.0rc2"`.
- [ ] Confirm `importlib.metadata.version("ariadion")` equals `"0.1.0rc2"` in an
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
	- [ ] All 30 artifacts use version `0.1.0rc2`.
	- [ ] All internal dependency pins equal `==0.1.0rc2`.
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

- [ ] Record the exact reviewer-approved RC2 commit SHA.
- [ ] Confirm the artifact-build checkout has a clean tree at that approved SHA.
- [ ] Retain accepted artifact-build, strict-Twine, installation-smoke, and SHA-256
	manifest evidence for that approved SHA.

## During separately authorized tagging

- [ ] Create `v0.1.0rc2` at the exact approved SHA only after separate reviewer
	authorization.
- [ ] Do not move `v0.1.0rc2` or substitute a later commit.

## Before publication

- [ ] Confirm `v0.1.0rc2` peels to the approved SHA.
- [ ] Confirm the tag, all 30 artifact versions, and the recorded SHA-256 manifest
	agree on `0.1.0rc2`.
- [ ] Confirm package publication remains a separate authorized action from RC2
	preparation and tagging.

## Release notes

- [ ] Update the changelog with the ship-ready user-visible changes.
- [ ] Confirm the public README and contributor guide describe the supported install path.
- [ ] Verify CI covers Python 3.11/3.12, clean installation, SDK/CLI execution,
	  and the optional NumPy boundary.
