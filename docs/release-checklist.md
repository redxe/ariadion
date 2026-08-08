# Release checklist

## Pre-release

- [ ] Run the canonical test suite on Python 3.11 and 3.12 with `python tools/test.py`.
- [ ] Confirm the root workspace and all publishable distributions use `0.1.0rc1`.
- [ ] Confirm every direct internal Ariadion dependency in publishable metadata uses
	the exact RC pin `==0.1.0rc1`.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-wheelhouse>`.
- [ ] Confirm every workspace distribution produced a wheel in that wheelhouse.
- [ ] Confirm `pip check` passes after `ariadion` and `ariadion-cli` install from
	only the local wheelhouse into a fresh environment outside the checkout.
- [ ] Confirm the installed SDK Bell-state smoke and `ariadion demo bell` both pass.
- [ ] Confirm installed-wheel noise-impact reporting smoke passes.
- [ ] Confirm installed-wheel bare-reliability reporting smoke passes.
- [ ] Confirm installed-wheel protection-requirement reporting smoke passes.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-numpy-wheelhouse> --with-numpy`.
- [ ] Confirm the optional release smoke currently pins `numpy==2.4.6` for
	reproducible gating; this pin is not the optional package compatibility limit.
- [ ] Confirm the optional package imports separately, selects NumPy `complex128`,
	and matches the reference Bell-state probabilities.
- [ ] Confirm the resolved NumPy version reported by optional smoke equals the pin
	`2.4.6` exactly.
- [ ] Confirm package publication and final release tagging are tracked as separate
	authorized actions from RC preparation.

## Release notes

- [ ] Update the changelog with the ship-ready user-visible changes.
- [ ] Confirm the public README and contributor guide describe the supported install path.
- [ ] Verify CI covers Python 3.11/3.12, clean installation, SDK/CLI execution,
	  and the optional NumPy boundary.
