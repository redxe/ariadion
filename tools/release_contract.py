"""Immutable identity for the next coordinated Ariadion release candidate."""

from __future__ import annotations

RELEASE_VERSION = "0.1.0rc3"
RELEASE_TAG = f"v{RELEASE_VERSION}"
RELEASE_BUNDLE_NAME = "ariadion-rc3-release-bundle"

PUBLISHABLE_PROJECTS = (
    ("apps/cli/pyproject.toml", "ariadion-cli"),
    ("packages/core/pyproject.toml", "ariadion-core"),
    ("packages/daidalon/pyproject.toml", "daidalon"),
    ("packages/frontend-python/pyproject.toml", "ariadion-frontend-python"),
    ("packages/ir/pyproject.toml", "ariadion-ir"),
    ("packages/language/pyproject.toml", "ariadion-language"),
    ("packages/noise/pyproject.toml", "ariadion-noise"),
    ("packages/runtime/pyproject.toml", "ariadion-runtime"),
    ("packages/sdk/pyproject.toml", "ariadion"),
    ("packages/semantics/pyproject.toml", "ariadion-semantics"),
    ("packages/simulator/pyproject.toml", "ariadion-simulator"),
    ("packages/simulator-numpy/pyproject.toml", "ariadion-simulator-numpy"),
    ("packages/syntax/pyproject.toml", "ariadion-syntax"),
    ("packages/theonoe/pyproject.toml", "theonoe"),
    ("packages/visualization/pyproject.toml", "ariadion-visualization"),
)
PUBLISHABLE_DISTRIBUTIONS = (
    "ariadion",
    "ariadion-cli",
    "ariadion-core",
    "ariadion-frontend-python",
    "ariadion-ir",
    "ariadion-language",
    "ariadion-noise",
    "ariadion-runtime",
    "ariadion-semantics",
    "ariadion-simulator",
    "ariadion-simulator-numpy",
    "ariadion-syntax",
    "ariadion-visualization",
    "daidalon",
    "theonoe",
)
ARTIFACT_COUNT = len(PUBLISHABLE_DISTRIBUTIONS) * 2
