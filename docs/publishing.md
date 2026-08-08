# Publishing the initial repository

The intended remote is `redxe/ariadion` with `main` as the default branch.

## Technical RC policy

- RC artifact version for this preparation pass: `0.1.0rc1`.
- RC tag form for reviewer-approved release actions: `v0.1.0rc1`.
- The artifact version itself must carry the `rc` suffix; do not tag an RC while
  emitting final-looking `0.1.0` wheels.
- Publishable Ariadion package/app metadata must use exact internal RC pins
  `==0.1.0rc1` during this candidate stage.
- Revisit internal dependency pins before the final `0.1.0` release plan.

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

- This RC preparation pass does not publish packages.
- This RC preparation pass does not create tags.

Before public branding or package publication, complete formal trademark and package-name clearance.
