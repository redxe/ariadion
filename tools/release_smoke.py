from __future__ import annotations

import argparse
import configparser
import email.parser
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version
try:
    from tools.release_contract import RELEASE_VERSION
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    from release_contract import RELEASE_VERSION

ROOT = Path(__file__).resolve().parents[1]
PUBLISHABLE_DISTRIBUTION_COUNT = 15
RELEASE_SMOKE_MINIMUM_NUMPY_VERSION = "1.26.0"
RELEASE_SMOKE_NUMPY_VERSION = "2.4.6"
PEP_639_METADATA_VERSION = Version("2.4")

# This reviewed RC3 contract is intentionally authored separately from package
# pyproject.toml files. Source/artifact parity alone cannot detect an edge
# deleted, duplicated, conditionalized, redirected, or incorrectly pinned in both.
EXPECTED_RC3_DEPENDENCY_GRAPH: dict[str, tuple[str, ...]] = {
    "ariadion": (
        f"ariadion-frontend-python=={RELEASE_VERSION}",
        f"ariadion-language=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
        f"ariadion-runtime=={RELEASE_VERSION}",
        f"ariadion-semantics=={RELEASE_VERSION}",
    ),
    "ariadion-cli": (
        f"ariadion=={RELEASE_VERSION}",
        f"ariadion-visualization=={RELEASE_VERSION}",
    ),
    "ariadion-core": (),
    "ariadion-frontend-python": (
        f"ariadion-core=={RELEASE_VERSION}",
        f"ariadion-language=={RELEASE_VERSION}",
        f"ariadion-semantics=={RELEASE_VERSION}",
    ),
    "ariadion-ir": (f"ariadion-core=={RELEASE_VERSION}",),
    "ariadion-language": (f"ariadion-core=={RELEASE_VERSION}",),
    "ariadion-noise": (f"ariadion-core=={RELEASE_VERSION}",),
    "ariadion-runtime": (
        f"ariadion-core=={RELEASE_VERSION}",
        f"ariadion-ir=={RELEASE_VERSION}",
        f"ariadion-language=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
        f"ariadion-semantics=={RELEASE_VERSION}",
        f"daidalon=={RELEASE_VERSION}",
        f"ariadion-simulator=={RELEASE_VERSION}",
        f"theonoe=={RELEASE_VERSION}",
        f"ariadion-visualization=={RELEASE_VERSION}",
    ),
    "ariadion-semantics": (
        f"ariadion-core=={RELEASE_VERSION}",
        f"ariadion-language=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
    ),
    "ariadion-simulator": (
        f"ariadion-ir=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
    ),
    "ariadion-simulator-numpy": (
        f"ariadion-ir=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
        f"ariadion-simulator=={RELEASE_VERSION}",
        "numpy>=1.26",
    ),
    "ariadion-syntax": (f"ariadion-core=={RELEASE_VERSION}",),
    "ariadion-visualization": (f"ariadion-ir=={RELEASE_VERSION}",),
    "daidalon": (
        f"ariadion-core=={RELEASE_VERSION}",
        f"ariadion-language=={RELEASE_VERSION}",
        f"ariadion-ir=={RELEASE_VERSION}",
        f"ariadion-semantics=={RELEASE_VERSION}",
    ),
    "theonoe": (
        f"ariadion-core=={RELEASE_VERSION}",
        f"ariadion-noise=={RELEASE_VERSION}",
        f"ariadion-semantics=={RELEASE_VERSION}",
        f"ariadion-simulator=={RELEASE_VERSION}",
    ),
}


class ReleaseSmokeError(RuntimeError):
    """Raised when the release smoke workflow cannot complete."""


