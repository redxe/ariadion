# Changelog

## Unreleased

### Added
- Local workspace packaging discovery for publishable Ariadion distributions.
- An end-to-end release smoke workflow that builds wheels, installs the public SDK
	and CLI from an isolated local wheelhouse, and executes both outside the checkout.
- Optional NumPy backend installation and explicit parity smoke validation.
- Repository-level release documentation and Python 3.11/3.12 CI coverage for
	packaging and installability.
