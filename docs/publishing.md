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

## RC2 Trusted Publishing workflow

The publication workflow is [`.github/workflows/publish.yml`](../.github/workflows/publish.yml).
It is deliberately inactive while RC2 remains **untagged and unpublished**. It runs only
when a version tag is pushed, and rejects every tag except `v0.1.0rc2` before building.

The workflow publishes these 15 distributions as one reviewed set:

- `ariadion`
- `ariadion-cli`
- `ariadion-core`
- `ariadion-frontend-python`
- `ariadion-ir`
- `ariadion-language`
- `ariadion-noise`
- `ariadion-runtime`
- `ariadion-semantics`
- `ariadion-simulator`
- `ariadion-simulator-numpy`
- `ariadion-syntax`
- `ariadion-visualization`
- `daidalon`
- `theonoe`

Before installing build tools, the non-OIDC build job requires a tag trigger named
`v0.1.0rc2`, confirms that `HEAD`, `GITHUB_SHA`, and the peeled tag commit are identical,
and rejects any dirty checkout. It reads the root project and the exact 15 publishable
`pyproject.toml` files, requiring every declared name and version to be the approved RC2
set. It then creates the complete 15-wheel/15-sdist set, validates it, runs strict Twine
checks, and stores the distributions, validation evidence, tag/commit provenance, and a
filename-sorted 30-entry lowercase-SHA-256 manifest in a single immutable Actions artifact.
Later jobs reuse that exact artifact and never rebuild.

### Trusted Publisher setup

Before separately authorizing the RC2 tag, configure the pending publishers in the package
indexes using these GitHub values:

| Index | Owner | Repository | Workflow | Environment |
| --- | --- | --- | --- | --- |
| TestPyPI | `redxe` | `ariadion` | `publish.yml` | `testpypi` |
| PyPI | `redxe` | `ariadion` | `publish.yml` | `pypi` |

The `testpypi` and `pypi` GitHub environments must exist. The `pypi` environment requires
a release reviewer for its manual production approval. No API token, password, repository
secret, or credentials are used: only the publishing jobs receive `id-token: write`, and
both use PyPI Trusted Publishing with attestations enabled.

### TestPyPI-first publication and verification

After the build artifact has been verified, the `testpypi` environment job uploads all 30
approved files together to `https://test.pypi.org/legacy/`. `skip-existing: true` is always
enabled in this TestPyPI-only job so a rerun can recover a partially accepted first upload;
it never appears in production publication. A follow-on non-OIDC job polls the fixed HTTPS
TestPyPI JSON API with a bounded retry budget, then requires every remote project to expose
only its own approved RC2 wheel and sdist. Every remote filename and lowercase SHA-256 digest
must match the 30-entry manifest exactly.

The verifier accepts only the fixed RC2 version, the 15 approved distribution identities,
HTTPS metadata hosts, and HTTPS artifact URLs under the approved `/packages/` prefix. It
rejects duplicate manifest keys, unsafe filenames, non-RC2 filenames, non-lowercase digests,
credential-bearing or redirected-to-unapproved URLs, oversized responses, and exhausted
redirect or metadata retry budgets. Artifact downloads are size-bounded, streamed to new
temporary files while hashing, atomically made visible only after their digest matches, and
removed with the destination on every failure. The isolated installed smoke matrix never uses
an `--extra-index-url`.

For an incomplete TestPyPI attempt, do not retry blindly. First compare every existing file
with the approved manifest. Retry only when all existing files match, then require the
remote verifier to prove the completed 30-file set exactly. Multi-project uploads are not
perfectly transactional; this verification is the safety boundary.

### Production approval and incident handling

Production publication cannot begin until TestPyPI publication *and* remote verification
succeed. The manually approved `pypi` environment receives the same immutable artifact,
rechecks its manifest, and uploads all 30 files in one invocation with no `skip-existing`.
The final non-OIDC job applies the same fixed, bounded, atomic remote verification to every
PyPI filename and SHA-256 digest against the approved manifest. The workflow never creates a
GitHub Release.

If a production upload is interrupted or reports an existing file, stop publication. Do not
rerun the production job as a workaround. Preserve the manifest and workflow evidence,
compare index state with the approved artifact set, and obtain a separately authorized
incident decision before any further index action.

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