def _load_pyproject(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def discover_workspace_distributions(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or ROOT
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        raise ReleaseSmokeError(f"workspace pyproject.toml missing: {pyproject_path}")

    pyproject = _load_pyproject(pyproject_path)

    workspace_config = pyproject.get("tool", {}).get("uv", {}).get("workspace", {})
    members = workspace_config.get("members")
    if not isinstance(members, list) or not members:
        raise ReleaseSmokeError("workspace members configuration is missing or empty")

    discovered: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, str) or not member:
            raise ReleaseSmokeError("workspace member entries must be non-empty strings")
        matches = sorted(
            path
            for path in root.glob(member)
            if path.is_dir() and (path / "pyproject.toml").exists()
        )
        if not matches:
            raise ReleaseSmokeError(f"workspace member pattern did not resolve to a package: {member}")
        for path in matches:
            if path == root:
                continue
            project_path = path / "pyproject.toml"
            project_data = _load_pyproject(project_path)
            project = project_data.get("project")
            if not isinstance(project, dict):
                raise ReleaseSmokeError(f"package metadata is missing [project] in {project_path}")
            project_name = project.get("name")
            if not isinstance(project_name, str) or not project_name:
                raise ReleaseSmokeError(f"package name is missing in {project_path}")
            discovered.append(
                {
                    "path": path,
                    "name": project_name,
                    "pyproject_path": project_path,
                    "relative_path": str(path.relative_to(root)),
                }
            )

    discovered.sort(key=lambda item: item["relative_path"])
    seen_names: dict[str, Path] = {}
    for entry in discovered:
        name = entry["name"]
        if name in seen_names:
            raise ReleaseSmokeError(
                f"duplicate workspace project name {name!r} in {seen_names[name]} and {entry['path']}"
            )
        seen_names[name] = entry["path"]

    return discovered


def publishable_distributions(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or ROOT
    discovered = discover_workspace_distributions(root)
    publishable = []
    for entry in discovered:
        relative_path = entry["path"].relative_to(root)
        if relative_path.parts[:1] == ("packages",) or relative_path == Path("apps") / "cli":
            publishable.append(entry)
    return [entry for entry in publishable if entry["name"] != "ariadion-workspace"]


def build_wheel_command(member_dir: Path, wheelhouse: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "wheel",
        str(member_dir),
        "--wheel-dir",
        str(wheelhouse),
        "--no-deps",
    ]


def build_venv_command(venv_dir: Path) -> list[str]:
    return [sys.executable, "-m", "venv", str(venv_dir)]


def download_numpy_command(
    wheelhouse: Path,
    numpy_version: str = RELEASE_SMOKE_NUMPY_VERSION,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "download",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        f"numpy=={numpy_version}",
    ]


def install_from_wheelhouse_command(
    venv_python: Path,
    wheelhouse: Path,
    *,
    with_numpy: bool = False,
) -> list[str]:
    command = [
        str(venv_python),
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "ariadion",
        "ariadion-cli",
    ]
    if with_numpy:
        command.append("ariadion-simulator-numpy")
    return command


def install_all_distributions_command(
    venv_python: Path,
    wheelhouse: Path,
    distributions: list[dict[str, Any]],
    *,
    with_numpy: bool,
) -> list[str]:
    """Install every built distribution, excluding the optional NumPy package when absent."""
    names = sorted(
        entry["name"]
        for entry in distributions
        if with_numpy or entry["name"] != "ariadion-simulator-numpy"
    )
    return [
        str(venv_python),
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        *names,
    ]


def all_imports_smoke_script(distribution_names: list[str]) -> str:
    """Return a script that imports each distribution's normalized top-level package."""
    import_packages = sorted(name.replace("-", "_") for name in distribution_names)
    return textwrap.dedent(
        f"""
        import importlib

        packages = {import_packages!r}
        for package in packages:
            importlib.import_module(package)
        print(f"all-imports-smoke-ok:{{len(packages)}}")
        """
    ).strip()


def sdk_smoke_script() -> str:
    return textwrap.dedent(
        """
        from ariadion import Program, run

        program = Program(2, name='release-smoke')
        program.h(0).cx(0, 1)
        result = run(program)
        probabilities = result.simulation.probabilities
        if not (abs(probabilities[0] - 0.5) < 1e-9 and abs(probabilities[3] - 0.5) < 1e-9):
            raise SystemExit('unexpected bell-state probabilities')
        print('sdk-smoke-ok')
        """
    ).strip()


def numpy_smoke_script() -> str:
    return textwrap.dedent(
        """
        from ariadion import Program, run
        import numpy
        from ariadion_simulator_numpy import (
            NUMPY_COMPLEX_DTYPE,
            NumpyStateVectorBackend,
        )

        program = Program(2, name='release-numpy-smoke')
        program.h(0).cx(0, 1)
        reference = run(program)
        backend = NumpyStateVectorBackend()
        result = backend.execute(reference.ir)
        if NUMPY_COMPLEX_DTYPE.name != 'complex128':
            raise SystemExit('optional backend did not select NumPy complex128')
        if any(abs(left - right) >= 1e-12 for left, right in zip(
            result.probabilities,
            reference.simulation.probabilities,
            strict=True,
        )):
            raise SystemExit('optional NumPy backend did not match the reference result')
        print(f'numpy-smoke-ok:{numpy.__version__}')
        """
    ).strip()


def installed_report_smoke_script() -> str:
    lines = [
        "import json",
        "",
        "from ariadion import Bit, Qubit, x",
        "from ariadion_frontend_python import PythonFunctionSource, explicit_quantum_function",
        "from ariadion_runtime import (",
        "    DensityMatrixExecutionRequest,",
        "    build_bare_reliability_report,",
        "    build_density_noise_impact_report,",
        "    run_logical_module,",
        ")",
        "from ariadion_semantics import ClassicalAcceptanceCriterion, ReliabilityGoal",
        "from theonoe import (",
        "    BARE_RELIABILITY_SCHEMA_VERSION,",
        "    NOISE_IMPACT_SCHEMA_VERSION,",
        "    PROTECTION_REQUIREMENT_SCHEMA_VERSION,",
        "    BareReliabilityDistributionKind,",
        "    BareReliabilityGoalVerdict,",
        "    BareReliabilityReport,",
        "    BareReliabilityStatus,",
        "    NoiseImpactReport,",
        "    ProtectionNeedVerdict,",
        "    ProtectionRequirementReport,",
        "    build_protection_requirement_report,",
        ")",
        "",
        "",
        "def _source_placeholder() -> None:",
        "    return None",
        "",
        "",
        "_deterministic_one = explicit_quantum_function(",
        "    _source_placeholder,",
        "    PythonFunctionSource(",
        "        text=(",
        "            \"def deterministic_one() -> Bit:\\n\"",
        "            \"    value = Qubit()\\n\"",
        "            \"    x(value)\\n\"",
        "            \"    return value\\n\"",
        "        ),",
        "        file=\"release_smoke_installed_report.py\",",
        "        starting_line=1,",
        "        module_name=\"release_smoke\",",
        "        qualified_name=\"deterministic_one\",",
        "    ),",
        ")",
        "",
        "",
        "run = run_logical_module(",
        "    _deterministic_one.to_logical_module(),",
        "    execution=DensityMatrixExecutionRequest(),",
        ")",
        "",
        "noise_impact = build_density_noise_impact_report(run)",
        "if not isinstance(noise_impact, NoiseImpactReport):",
        "    raise SystemExit('installed report smoke expected NoiseImpactReport')",
        "if noise_impact.schema_version != NOISE_IMPACT_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke noise-impact schema_version mismatch')",
        "noise_payload = json.loads(noise_impact.to_json())",
        "if noise_payload['schema_version'] != NOISE_IMPACT_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke noise-impact JSON schema marker mismatch')",
        "for key in ('comparison', 'metrics', 'event_findings'):",
        "    if key not in noise_payload:",
        "        raise SystemExit(f\"installed report smoke noise-impact missing key: {key}\")",
        "",
        "bare_reliability = build_bare_reliability_report(",
        "    run,",
        "    goal=ReliabilityGoal(0.1),",
        "    acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),",
        "    distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,",
        ")",
        "if not isinstance(bare_reliability, BareReliabilityReport):",
        "    raise SystemExit('installed report smoke expected BareReliabilityReport')",
        "if bare_reliability.schema_version != BARE_RELIABILITY_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke bare-reliability schema_version mismatch')",
        "if bare_reliability.status is not BareReliabilityStatus.SUPPORTED:",
        "    raise SystemExit('installed report smoke expected supported bare reliability status')",
        "if bare_reliability.goal_verdict is not BareReliabilityGoalVerdict.SATISFIED:",
        "    raise SystemExit('installed report smoke expected satisfied bare reliability verdict')",
        "bare_payload = json.loads(bare_reliability.to_json())",
        "if bare_payload['schema_version'] != BARE_RELIABILITY_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke bare-reliability JSON schema marker mismatch')",
        "for key in ('status', 'goal_verdict', 'supporting_noise_impact'):",
        "    if key not in bare_payload:",
        "        raise SystemExit(f\"installed report smoke bare-reliability missing key: {key}\")",
        "",
        "protection_requirement = build_protection_requirement_report(bare_reliability)",
        "if not isinstance(protection_requirement, ProtectionRequirementReport):",
        "    raise SystemExit('installed report smoke expected ProtectionRequirementReport')",
        "if protection_requirement.schema_version != PROTECTION_REQUIREMENT_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke protection-requirement schema_version mismatch')",
        "if protection_requirement.status is not BareReliabilityStatus.SUPPORTED:",
        "    raise SystemExit('installed report smoke expected supported protection status')",
        "if protection_requirement.need_verdict is not ProtectionNeedVerdict.NO_PROTECTION_REQUIRED:",
        "    raise SystemExit('installed report smoke expected no_protection_required verdict')",
        "protection_payload = json.loads(protection_requirement.to_json())",
        "if protection_payload['schema_version'] != PROTECTION_REQUIREMENT_SCHEMA_VERSION:",
        "    raise SystemExit('installed report smoke protection-requirement JSON schema marker mismatch')",
        "for key in ('status', 'need_verdict', 'supporting_bare_reliability'):",
        "    if key not in protection_payload:",
        "        raise SystemExit(f\"installed report smoke protection-requirement missing key: {key}\")",
        "",
        "print('installed-report-smoke-ok')",
    ]
    return "\n".join(lines)


def cli_smoke_command(venv_dir: Path) -> list[str]:
    if os.name == "nt":
        return [str(venv_dir / "Scripts" / "ariadion.exe")]
    return [str(venv_dir / "bin" / "ariadion")]


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _require_empty_directory(path: Path, *, label: str) -> None:
    if path.exists() and any(path.iterdir()):
        raise ReleaseSmokeError(f"{label} must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _missing_distribution_wheels(
    distributions: list[dict[str, Any]],
    wheel_files: list[Path],
) -> list[str]:
    wheel_names = tuple(path.name.lower() for path in wheel_files)
    return [
        entry["name"]
        for entry in distributions
        if not any(
            wheel_name.startswith(f"{_normalized_distribution_name(entry['name'])}-")
            for wheel_name in wheel_names
        )
    ]


def _subprocess_environment(*, sanitize_cli_encoding: bool = False) -> dict[str, str]:
    merged_env = os.environ.copy()
    merged_env.pop("PYTHONPATH", None)
    if sanitize_cli_encoding:
        merged_env.pop("PYTHONUTF8", None)
        merged_env.pop("PYTHONIOENCODING", None)
    return merged_env


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    sanitize_cli_encoding: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged_env = _subprocess_environment(sanitize_cli_encoding=sanitize_cli_encoding)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseSmokeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def _assert_cli_smoke_output(output: str) -> None:
    required_markers = ("q0:", "q1:", "[H]", "[X]", "0.5")
    missing_markers = [marker for marker in required_markers if marker not in output]
    if missing_markers:
        raise ReleaseSmokeError(
            "CLI smoke output missing expected semantic markers: "
            + ", ".join(missing_markers)
        )


def _extract_numpy_version(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("numpy-smoke-ok:"):
            version = line.split(":", 1)[1].strip()
            if version:
                return version
            break
    raise ReleaseSmokeError("optional NumPy smoke did not report the resolved NumPy version")


def _assert_numpy_version_matches_pin(version: str) -> None:
    _assert_numpy_version_matches(version, RELEASE_SMOKE_NUMPY_VERSION)


def _assert_numpy_version_matches(version: str, expected_version: str) -> None:
    if version != expected_version:
        expected_label = (
            f"pinned {expected_version}"
            if expected_version == RELEASE_SMOKE_NUMPY_VERSION
            else f"requested {expected_version}"
        )
        raise ReleaseSmokeError(
            "optional NumPy smoke resolved "
            f"numpy {version}, expected {expected_label}; "
            "rebuild the wheelhouse and rerun release smoke"
        )


def build_sdist_command(member_dir: Path, sdist_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "build",
        "--sdist",
        "--outdir",
        str(sdist_dir),
        str(member_dir),
    ]


def twine_check_command(artifact_paths: list[Path]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "twine",
        "check",
        "--strict",
    ] + [str(p) for p in sorted(artifact_paths)]


def runtime_version_check_script() -> str:
    return textwrap.dedent(
        """
        import importlib.metadata
        import ariadion
        installed = importlib.metadata.version("ariadion")
        runtime = ariadion.__version__
        if installed != runtime:
            raise SystemExit(
                f"version mismatch: installed={installed!r}, "
                f"ariadion.__version__={runtime!r}"
            )
        print(f"version-check-ok:{installed}")
        """
    ).strip()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_sha256_manifest(artifact_paths: list[Path]) -> dict[str, str]:
    """Return a filename-sorted, portable SHA-256 manifest for regular artifact files."""
    existing_paths = [path for path in artifact_paths if path.is_file()]
    filenames = [path.name for path in existing_paths]
    duplicates = sorted(name for name, count in Counter(filenames).items() if count > 1)
    if duplicates:
        raise ReleaseSmokeError(
            "cannot generate SHA-256 manifest with duplicate filenames: "
            + ", ".join(duplicates)
        )
    return {
        path.name: _sha256_file(path)
        for path in sorted(existing_paths, key=lambda artifact_path: artifact_path.name)
    }


RequirementKey = tuple[str, tuple[str, ...], str, str | None, str | None]


def _normalize_description(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip()


def _require_project_string(
    project: dict[str, Any],
    field: str,
    *,
    source_label: str,
) -> str:
    value = project.get(field)
    if not isinstance(value, str) or not value:
        raise ReleaseSmokeError(f"{source_label}: project.{field} must be a non-empty string")
    return value


def _parse_requirements(
    values: list[str] | tuple[str, ...],
    *,
    context: str,
) -> tuple[Requirement, ...]:
    requirements: list[Requirement] = []
    for value in values:
        if not isinstance(value, str):
            raise ReleaseSmokeError(f"{context}: requirement must be a string, got {value!r}")
        try:
            requirements.append(Requirement(value))
        except InvalidRequirement as exc:
            raise ReleaseSmokeError(f"{context}: invalid requirement {value!r}: {exc}") from exc
    return tuple(requirements)


def _requirement_key(requirement: Requirement) -> RequirementKey:
    return (
        _normalized_distribution_name(requirement.name),
        tuple(sorted(_normalized_distribution_name(extra) for extra in requirement.extras)),
        str(requirement.specifier),
        requirement.url,
        str(requirement.marker) if requirement.marker is not None else None,
    )


def _format_requirement_key(requirement_key: RequirementKey) -> str:
    name, extras, specifier, url, marker = requirement_key
    rendered = name
    if extras:
        rendered += "[" + ",".join(extras) + "]"
    rendered += specifier
    if url is not None:
        rendered += f" @ {url}"
    if marker is not None:
        rendered += f" ; {marker}"
    return rendered


def _format_dependency_difference(
    *,
    source_label: str,
    expected: Counter[RequirementKey],
    actual: Counter[RequirementKey],
) -> str:
    missing = expected - actual
    unexpected = actual - expected
    details: list[str] = []
    if missing:
        details.append(
            "missing="
            + repr(sorted(_format_requirement_key(requirement) for requirement in missing.elements()))
        )
    if unexpected:
        details.append(
            "unexpected="
            + repr(sorted(_format_requirement_key(requirement) for requirement in unexpected.elements()))
        )
    return (
        f"{source_label}: source dependency graph differs from the independent RC3 "
        "baseline: "
        + "; ".join(details)
    )


def _expected_rc3_dependency_multisets() -> dict[str, Counter[RequirementKey]]:
    """Return semantic requirement multisets from the fixed reviewed RC3 graph."""
    return {
        _normalized_distribution_name(distribution_name): Counter(
            _requirement_key(requirement)
            for requirement in _parse_requirements(
                requirements,
                context=f"independent RC3 dependency baseline for {distribution_name}",
            )
        )
        for distribution_name, requirements in EXPECTED_RC3_DEPENDENCY_GRAPH.items()
    }


def _read_source_readme(
    entry: dict[str, Any],
    project: dict[str, Any],
    *,
    source_label: str,
) -> str:
    readme = project.get("readme")
    if isinstance(readme, str):
        readme_file = readme
    elif isinstance(readme, dict):
        readme_file = readme.get("file")
        content_type = readme.get("content-type")
        if content_type not in (None, "text/markdown"):
            raise ReleaseSmokeError(
                f"{source_label}: README content type must be text/markdown, got {content_type!r}"
            )
    else:
        raise ReleaseSmokeError(f"{source_label}: project.readme must name a Markdown file")
    if not isinstance(readme_file, str) or not readme_file:
        raise ReleaseSmokeError(f"{source_label}: project.readme file is missing")
    readme_path = Path(entry["path"]) / readme_file
    if not readme_path.is_file():
        raise ReleaseSmokeError(f"{source_label}: README file is missing: {readme_path}")
    readme_text = _normalize_description(readme_path.read_text(encoding="utf-8"))
    if not readme_text:
        raise ReleaseSmokeError(f"{source_label}: README file is empty: {readme_path}")
    return readme_text


def _source_import_package(entry: dict[str, Any], *, source_label: str) -> str:
    source_root = Path(entry["path"]) / "src"
    init_files = sorted(
        path
        for path in source_root.glob("*/__init__.py")
        if path.is_file()
    )
    if len(init_files) != 1:
        raise ReleaseSmokeError(
            f"{source_label}: expected exactly one src/<package>/__init__.py, "
            f"found {len(init_files)}"
        )
    return init_files[0].parent.name


def authoritative_distribution_records(
    distributions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build the authoritative normalized-name mapping from source pyproject metadata."""
    records: dict[str, dict[str, Any]] = {}
    expected_dependency_multisets = _expected_rc3_dependency_multisets()
    for entry in distributions:
        pyproject_path = Path(entry["pyproject_path"])
        source_label = str(pyproject_path)
        document = _load_pyproject(pyproject_path)
        project = document.get("project")
        if not isinstance(project, dict):
            raise ReleaseSmokeError(f"{source_label}: [project] metadata is missing")

        name = _require_project_string(project, "name", source_label=source_label)
        entry_name = entry.get("name")
        if entry_name != name:
            raise ReleaseSmokeError(
                f"{source_label}: discovered name {entry_name!r} does not match project.name {name!r}"
            )
        normalized_name = _normalized_distribution_name(name)
        if normalized_name in records:
            previous = records[normalized_name]["pyproject_path"]
            raise ReleaseSmokeError(
                f"duplicate normalized publishable distribution name {normalized_name!r} "
                f"in {previous} and {pyproject_path}"
            )
        if normalized_name not in expected_dependency_multisets:
            raise ReleaseSmokeError(
                f"{source_label}: distribution {name!r} is absent from the independent RC3 dependency baseline"
            )

        version = _require_project_string(project, "version", source_label=source_label)
        summary = _require_project_string(project, "description", source_label=source_label)
        requires_python = _require_project_string(
            project,
            "requires-python",
            source_label=source_label,
        )
        if requires_python != ">=3.11":
            raise ReleaseSmokeError(
                f"{source_label}: requires-python must be exactly '>=3.11', got {requires_python!r}"
            )
        if project.get("license") != "Apache-2.0":
            raise ReleaseSmokeError(
                f"{source_label}: project.license must be 'Apache-2.0'"
            )
        if project.get("license-files") != ["LICENSE"]:
            raise ReleaseSmokeError(
                f"{source_label}: project.license-files must be exactly ['LICENSE']"
            )
        if project.get("authors") != [{"name": "Vi Connelly"}]:
            raise ReleaseSmokeError(
                f"{source_label}: project.authors must be exactly Vi Connelly without an email"
            )

        urls = project.get("urls")
        if not isinstance(urls, dict) or not all(
            isinstance(label, str) and isinstance(url, str) and label and url
            for label, url in urls.items()
        ):
            raise ReleaseSmokeError(f"{source_label}: project.urls must be a string mapping")
        classifiers = project.get("classifiers")
        if not isinstance(classifiers, list) or not all(
            isinstance(classifier, str) and classifier for classifier in classifiers
        ):
            raise ReleaseSmokeError(f"{source_label}: project.classifiers must be a string list")
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ReleaseSmokeError(f"{source_label}: project.dependencies must be a list")
        dependency_requirements = _parse_requirements(
            dependencies,
            context=f"{source_label}: project.dependencies",
        )
        actual_dependency_multiset = Counter(
            _requirement_key(requirement) for requirement in dependency_requirements
        )
        expected_dependency_multiset = expected_dependency_multisets[normalized_name]
        if actual_dependency_multiset != expected_dependency_multiset:
            raise ReleaseSmokeError(
                _format_dependency_difference(
                    source_label=source_label,
                    expected=expected_dependency_multiset,
                    actual=actual_dependency_multiset,
                )
            )

        records[normalized_name] = {
            "name": name,
            "normalized_name": normalized_name,
            "path": Path(entry["path"]),
            "pyproject_path": pyproject_path,
            "version": version,
            "summary": summary,
            "requires_python": requires_python,
            "readme_text": _read_source_readme(entry, project, source_label=source_label),
            "import_name": _source_import_package(entry, source_label=source_label),
            "project_urls": Counter((label, url) for label, url in urls.items()),
            "classifiers": Counter(classifiers),
            "dependency_requirements": dependency_requirements,
        }
    missing_baseline_distributions = sorted(set(expected_dependency_multisets) - set(records))
    if missing_baseline_distributions:
        raise ReleaseSmokeError(
            "publishable source distributions missing from the independent RC3 dependency baseline: "
            + ", ".join(missing_baseline_distributions)
        )
    return records


def _single_metadata_value(
    metadata: email.parser.Message,
    header: str,
    *,
    artifact_name: str,
    errors: list[str],
) -> str | None:
    values = metadata.get_all(header) or []
    if len(values) != 1:
        errors.append(
            f"{artifact_name}: expected exactly one {header} header, found {len(values)}"
        )
        return None
    return values[0]


def _metadata_project_urls(
    metadata: email.parser.Message,
    *,
    artifact_name: str,
    errors: list[str],
) -> Counter[tuple[str, str]]:
    project_urls: Counter[tuple[str, str]] = Counter()
    for value in metadata.get_all("Project-URL") or []:
        label, separator, url = value.partition(",")
        if not separator or not label.strip() or not url.strip():
            errors.append(f"{artifact_name}: malformed Project-URL header {value!r}")
            continue
        project_urls[(label.strip(), url.strip())] += 1
    return project_urls


def _artifact_requirements(
    metadata: email.parser.Message,
    *,
    artifact_name: str,
    errors: list[str],
) -> tuple[Requirement, ...]:
    values = metadata.get_all("Requires-Dist") or []
    requirements: list[Requirement] = []
    for value in values:
        try:
            requirements.append(Requirement(value))
        except InvalidRequirement as exc:
            errors.append(f"{artifact_name}: invalid Requires-Dist {value!r}: {exc}")
    return tuple(requirements)


def _validate_dependency_metadata(
    metadata: email.parser.Message,
    *,
    artifact_name: str,
    expected_version: str,
    record: dict[str, Any],
    records_by_normalized_name: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    actual_requirements = _artifact_requirements(
        metadata,
        artifact_name=artifact_name,
        errors=errors,
    )
    expected_requirements = record["dependency_requirements"]
    expected_multiset = Counter(_requirement_key(requirement) for requirement in expected_requirements)
    actual_multiset = Counter(_requirement_key(requirement) for requirement in actual_requirements)
    missing = expected_multiset - actual_multiset
    unexpected = actual_multiset - expected_multiset
    if missing:
        errors.append(
            f"{artifact_name}: missing Requires-Dist values: "
            + ", ".join(
                _format_requirement_key(requirement_key)
                for requirement_key in sorted(missing.elements())
            )
        )
    if unexpected:
        errors.append(
            f"{artifact_name}: unexpected Requires-Dist values: "
            + ", ".join(
                _format_requirement_key(requirement_key)
                for requirement_key in sorted(unexpected.elements())
            )
        )

    for requirement in actual_requirements:
        normalized_name = _normalized_distribution_name(requirement.name)
        if normalized_name not in records_by_normalized_name:
            continue
        violations: list[str] = []
        if requirement.extras:
            violations.append(f"unexpected extras {sorted(requirement.extras)}")
        if str(requirement.specifier) != f"=={expected_version}":
            violations.append(
                f"specifier {str(requirement.specifier)!r}, expected '=={expected_version}'"
            )
        if requirement.url is not None:
            violations.append(f"URL {requirement.url!r}")
        if requirement.marker is not None:
            violations.append(f"environment marker {str(requirement.marker)!r}")
        if violations:
            errors.append(
                f"{artifact_name}: internal dependency {requirement.name!r} must be an "
                f"unconditional exact RC pin; found " + "; ".join(violations)
            )
    return errors


def _validate_core_metadata(
    metadata: email.parser.Message,
    *,
    artifact_name: str,
    expected_version: str,
    record: dict[str, Any],
    records_by_normalized_name: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate artifact Core Metadata exactly against its authoritative source record."""
    errors: list[str] = []
    expected_headers = {
        "Name": record["name"],
        "Version": record["version"],
        "Summary": record["summary"],
        "Requires-Python": record["requires_python"],
        "Description-Content-Type": "text/markdown",
        "License-Expression": "Apache-2.0",
        "Author": "Vi Connelly",
    }
    for header, expected_value in expected_headers.items():
        actual_value = _single_metadata_value(
            metadata,
            header,
            artifact_name=artifact_name,
            errors=errors,
        )
        if actual_value is not None and actual_value != expected_value:
            errors.append(
                f"{artifact_name}: {header} is {actual_value!r}, expected {expected_value!r}"
            )

    metadata_version = _single_metadata_value(
        metadata,
        "Metadata-Version",
        artifact_name=artifact_name,
        errors=errors,
    )
    if metadata_version is not None:
        try:
            if Version(metadata_version) < PEP_639_METADATA_VERSION:
                errors.append(
                    f"{artifact_name}: Metadata-Version {metadata_version!r} is below "
                    f"the PEP 639 minimum {PEP_639_METADATA_VERSION}"
                )
        except InvalidVersion:
            errors.append(f"{artifact_name}: invalid Metadata-Version {metadata_version!r}")

    if record["version"] != expected_version:
        errors.append(
            f"{artifact_name}: authoritative source version {record['version']!r} "
            f"does not equal expected {expected_version!r}"
        )
    license_files = metadata.get_all("License-File") or []
    if license_files != ["LICENSE"]:
        errors.append(
            f"{artifact_name}: License-File headers are {license_files!r}, expected ['LICENSE']"
        )
    author_emails = metadata.get_all("Author-email") or []
    if author_emails:
        errors.append(f"{artifact_name}: Author-email headers must be absent, found {author_emails!r}")

    description = metadata.get_payload()
    if not isinstance(description, str) or not _normalize_description(description):
        errors.append(f"{artifact_name}: Description payload is empty")
    elif _normalize_description(description) != record["readme_text"]:
        errors.append(f"{artifact_name}: Description payload differs from the package README")

    project_urls = _metadata_project_urls(
        metadata,
        artifact_name=artifact_name,
        errors=errors,
    )
    if project_urls != record["project_urls"]:
        errors.append(
            f"{artifact_name}: Project-URL headers differ from source metadata: "
            f"found={sorted(project_urls.elements())!r}, "
            f"expected={sorted(record['project_urls'].elements())!r}"
        )
    classifiers = Counter(metadata.get_all("Classifier") or [])
    if classifiers != record["classifiers"]:
        errors.append(
            f"{artifact_name}: Classifier headers differ from source metadata: "
            f"found={sorted(classifiers.elements())!r}, "
            f"expected={sorted(record['classifiers'].elements())!r}"
        )
    errors.extend(
        _validate_dependency_metadata(
            metadata,
            artifact_name=artifact_name,
            expected_version=expected_version,
            record=record,
            records_by_normalized_name=records_by_normalized_name,
        )
    )
    return errors


def _zip_info_is_regular_file(info: zipfile.ZipInfo) -> bool:
    if info.is_dir():
        return False
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type:
        return file_type == stat.S_IFREG
    return not info.is_dir() and not stat.S_ISLNK(unix_mode)


def _required_zip_member(
    archive: zipfile.ZipFile,
    member_name: str,
    *,
    artifact_name: str,
) -> zipfile.ZipInfo:
    matches = [info for info in archive.infolist() if info.filename == member_name]
    if len(matches) != 1:
        raise ReleaseSmokeError(
            f"{artifact_name}: expected exactly one archive member {member_name!r}, "
            f"found {len(matches)}"
        )
    member = matches[0]
    if not _zip_info_is_regular_file(member):
        raise ReleaseSmokeError(
            f"{artifact_name}: archive member {member_name!r} must be a regular file"
        )
    return member


def _read_wheel_metadata(wheel_path: Path) -> tuple[email.parser.Message, str]:
    """Extract a wheel's only METADATA payload and its owning dist-info directory."""
    with zipfile.ZipFile(wheel_path) as archive:
        members = archive.infolist()
        unsafe_members = [
            info.filename
            for info in members
            if info.filename.startswith("/") or ".." in info.filename.split("/")
        ]
        if unsafe_members:
            raise ReleaseSmokeError(
                f"wheel {wheel_path.name}: unsafe archive member paths: "
                f"{sorted(unsafe_members)!r}"
            )
        metadata_members = [
            info
            for info in members
            if re.fullmatch(r"[^/]+\.dist-info/METADATA", info.filename)
        ]
        if len(metadata_members) != 1:
            raise ReleaseSmokeError(
                f"wheel {wheel_path.name}: expected exactly one dist-info METADATA file, "
                f"found {len(metadata_members)}"
            )
        metadata_member = metadata_members[0]
        if not _zip_info_is_regular_file(metadata_member):
            raise ReleaseSmokeError(f"wheel {wheel_path.name}: METADATA must be a regular file")
        metadata_text = archive.read(metadata_member).decode("utf-8")
    parser = email.parser.Parser()
    return parser.parsestr(metadata_text), metadata_member.filename.rsplit("/", 1)[0]


def _required_tar_member(
    archive: tarfile.TarFile,
    member_name: str,
    *,
    artifact_name: str,
) -> tarfile.TarInfo:
    matches = [member for member in archive.getmembers() if member.name == member_name]
    if len(matches) != 1:
        raise ReleaseSmokeError(
            f"{artifact_name}: expected exactly one archive member {member_name!r}, "
            f"found {len(matches)}"
        )
    member = matches[0]
    if not member.isfile():
        raise ReleaseSmokeError(
            f"{artifact_name}: archive member {member_name!r} must be a regular file"
        )
    return member


def _read_sdist_metadata(sdist_path: Path) -> tuple[email.parser.Message, str]:
    """Extract the only regular root PKG-INFO payload and its sdist root directory."""
    with tarfile.open(sdist_path, "r:gz") as archive:
        members = archive.getmembers()
        unsafe_members = [
            member.name
            for member in members
            if member.name.startswith("/") or ".." in member.name.split("/")
        ]
        if unsafe_members:
            raise ReleaseSmokeError(
                f"sdist {sdist_path.name}: unsafe archive member paths: "
                f"{sorted(unsafe_members)!r}"
            )
        roots = {
            member.name.split("/", 1)[0]
            for member in members
            if member.name and not member.name.startswith("/")
        }
        if len(roots) != 1:
            raise ReleaseSmokeError(
                f"sdist {sdist_path.name}: expected exactly one top-level root, "
                f"found {sorted(roots)!r}"
            )
        metadata_members = [
            member
            for member in members
            if re.fullmatch(r"[^/]+/PKG-INFO", member.name)
        ]
        if len(metadata_members) != 1:
            raise ReleaseSmokeError(
                f"sdist {sdist_path.name}: expected exactly one root PKG-INFO file, "
                f"found {len(metadata_members)}"
            )
        metadata_member = metadata_members[0]
        if not metadata_member.isfile():
            raise ReleaseSmokeError(f"sdist {sdist_path.name}: root PKG-INFO must be a regular file")
        extracted = archive.extractfile(metadata_member)
        if extracted is None:
            raise ReleaseSmokeError(f"sdist {sdist_path.name}: root PKG-INFO could not be read")
        metadata_text = extracted.read().decode("utf-8")
    parser = email.parser.Parser()
    return parser.parsestr(metadata_text), next(iter(roots))


def _wheel_license_payload(wheel_path: Path, dist_info_dir: str) -> bytes:
    """Read the sole PEP 639 wheel license payload and reject the legacy location."""
    expected_member = f"{dist_info_dir}/licenses/LICENSE"
    legacy_member = f"{dist_info_dir}/LICENSE"
    with zipfile.ZipFile(wheel_path) as archive:
        if any(info.filename == legacy_member for info in archive.infolist()):
            raise ReleaseSmokeError(
                f"wheel {wheel_path.name}: legacy license member {legacy_member!r} is not allowed"
            )
        license_candidates = [
            info.filename
            for info in archive.infolist()
            if re.fullmatch(r"[^/]+\.dist-info/(?:LICENSE|licenses/[^/]+)", info.filename)
        ]
        if license_candidates != [expected_member]:
            raise ReleaseSmokeError(
                f"wheel {wheel_path.name}: expected sole PEP 639 license member "
                f"{expected_member!r}, found {license_candidates!r}"
            )
        member = _required_zip_member(
            archive,
            expected_member,
            artifact_name=f"wheel {wheel_path.name}",
        )
        return archive.read(member)


def _sdist_license_payload(sdist_path: Path, sdist_root: str) -> bytes:
    """Read the sole regular LICENSE payload at the sdist root."""
    expected_member = f"{sdist_root}/LICENSE"
    with tarfile.open(sdist_path, "r:gz") as archive:
        member = _required_tar_member(
            archive,
            expected_member,
            artifact_name=f"sdist {sdist_path.name}",
        )
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ReleaseSmokeError(f"sdist {sdist_path.name}: LICENSE could not be read")
        return extracted.read()


def _validate_wheel_import_payload(
    wheel_path: Path,
    *,
    import_name: str,
) -> None:
    expected_member = f"{import_name}/__init__.py"
    with zipfile.ZipFile(wheel_path) as archive:
        _required_zip_member(
            archive,
            expected_member,
            artifact_name=f"wheel {wheel_path.name}",
        )


def _validate_sdist_import_payload(
    sdist_path: Path,
    *,
    sdist_root: str,
    import_name: str,
) -> None:
    expected_member = f"{sdist_root}/src/{import_name}/__init__.py"
    with tarfile.open(sdist_path, "r:gz") as archive:
        _required_tar_member(
            archive,
            expected_member,
            artifact_name=f"sdist {sdist_path.name}",
        )


def _parse_entry_points(
    text: str,
    *,
    artifact_name: str,
) -> list[tuple[str, str, str]]:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ReleaseSmokeError(f"{artifact_name}: malformed entry_points.txt: {exc}") from exc
    return [
        (section, command, target)
        for section in parser.sections()
        for command, target in parser.items(section)
    ]


def _validate_wheel_entry_points(
    wheel_path: Path,
    *,
    record: dict[str, Any],
    dist_info_dir: str,
) -> list[str]:
    """Validate the CLI entry point structurally and reject it from non-CLI wheels."""
    errors: list[str] = []
    expected_cli = ("console_scripts", "ariadion", "ariadion_cli:main")
    with zipfile.ZipFile(wheel_path) as archive:
        entry_point_members = [
            info
            for info in archive.infolist()
            if re.fullmatch(r"[^/]+\.dist-info/entry_points\.txt", info.filename)
        ]
        if record["name"] == "ariadion-cli":
            expected_member = f"{dist_info_dir}/entry_points.txt"
            if len(entry_point_members) != 1 or entry_point_members[0].filename != expected_member:
                errors.append(
                    f"wheel {wheel_path.name}: expected exactly one entry_points.txt at "
                    f"{expected_member!r}"
                )
                return errors
            member = entry_point_members[0]
            if not _zip_info_is_regular_file(member):
                errors.append(
                    f"wheel {wheel_path.name}: entry_points.txt must be a regular file"
                )
                return errors
            try:
                definitions = _parse_entry_points(
                    archive.read(member).decode("utf-8"),
                    artifact_name=f"wheel {wheel_path.name}",
                )
            except (ReleaseSmokeError, UnicodeDecodeError) as exc:
                errors.append(str(exc))
                return errors
            console_definitions = [
                (command, target)
                for section, command, target in definitions
                if section == "console_scripts"
            ]
            cli_definitions = [
                definition
                for definition in definitions
                if definition[1] == "ariadion"
            ]
            if console_definitions != [("ariadion", "ariadion_cli:main")]:
                errors.append(
                    f"wheel {wheel_path.name}: [console_scripts] must contain exactly "
                    "'ariadion = ariadion_cli:main'"
                )
            if cli_definitions != [expected_cli]:
                errors.append(
                    f"wheel {wheel_path.name}: ariadion CLI entry point must appear exactly "
                    "once in [console_scripts]"
                )
            return errors

        for member in entry_point_members:
            if not _zip_info_is_regular_file(member):
                errors.append(
                    f"wheel {wheel_path.name}: entry_points.txt must be a regular file"
                )
                continue
            try:
                definitions = _parse_entry_points(
                    archive.read(member).decode("utf-8"),
                    artifact_name=f"wheel {wheel_path.name}",
                )
            except (ReleaseSmokeError, UnicodeDecodeError) as exc:
                errors.append(str(exc))
                continue
            if expected_cli in definitions:
                errors.append(
                    f"wheel {wheel_path.name}: non-CLI distribution must not expose "
                    "'ariadion = ariadion_cli:main'"
                )
    return errors


def _artifact_filename_component(distribution_name: str) -> str:
    return re.sub(r"[-.]+", "_", distribution_name)


def _validate_wheel_filename(wheel_path: Path, record: dict[str, Any]) -> list[str]:
    try:
        distribution_name, version, _, _ = parse_wheel_filename(wheel_path.name)
    except InvalidWheelFilename as exc:
        return [f"{wheel_path.name}: invalid wheel filename: {exc}"]
    errors: list[str] = []
    if _normalized_distribution_name(str(distribution_name)) != record["normalized_name"]:
        errors.append(
            f"{wheel_path.name}: wheel filename distribution does not match "
            f"{record['name']!r}"
        )
    if str(version) != record["version"] or f"-{record['version']}-" not in wheel_path.name:
        errors.append(
            f"{wheel_path.name}: wheel filename version must be {record['version']!r}"
        )
    return errors


def _validate_sdist_filename(sdist_path: Path, record: dict[str, Any]) -> list[str]:
    filename = sdist_path.name
    suffix = f"-{record['version']}.tar.gz"
    if not filename.endswith(suffix):
        return [
            f"{filename}: sdist filename version must be {record['version']!r}"
        ]
    distribution_name = filename[: -len(suffix)]
    if not distribution_name or (
        _normalized_distribution_name(distribution_name) != record["normalized_name"]
    ):
        return [
            f"{filename}: sdist filename distribution does not match {record['name']!r}"
        ]
    return []


def _validate_sdist_root(sdist_root: str, record: dict[str, Any]) -> list[str]:
    suffix = f"-{record['version']}"
    if not sdist_root.endswith(suffix):
        return [
            f"sdist root {sdist_root!r} must end with version {record['version']!r}"
        ]
    distribution_name = sdist_root[: -len(suffix)]
    if not distribution_name or (
        _normalized_distribution_name(distribution_name) != record["normalized_name"]
    ):
        return [
            f"sdist root {sdist_root!r} does not match distribution {record['name']!r}"
        ]
    return []


def _resolve_artifact_record(
    metadata: email.parser.Message,
    *,
    artifact_name: str,
    records_by_normalized_name: dict[str, dict[str, Any]],
    errors: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    metadata_name = _single_metadata_value(
        metadata,
        "Name",
        artifact_name=artifact_name,
        errors=errors,
    )
    if metadata_name is None:
        return None, None
    normalized_name = _normalized_distribution_name(metadata_name)
    record = records_by_normalized_name.get(normalized_name)
    if record is None:
        errors.append(
            f"{artifact_name}: unknown normalized metadata name {normalized_name!r} "
            f"from Name {metadata_name!r}"
        )
    return record, normalized_name


def _validate_observed_distribution_names(
    kind: str,
    observed_names: list[str],
    expected_names: set[str],
) -> list[str]:
    errors: list[str] = []
    counts = Counter(observed_names)
    unknown = sorted(set(counts) - expected_names)
    if unknown:
        errors.append(f"{kind} artifacts contain unknown normalized names: {unknown}")
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        errors.append(
            f"{kind} artifacts contain duplicate normalized distribution names: {duplicates}"
        )
    missing = sorted(expected_names - set(counts))
    if missing:
        errors.append(f"{kind} artifacts are missing normalized distribution names: {missing}")
    return errors


def _is_workspace_artifact_filename(filename: str) -> bool:
    return "ariadion_workspace" in _normalized_distribution_name(filename)


def _validate_wheel_payload(
    wheel_path: Path,
    *,
    record: dict[str, Any],
    dist_info_dir: str,
    canonical_license: bytes | None,
) -> list[str]:
    errors: list[str] = []
    try:
        license_payload = _wheel_license_payload(wheel_path, dist_info_dir)
        if canonical_license is not None and license_payload != canonical_license:
            errors.append(
                f"{wheel_path.name}: PEP 639 LICENSE payload differs from the canonical LICENSE"
            )
    except (OSError, ReleaseSmokeError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        errors.append(str(exc))
    try:
        _validate_wheel_import_payload(
            wheel_path,
            import_name=record["import_name"],
        )
    except (OSError, ReleaseSmokeError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
    try:
        errors.extend(
            _validate_wheel_entry_points(
                wheel_path,
                record=record,
                dist_info_dir=dist_info_dir,
            )
        )
    except (OSError, ReleaseSmokeError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
    return errors


def _validate_sdist_payload(
    sdist_path: Path,
    *,
    record: dict[str, Any],
    sdist_root: str,
    canonical_license: bytes | None,
) -> list[str]:
    errors: list[str] = []
    try:
        license_payload = _sdist_license_payload(sdist_path, sdist_root)
        if canonical_license is not None and license_payload != canonical_license:
            errors.append(
                f"{sdist_path.name}: LICENSE payload differs from the canonical LICENSE"
            )
    except (OSError, ReleaseSmokeError, tarfile.TarError, UnicodeDecodeError) as exc:
        errors.append(str(exc))
    try:
        _validate_sdist_import_payload(
            sdist_path,
            sdist_root=sdist_root,
            import_name=record["import_name"],
        )
    except (OSError, ReleaseSmokeError, tarfile.TarError) as exc:
        errors.append(str(exc))
    return errors


def validate_artifact_set(
    distributions: list[dict[str, Any]],
    wheels: list[Path],
    sdists: list[Path],
    expected_version: str,
    canonical_license_path: Path | None = None,
) -> dict[str, Any]:
    """
    Validate a complete RC artifact set against authoritative source metadata.

    Every artifact must map exactly once to a publishable source distribution,
    reproduce its PEP 621 metadata, and contain the prescribed PEP 639 and
    import payload members.
    """
    errors: list[str] = []
    canonical_license_path = canonical_license_path or ROOT / "LICENSE"
    canonical_license: bytes | None = None
    if canonical_license_path.is_file():
        canonical_license = canonical_license_path.read_bytes()
    else:
        errors.append(f"canonical LICENSE file is missing: {canonical_license_path}")

    try:
        records_by_normalized_name = authoritative_distribution_records(distributions)
    except ReleaseSmokeError as exc:
        records_by_normalized_name = {}
        errors.append(str(exc))

    if len(records_by_normalized_name) != PUBLISHABLE_DISTRIBUTION_COUNT:
        errors.append(
            "authoritative release set must contain "
            f"{PUBLISHABLE_DISTRIBUTION_COUNT} distributions, found "
            f"{len(records_by_normalized_name)}"
        )
    for record in records_by_normalized_name.values():
        if record["version"] != expected_version:
            errors.append(
                f"{record['pyproject_path']}: authoritative source version "
                f"{record['version']!r} does not equal expected {expected_version!r}"
            )

    if len(wheels) != PUBLISHABLE_DISTRIBUTION_COUNT:
        errors.append(
            f"expected {PUBLISHABLE_DISTRIBUTION_COUNT} wheels, found {len(wheels)}"
        )
    if len(sdists) != PUBLISHABLE_DISTRIBUTION_COUNT:
        errors.append(
            f"expected {PUBLISHABLE_DISTRIBUTION_COUNT} sdists, found {len(sdists)}"
        )

    all_artifacts = wheels + sdists
    for artifact in all_artifacts:
        if not artifact.is_file():
            errors.append(f"artifact file does not exist: {artifact}")
        if _is_workspace_artifact_filename(artifact.name):
            errors.append(f"ariadion-workspace artifact must not be present: {artifact.name}")

    wheel_names: list[str] = []
    for wheel_path in wheels:
        if not wheel_path.is_file():
            continue
        try:
            metadata, dist_info_dir = _read_wheel_metadata(wheel_path)
        except (OSError, ReleaseSmokeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
            errors.append(str(exc))
            continue

        record, normalized_name = _resolve_artifact_record(
            metadata,
            artifact_name=wheel_path.name,
            records_by_normalized_name=records_by_normalized_name,
            errors=errors,
        )
        if normalized_name is not None:
            wheel_names.append(normalized_name)
        if record is None:
            continue

        expected_dist_info_dir = (
            f"{_artifact_filename_component(record['name'])}-{record['version']}.dist-info"
        )
        if dist_info_dir != expected_dist_info_dir:
            errors.append(
                f"{wheel_path.name}: dist-info directory is {dist_info_dir!r}, expected "
                f"{expected_dist_info_dir!r}"
            )
        errors.extend(_validate_wheel_filename(wheel_path, record))
        errors.extend(
            _validate_core_metadata(
                metadata,
                artifact_name=wheel_path.name,
                expected_version=expected_version,
                record=record,
                records_by_normalized_name=records_by_normalized_name,
            )
        )
        errors.extend(
            _validate_wheel_payload(
                wheel_path,
                record=record,
                dist_info_dir=dist_info_dir,
                canonical_license=canonical_license,
            )
        )

    sdist_names: list[str] = []
    for sdist_path in sdists:
        if not sdist_path.is_file():
            continue
        try:
            metadata, sdist_root = _read_sdist_metadata(sdist_path)
        except (OSError, ReleaseSmokeError, UnicodeDecodeError, tarfile.TarError) as exc:
            errors.append(str(exc))
            continue

        record, normalized_name = _resolve_artifact_record(
            metadata,
            artifact_name=sdist_path.name,
            records_by_normalized_name=records_by_normalized_name,
            errors=errors,
        )
        if normalized_name is not None:
            sdist_names.append(normalized_name)
        if record is None:
            continue

        errors.extend(_validate_sdist_root(sdist_root, record))
        errors.extend(_validate_sdist_filename(sdist_path, record))
        errors.extend(
            _validate_core_metadata(
                metadata,
                artifact_name=sdist_path.name,
                expected_version=expected_version,
                record=record,
                records_by_normalized_name=records_by_normalized_name,
            )
        )
        errors.extend(
            _validate_sdist_payload(
                sdist_path,
                record=record,
                sdist_root=sdist_root,
                canonical_license=canonical_license,
            )
        )

    expected_names = set(records_by_normalized_name)
    errors.extend(
        _validate_observed_distribution_names("wheel", wheel_names, expected_names)
    )
    errors.extend(
        _validate_observed_distribution_names("sdist", sdist_names, expected_names)
    )

    try:
        manifest = generate_sha256_manifest(all_artifacts)
    except ReleaseSmokeError as exc:
        manifest = {}
        errors.append(str(exc))
    expected_manifest_count = PUBLISHABLE_DISTRIBUTION_COUNT * 2
    if len(manifest) != expected_manifest_count:
        errors.append(
            f"expected {expected_manifest_count} SHA-256 manifest entries, found {len(manifest)}"
        )

    if errors:
        raise ReleaseSmokeError(
            f"artifact validation found {len(errors)} problem(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return {
        "wheels": len(wheels),
        "sdists": len(sdists),
        "version": expected_version,
        "manifest": manifest,
    }


def run_release_smoke(
    *,
    root: Path | None = None,
    wheelhouse: Path | None = None,
    venv_dir: Path | None = None,
    list_only: bool = False,
    with_numpy: bool = False,
    requested_numpy_version: str = RELEASE_SMOKE_NUMPY_VERSION,
) -> dict[str, Any]:
    root = (root or ROOT).resolve()
    if wheelhouse is None:
        raise ReleaseSmokeError("a wheelhouse path is required")
    wheelhouse = wheelhouse.resolve()
    distributions = publishable_distributions(root)

    if list_only:
        return {
            "distributions": [entry["name"] for entry in distributions],
            "wheelhouse": str(wheelhouse),
            "list_only": True,
        }

    _require_empty_directory(wheelhouse, label="wheelhouse")
    for entry in distributions:
        member_dir = entry["path"]
        command = build_wheel_command(member_dir, wheelhouse)
        try:
            _run_command(command, cwd=root)
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"wheel build failed for {entry['name']}: {exc}") from exc

    if with_numpy:
        try:
            _run_command(
                download_numpy_command(wheelhouse, requested_numpy_version),
                cwd=root,
            )
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"NumPy wheel download failed: {exc}") from exc

    wheel_files = sorted(path for path in wheelhouse.glob("*.whl") if path.is_file())
    missing_wheels = _missing_distribution_wheels(distributions, wheel_files)
    if missing_wheels:
        raise ReleaseSmokeError(
            "wheel build did not produce distributions: " + ", ".join(missing_wheels)
        )

    if venv_dir is None:
        venv_dir = Path(tempfile.mkdtemp(prefix="ariadion-release-smoke-"))
    else:
        venv_dir = venv_dir.resolve()
        _require_empty_directory(venv_dir, label="virtual environment directory")
    if _is_within(venv_dir, root):
        raise ReleaseSmokeError(
            f"virtual environment must be outside the repository checkout: {venv_dir}"
        )
    _run_command(build_venv_command(venv_dir), cwd=root)

    venv_python = _venv_python(venv_dir)
    install_command = install_from_wheelhouse_command(
        venv_python,
        wheelhouse,
        with_numpy=with_numpy,
    )
    try:
        _run_command(install_command, cwd=venv_dir)
        _run_command(
            install_all_distributions_command(
                venv_python,
                wheelhouse,
                distributions,
                with_numpy=with_numpy,
            ),
            cwd=venv_dir,
        )
        _run_command([str(venv_python), "-m", "pip", "--isolated", "check"], cwd=venv_dir)
    except ReleaseSmokeError as exc:
        raise ReleaseSmokeError(f"package installation failed: {exc}") from exc

    smoke_dir = Path(tempfile.mkdtemp(prefix="ariadion-installed-smoke-"))
    if _is_within(smoke_dir, root):
        raise ReleaseSmokeError(f"smoke working directory is inside the checkout: {smoke_dir}")
    resolved_numpy_version: str | None = None
    runtime_version: str | None = None
    installed_distribution_names = [
        entry["name"]
        for entry in distributions
        if with_numpy or entry["name"] != "ariadion-simulator-numpy"
    ]
    try:
        try:
            _run_command([str(venv_python), "-c", sdk_smoke_script()], cwd=smoke_dir)
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"SDK smoke test failed: {exc}") from exc

        cli_command = cli_smoke_command(venv_dir)
        try:
            cli_result = _run_command(
                cli_command + ["demo", "bell"],
                cwd=smoke_dir,
                sanitize_cli_encoding=True,
            )
            _assert_cli_smoke_output(cli_result.stdout)
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"CLI smoke test failed: {exc}") from exc

        try:
            _run_command([str(venv_python), "-c", installed_report_smoke_script()], cwd=smoke_dir)
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"installed report smoke test failed: {exc}") from exc

        try:
            version_result = _run_command(
                [str(venv_python), "-c", runtime_version_check_script()], cwd=smoke_dir
            )
            runtime_version = version_result.stdout.strip().split(":", 1)[-1]
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"runtime version check failed: {exc}") from exc

        try:
            _run_command(
                [
                    str(venv_python),
                    "-c",
                    all_imports_smoke_script(installed_distribution_names),
                ],
                cwd=smoke_dir,
            )
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"all-package import smoke failed: {exc}") from exc

        if with_numpy:
            try:
                numpy_result = _run_command(
                    [str(venv_python), "-c", numpy_smoke_script()],
                    cwd=smoke_dir,
                )
                resolved_numpy_version = _extract_numpy_version(numpy_result.stdout)
                _assert_numpy_version_matches(
                    resolved_numpy_version,
                    requested_numpy_version,
                )
            except ReleaseSmokeError as exc:
                raise ReleaseSmokeError(f"optional NumPy smoke test failed: {exc}") from exc
    finally:
        shutil.rmtree(smoke_dir, ignore_errors=True)

    return {
        "distributions": [entry["name"] for entry in distributions],
        "wheelhouse": str(wheelhouse),
        "wheel_count": len(wheel_files),
        "wheel_files": [path.name for path in wheel_files],
        "venv_dir": str(venv_dir),
        "list_only": False,
        "with_numpy": with_numpy,
        "numpy_version": resolved_numpy_version,
        "requested_numpy_version": requested_numpy_version if with_numpy else None,
        "runtime_version": runtime_version,
        "import_count": len(installed_distribution_names),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Ariadion wheels and smoke-test the installed SDK/CLI"
    )
    parser.add_argument(
        "--wheelhouse",
        required=True,
        help="destination directory for built wheels",
    )
    parser.add_argument(
        "--venv-dir",
        help="optional empty virtualenv directory outside the repository checkout",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="discover and print workspace distributions without building",
    )
    parser.add_argument(
        "--with-numpy",
        action="store_true",
        help="download a NumPy wheel and validate the optional NumPy backend",
    )
    parser.add_argument(
        "--numpy-version",
        default=None,
        help=(
            "exact NumPy version used with --with-numpy "
            f"(default: {RELEASE_SMOKE_NUMPY_VERSION})"
        ),
    )
    parser.add_argument(
        "--validate-artifacts",
        metavar="SDIST_DIR",
        help=(
            "build wheels and sdists into the supplied directories, run strict Twine checks, "
            "and validate the complete artifact set; requires the 'build' and 'twine' packages"
        ),
    )
    return parser


def _validate_argument_combinations(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Reject combinations that would mix installed-smoke and artifact-only modes."""
    if args.validate_artifacts is not None:
        incompatible_options = []
        if args.list:
            incompatible_options.append("--list")
        if args.with_numpy:
            incompatible_options.append("--with-numpy")
        if args.numpy_version is not None:
            incompatible_options.append("--numpy-version")
        if args.venv_dir is not None:
            incompatible_options.append("--venv-dir")
        if incompatible_options:
            parser.error(
                "--validate-artifacts cannot be combined with "
                + ", ".join(incompatible_options)
            )
    elif args.numpy_version is not None and not args.with_numpy:
        parser.error("--numpy-version requires --with-numpy")


def _run_validate_artifacts(
    root: Path,
    wheelhouse: Path,
    sdist_dir: Path,
    distributions: list[dict[str, Any]],
    expected_version: str,
) -> dict[str, Any]:
    """Build sdists, run Twine, and validate the full 30-artifact set."""
    root = root.resolve()
    wheelhouse = wheelhouse.resolve()
    sdist_dir = sdist_dir.resolve()
    _require_empty_directory(sdist_dir, label="sdist directory")
    for entry in distributions:
        member_dir = entry["path"]
        command = build_sdist_command(member_dir, sdist_dir)
        try:
            _run_command(command, cwd=root)
        except ReleaseSmokeError as exc:
            raise ReleaseSmokeError(f"sdist build failed for {entry['name']}: {exc}") from exc

    wheel_files = sorted(p for p in wheelhouse.glob("*.whl") if p.is_file())
    sdist_files = sorted(p for p in sdist_dir.glob("*.tar.gz") if p.is_file())

    all_artifacts = sorted(wheel_files + sdist_files)
    try:
        _run_command(twine_check_command(all_artifacts), cwd=root)
    except ReleaseSmokeError as exc:
        raise ReleaseSmokeError(f"Twine strict check failed: {exc}") from exc

    return validate_artifact_set(
        distributions,
        wheel_files,
        sdist_files,
        expected_version,
        canonical_license_path=root / "LICENSE",
    )


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    _validate_argument_combinations(parser, args)

    root = ROOT.resolve()
    wheelhouse = Path(args.wheelhouse).resolve()
    validate_sdist_dir = (
        Path(args.validate_artifacts).resolve() if args.validate_artifacts else None
    )

    if validate_sdist_dir is not None:
        # Artifact validation mode: build wheels + sdists, Twine check, validate.
        distributions = publishable_distributions(root)
        try:
            _require_empty_directory(wheelhouse, label="wheelhouse")
        except ReleaseSmokeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for entry in distributions:
            command = build_wheel_command(entry["path"], wheelhouse)
            try:
                _run_command(command, cwd=root)
            except ReleaseSmokeError as exc:
                print(f"wheel build failed for {entry['name']}: {exc}", file=sys.stderr)
                return 1
        project_version = next(
            (
                _load_pyproject(entry["pyproject_path"]).get("project", {}).get("version", "")
                for entry in distributions
            ),
            "",
        )
        try:
            validation = _run_validate_artifacts(
                root=root,
                wheelhouse=wheelhouse,
                sdist_dir=validate_sdist_dir,
                distributions=distributions,
                expected_version=project_version,
            )
        except ReleaseSmokeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(
            "Artifact validation passed "
            f"({validation['wheels']} wheels, {validation['sdists']} sdists)"
        )
        print(f"Version: {validation['version']}")
        print("SHA-256 manifest:")
        for filename, digest in sorted(validation["manifest"].items()):
            print(f"  {digest}  {filename}")
        return 0

    try:
        result = run_release_smoke(
            root=root,
            wheelhouse=wheelhouse,
            venv_dir=Path(args.venv_dir) if args.venv_dir else None,
            list_only=args.list,
            with_numpy=args.with_numpy,
            requested_numpy_version=args.numpy_version or RELEASE_SMOKE_NUMPY_VERSION,
        )
    except ReleaseSmokeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result["list_only"]:
        for name in result["distributions"]:
            print(name)
        return 0

    print("Built distributions:")
    for name in result["distributions"]:
        print(f"- {name}")
    print(f"Wheel count: {result['wheel_count']}")
    print(f"Wheelhouse: {result['wheelhouse']}")
    print(f"Virtualenv: {result['venv_dir']}")
    print("SDK smoke: passed")
    print("CLI smoke: passed")
    print("Installed report smoke: passed")
    print(f"Runtime version check: passed (ariadion {result['runtime_version']})")
    print(f"All-package import smoke: passed ({result['import_count']} packages)")
    if result["with_numpy"]:
        print(
            "Optional NumPy backend smoke: passed "
            f"(numpy {result['numpy_version']}, requested {result['requested_numpy_version']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
