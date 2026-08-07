# Release checklist

## Pre-release

- [ ] Run the canonical test suite on Python 3.11 and 3.12 with `python tools/test.py`.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-wheelhouse>`.
- [ ] Confirm every workspace distribution produced a wheel in that wheelhouse.
- [ ] Confirm `pip check` passes after `ariadion` and `ariadion-cli` install from
	only the local wheelhouse into a fresh environment outside the checkout.
- [ ] Confirm the installed SDK Bell-state smoke and `ariadion demo bell` both pass.
- [ ] Run `python tools/release_smoke.py --wheelhouse <new-empty-numpy-wheelhouse> --with-numpy`.
- [ ] Confirm the optional release smoke currently pins `numpy==2.4.6` for
	reproducible gating; this pin is not the optional package compatibility limit.
- [ ] Confirm the optional package imports separately, selects NumPy `complex128`,
	and matches the reference Bell-state probabilities.

## Release notes

- [ ] Update the changelog with the ship-ready user-visible changes.
- [ ] Confirm the public README and contributor guide describe the supported install path.
- [ ] Verify CI covers Python 3.11/3.12, clean installation, SDK/CLI execution,
	  and the optional NumPy boundary.
