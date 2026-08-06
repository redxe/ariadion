# Publishing the initial repository

The intended remote is `redxe/ariadion` with `main` as the default branch.

From a machine with GitHub CLI authentication:

```bash
gh repo create redxe/ariadion \
  --public \
  --description "A thread through quantum complexity." \
  --source . \
  --remote origin \
  --push
```

Before public branding or package publication, complete formal trademark and package-name clearance.
