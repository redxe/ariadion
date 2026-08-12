# Publishing the initial repository

The intended remote is `redxe/ariadion` with `main` as the default branch.

## Technical RC policy

- Current artifact version: `0.1.0rc3`.
- RC tag form for reviewer-approved release actions: `v0.1.0rc3`.
- RC3 is not currently tagged or published.
- RC2 was only partially uploaded to production PyPI and has been yanked; it was
  never published to TestPyPI and must not be resumed.
- Previous coordinated tag: `v0.1.0rc1` at
  `3c1e986f53b6d1a6a10c1d24f4c62ea50958004b`.
- The artifact version must carry the `rc` suffix; do not tag an RC while emitting
  final-looking `0.1.0` wheels.
- Publishable Ariadion package/app metadata must use exact internal RC pins
  `==0.1.0rc3` during this candidate stage.
- Revisit internal dependency pins before the final `0.1.0` release plan.

## RC3 artifact requirements

All 30 artifacts (15 wheels, 15 sdists) must satisfy:

- SPDX `Apache-2.0` license expression in distribution metadata.
- `setuptools>=77.0.3` build requirement for PEP 639 metadata support.
- `LICENSE` file present at each wheel's `.dist-info/licenses/LICENSE` location and
  at each sdist root.
- Non-empty `Description` and `Description-Content-Type` metadata headers.
- Version exactly `0.1.0rc3` across all artifacts.
- All internal dependency pins exactly `==0.1.0rc3`.
- `ariadion.__version__` equals `importlib.metadata.version("ariadion")` equals
  `"0.1.0rc3"` in an installed environment.
- Strict Twine check (`--strict`) passes for all 30 artifacts.
- SHA-256 manifest generated and reviewable (not uploaded).
- All 15 import packages load together in both NumPy validation environments.

Run `python tools/release_smoke.py --wheelhouse <dir> --validate-artifacts <sdist-dir>`
to validate the complete artifact set before any publication action.

## RC3 authorization sequence

### Before tagging

While RC3 remains untagged, record the reviewer-approved candidate commit SHA, confirm
the build checkout has a clean tree at that exact SHA, and retain accepted artifact-build,
Twine, installation-smoke, and SHA-256 manifest evidence for that candidate.

### During authorized tagging

Create `v0.1.0rc3` at the recorded approved SHA only after the release checks pass.
Pushing this tag authorizes the workflow to build and publish to TestPyPI; do not move
the tag or substitute a later commit.

### Before publication

Verify that `v0.1.0rc3` peels to the approved SHA and that the tag, every artifact
version, and the recorded SHA-256 manifest all agree on `0.1.0rc3`. Production PyPI
publication remains separately controlled by the protected `pypi` environment.

## RC3 Trusted Publishing workflow

The publication workflow is [`.github/workflows/publish.yml`](../.github/workflows/publish.yml).
It is deliberately inactive while RC3 remains **untagged and unpublished**. It runs only
when a version tag is pushed, and rejects every tag except `v0.1.0rc3` before building.

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

Before any build or OIDC publication, non-OIDC preflight jobs require `0.1.0rc3` to be
absent for all 15 project names on both indexes. Before installing build tools, the build
job requires a tag trigger named
`v0.1.0rc3`, confirms that `HEAD`, `GITHUB_SHA`, and the peeled tag commit are identical,
and rejects any dirty checkout. It reads the root project and the exact 15 publishable
`pyproject.toml` files, requiring every declared name and version to be the approved RC3
set. It then creates the complete 15-wheel/15-sdist set, validates it, runs strict Twine
checks, and stores the distributions, validation evidence, tag/commit provenance, and a
filename-sorted 30-entry lowercase-SHA-256 manifest in a single immutable Actions artifact.
Later jobs reuse that exact artifact and never rebuild.

### Trusted Publisher setup

All 30 Trusted Publisher registrations were recorded as configured on 2026-08-12 using
these GitHub values:

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
approved files together to `https://test.pypi.org/legacy/` without `skip-existing`. A
follow-on non-OIDC job polls the fixed HTTPS TestPyPI JSON API with a bounded retry budget,
then requires every remote project to expose only its own approved RC3 wheel and sdist.
Every remote filename and lowercase SHA-256 digest must match the 30-entry manifest exactly.

The verifier accepts only the fixed RC3 version, the 15 approved distribution identities,
HTTPS metadata hosts, and HTTPS artifact URLs under the approved `/packages/` prefix. It
rejects duplicate manifest keys, unsafe filenames, non-RC3 filenames, non-lowercase digests,
any artifact whose `yanked` value is not exactly `false`, inconsistent yank reasons,
credential-bearing or redirected-to-unapproved URLs, oversized responses, and exhausted
redirect or metadata retry budgets. Artifact downloads are size-bounded, streamed to new
temporary files while hashing, atomically made visible only after their digest matches, and
removed with the destination on every failure. The isolated installed smoke matrix pins all
15 distributions to `==0.1.0rc3` and never uses an `--extra-index-url`.

For an incomplete TestPyPI attempt, do not rerun this clean-publication workflow. Preserve
the manifest and workflow evidence, compare every existing file with the approved manifest,
and obtain a separately reviewed recovery decision. Multi-project uploads are not perfectly
transactional; the absence preflight and exact remote verification are the safety boundaries.

### Production approval and incident handling

Production publication cannot begin until TestPyPI publication *and* remote verification
succeed. A second non-OIDC preflight requires RC3 to remain absent from production PyPI. The
manually approved `pypi` environment then receives the same immutable artifact,
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

- RC3 preparation does not itself create a tag or publish packages.
- Pushing `v0.1.0rc3` starts the immutable build and TestPyPI publication workflow.
- Production PyPI publication requires the protected `pypi` environment approval.

Before public branding or package publication, complete formal trademark and package-name clearance.
