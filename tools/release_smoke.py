from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SMOKE_NUMPY_VERSION = "2.4.6"


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


def download_numpy_command(wheelhouse: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "download",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        f"numpy=={RELEASE_SMOKE_NUMPY_VERSION}",
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


def run_release_smoke(
    *,
    root: Path | None = None,
    wheelhouse: Path | None = None,
    venv_dir: Path | None = None,
    list_only: bool = False,
    with_numpy: bool = False,
) -> dict[str, Any]:
    root = root or ROOT
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
            _run_command(download_numpy_command(wheelhouse), cwd=root)
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
        _run_command([str(venv_python), "-m", "pip", "--isolated", "check"], cwd=venv_dir)
    except ReleaseSmokeError as exc:
        raise ReleaseSmokeError(f"package installation failed: {exc}") from exc

    smoke_dir = Path(tempfile.mkdtemp(prefix="ariadion-installed-smoke-"))
    if _is_within(smoke_dir, root):
        raise ReleaseSmokeError(f"smoke working directory is inside the checkout: {smoke_dir}")
    numpy_version: str | None = None
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

        if with_numpy:
            try:
                numpy_result = _run_command([str(venv_python), "-c", numpy_smoke_script()], cwd=smoke_dir)
                numpy_version = _extract_numpy_version(numpy_result.stdout)
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
        "numpy_version": numpy_version,
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Ariadion wheels and smoke-test the installed SDK/CLI")
    parser.add_argument("--wheelhouse", required=True, help="destination directory for built wheels")
    parser.add_argument(
        "--venv-dir",
        help="optional empty virtualenv directory outside the repository checkout",
    )
    parser.add_argument("--list", action="store_true", help="discover and print workspace distributions without building")
    parser.add_argument(
        "--with-numpy",
        action="store_true",
        help="download a NumPy wheel and validate the optional NumPy backend",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        result = run_release_smoke(
            root=ROOT,
            wheelhouse=Path(args.wheelhouse),
            venv_dir=Path(args.venv_dir) if args.venv_dir else None,
            list_only=args.list,
            with_numpy=args.with_numpy,
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
    if result["with_numpy"]:
        print(
            "Optional NumPy backend smoke: passed "
            f"(numpy {result['numpy_version']}, pinned {RELEASE_SMOKE_NUMPY_VERSION})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
