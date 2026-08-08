# Publishing the initial repository

The intended remote is `redxe/ariadion` with `main` as the default branch.

## Technical RC policy

- Current artifact version: `0.1.0rc2`.
- RC tag form for reviewer-approved release actions: `v0.1.0rc2`.
- RC2 is not currently tagged or published.
- Previous RC: `0.1.0rc1` (tag `v0.1.0rc1`, commit `3c1e986f53b6d1a6a10c1d24f4c62ea50958004b`).
- The artifact version must carry the `rc` suffix; do not tag an RC while emitting
  final-looking `0.1.0` wheels.
- Publishable Ariadion package/app metadata must use exact internal RC pins
  `==0.1.0rc2` during this candidate stage.
- Revisit internal dependency pins before the final `0.1.0` release plan.

## RC2 artifact requirements

All 30 artifacts (15 wheels, 15 sdists) must satisfy:

- SPDX `Apache-2.0` license expression in distribution metadata.
- `setuptools>=77.0.3` build requirement for PEP 639 metadata support.
- `LICENSE` file present at each wheel's `.dist-info/licenses/LICENSE` location and
  at each sdist root.
- Non-empty `Description` and `Description-Content-Type` metadata headers.
- Version exactly `0.1.0rc2` across all artifacts.
- All internal dependency pins exactly `==0.1.0rc2`.
- `ariadion.__version__` equals `importlib.metadata.version("ariadion")` equals
  `"0.1.0rc2"` in an installed environment.
- Strict Twine check (`--strict`) passes for all 30 artifacts.
- SHA-256 manifest generated and reviewable (not uploaded).
- All 15 import packages load together in both NumPy validation environments.

Run `python tools/release_smoke.py --wheelhouse <dir> --validate-artifacts <sdist-dir>`
to validate the complete artifact set before any publication action.

## RC2 authorization sequence

### Before tagging

While RC2 remains untagged, record the reviewer-approved candidate commit SHA, confirm
the build checkout has a clean tree at that exact SHA, and retain accepted artifact-build,
Twine, installation-smoke, and SHA-256 manifest evidence for that candidate.

### During separately authorized tagging

Create `v0.1.0rc2` at the recorded approved SHA only after a reviewer separately
authorizes the tag action. Do not move the tag or substitute a later commit.

### Before publication

Verify that `v0.1.0rc2` peels to the approved SHA and that the tag, every artifact
version, and the recorded SHA-256 manifest all agree on `0.1.0rc2`. Publication remains
a separate authorized action after this verification.

## Repository creation

From a machine with GitHub CLI authentication:

```bash
gh repo create redxe/ariadion \
  --public \
  --description "A thread through quantum complexity." \
  --source . \
  --remote origin \
  --push
```

## Authorization boundaries

- The RC2 preparation pass does not publish packages.
- The RC2 preparation pass does not create tags.
- Tag `v0.1.0rc2` and publication require a separate authorized reviewer action.

Before public branding or package publication, complete formal trademark and package-name clearance.
