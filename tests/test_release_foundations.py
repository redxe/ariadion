from __future__ import annotations

import os
import re
import subprocess
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_smoke import (
    RELEASE_SMOKE_NUMPY_VERSION,
    ReleaseSmokeError,
    _assert_numpy_version_matches_pin,
    _assert_cli_smoke_output,
    _extract_numpy_version,
    _is_within,
    _missing_distribution_wheels,
    _subprocess_environment,
    build_wheel_command,
    cli_smoke_command,
    download_numpy_command,
    discover_workspace_distributions,
    install_from_wheelhouse_command,
    installed_report_smoke_script,
    numpy_smoke_script,
    publishable_distributions,
    run_release_smoke,
    sdk_smoke_script,
)


class ReleaseFoundationsTests(unittest.TestCase):
    _EXPECTED_RC_VERSION = "0.1.0rc1"
    _EXPECTED_PUBLISHABLE = {
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
    }
    _EXPECTED_EXTERNAL_DEPENDENCIES = {
        "packages/simulator-numpy/pyproject.toml": ["numpy>=1.26"],
    }

    def _load_project_metadata(self, path: Path) -> dict[str, object]:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        project = document.get("project")
        self.assertIsInstance(project, dict)
        return project

    def _dependency_name(self, dependency: str) -> str:
        token = dependency.split(";", 1)[0].strip()
        return re.split(r"[ <>=!~\[]", token, 1)[0]

    def test_discover_workspace_distributions(self) -> None:
        distributions = discover_workspace_distributions(Path(__file__).resolve().parents[1])
        self.assertTrue(distributions)
        names = [entry["name"] for entry in distributions]
        self.assertIn("ariadion-core", names)
        self.assertIn("ariadion", names)
        self.assertIn("ariadion-cli", names)
        self.assertEqual(len(names), len(set(names)))

    def test_publishable_distributions_match_expected_release_set_and_count(self) -> None:
        distributions = publishable_distributions(Path(__file__).resolve().parents[1])
        names = {entry["name"] for entry in distributions}
        self.assertEqual(len(distributions), 15)
        self.assertSetEqual(names, self._EXPECTED_PUBLISHABLE)

    def test_publishable_distributions_use_rc_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            project = self._load_project_metadata(entry["pyproject_path"])
            self.assertEqual(project.get("version"), self._EXPECTED_RC_VERSION)

    def test_root_workspace_uses_rc_version(self) -> None:
        project = self._load_project_metadata(Path(__file__).resolve().parents[1] / "pyproject.toml")
        self.assertEqual(project.get("name"), "ariadion-workspace")
        self.assertEqual(project.get("version"), self._EXPECTED_RC_VERSION)

    def test_publishable_internal_dependencies_are_exact_rc_pins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            project = self._load_project_metadata(entry["pyproject_path"])
            dependencies = project.get("dependencies", [])
            self.assertIsInstance(dependencies, list)
            for dependency in dependencies:
                self.assertIsInstance(dependency, str)
                dependency_name = self._dependency_name(dependency)
                if dependency_name in self._EXPECTED_PUBLISHABLE:
                    self.assertEqual(dependency, f"{dependency_name}=={self._EXPECTED_RC_VERSION}")

    def test_external_dependency_constraints_remain_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        external_by_path: dict[str, list[str]] = {}
        for pyproject_path in sorted(root.glob("**/pyproject.toml")):
            relative = str(pyproject_path.relative_to(root)).replace("\\", "/")
            project = self._load_project_metadata(pyproject_path)
            dependencies = project.get("dependencies", [])
            self.assertIsInstance(dependencies, list)
            external = [
                dependency
                for dependency in dependencies
                if isinstance(dependency, str)
                and self._dependency_name(dependency) not in self._EXPECTED_PUBLISHABLE
            ]
            if external:
                external_by_path[relative] = external
        self.assertEqual(external_by_path, self._EXPECTED_EXTERNAL_DEPENDENCIES)

    def test_build_system_constraints_remain_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for pyproject_path in sorted(root.glob("**/pyproject.toml")):
            relative = str(pyproject_path.relative_to(root)).replace("\\", "/")
            document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            build_system = document.get("build-system")
            if relative == "pyproject.toml":
                self.assertIsNone(build_system)
                continue
            self.assertIsInstance(build_system, dict)
            assert isinstance(build_system, dict)
            self.assertEqual(build_system.get("requires"), ["setuptools>=68"])

    def test_build_wheel_command_uses_wheelhouse(self) -> None:
        wheelhouse = Path("/tmp/wheels")
        command = build_wheel_command(Path("/tmp/pkg"), wheelhouse)
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:5], ["-m", "pip", "--isolated", "wheel"])
        self.assertEqual(command[5], str(Path("/tmp/pkg")))
        self.assertEqual(command[6], "--wheel-dir")
        self.assertEqual(command[7], str(wheelhouse))
        self.assertEqual(command[-1], "--no-deps")

    def test_install_command_uses_only_the_local_wheelhouse(self) -> None:
        command = install_from_wheelhouse_command(
            Path("/tmp/venv/python"),
            Path("/tmp/wheels"),
        )
        self.assertIn("--isolated", command)
        self.assertIn("--no-index", command)
        self.assertEqual(command[-2:], ["ariadion", "ariadion-cli"])
        self.assertNotIn("ariadion-simulator-numpy", command)

    def test_optional_install_and_download_commands_include_numpy_boundary(self) -> None:
        wheelhouse = Path("/tmp/wheels")
        install = install_from_wheelhouse_command(
            Path("/tmp/venv/python"),
            wheelhouse,
            with_numpy=True,
        )
        download = download_numpy_command(wheelhouse)
        self.assertEqual(install[-1], "ariadion-simulator-numpy")
        self.assertIn("--only-binary=:all:", download)
        self.assertEqual(download[-1], f"numpy=={RELEASE_SMOKE_NUMPY_VERSION}")

    def test_cli_smoke_command_uses_windows_entrypoint(self) -> None:
        venv_dir = Path("/tmp/venv")
        with patch("tools.release_smoke.os.name", "nt"):
            command = cli_smoke_command(venv_dir)
        self.assertEqual(command, [str(venv_dir / "Scripts" / "ariadion.exe")])

    def test_cli_smoke_command_uses_posix_entrypoint(self) -> None:
        venv_dir = Path("/tmp/venv")
        with patch("tools.release_smoke.os.name", "posix"):
            command = cli_smoke_command(venv_dir)
        self.assertEqual(command, [str(venv_dir / "bin" / "ariadion")])

    def test_smoke_scripts_execute_sdk_and_optional_backend(self) -> None:
        self.assertIn("run(program)", sdk_smoke_script())
        self.assertIn("NumpyStateVectorBackend", numpy_smoke_script())
        self.assertIn("backend.execute(reference.ir)", numpy_smoke_script())
        self.assertIn("numpy.__version__", numpy_smoke_script())

    def test_installed_report_smoke_script_covers_noise_bare_and_protection_reports(self) -> None:
        script = installed_report_smoke_script()
        self.assertIn("build_density_noise_impact_report", script)
        self.assertIn("build_bare_reliability_report", script)
        self.assertIn("build_protection_requirement_report", script)
        self.assertIn("NOISE_IMPACT_SCHEMA_VERSION", script)
        self.assertIn("BARE_RELIABILITY_SCHEMA_VERSION", script)
        self.assertIn("PROTECTION_REQUIREMENT_SCHEMA_VERSION", script)
        self.assertIn("installed-report-smoke-ok", script)

    def test_installed_report_smoke_script_compiles(self) -> None:
        compile(installed_report_smoke_script(), "<installed-report-smoke>", "exec")

    def test_numpy_pin_mismatch_raises_actionable_error(self) -> None:
        with self.assertRaisesRegex(
            ReleaseSmokeError,
            "resolved numpy 2.4.5, expected pinned 2.4.6",
        ):
            _assert_numpy_version_matches_pin("2.4.5")

    def test_numpy_pin_match_is_accepted(self) -> None:
        _assert_numpy_version_matches_pin(RELEASE_SMOKE_NUMPY_VERSION)

    def test_missing_distribution_wheels_detects_incomplete_artifacts(self) -> None:
        distributions = [{"name": "ariadion"}, {"name": "ariadion-cli"}]
        wheel_files = [Path("ariadion-0.1.0-py3-none-any.whl")]
        self.assertEqual(
            _missing_distribution_wheels(distributions, wheel_files),
            ["ariadion-cli"],
        )

    def test_nonempty_wheelhouse_is_rejected_before_building(self) -> None:
        wheelhouse = Path(tempfile.mkdtemp(prefix="ariadion-wheelhouse-"))
        try:
            (wheelhouse / "stale.whl").write_bytes(b"stale")
            with self.assertRaisesRegex(ReleaseSmokeError, "wheelhouse must be empty"):
                run_release_smoke(
                    root=Path(__file__).resolve().parents[1],
                    wheelhouse=wheelhouse,
                )
        finally:
            shutil.rmtree(wheelhouse, ignore_errors=True)

    def test_path_containment_distinguishes_checkout_and_system_temp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(_is_within(root / "build" / "venv", root))
        with tempfile.TemporaryDirectory(prefix="ariadion-outside-") as temporary:
            self.assertFalse(_is_within(Path(temporary), root))

    def test_subprocess_environment_removes_pythonpath(self) -> None:
        with patch.dict(
            "os.environ",
            {"PYTHONPATH": "x", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            clear=True,
        ):
            environment = _subprocess_environment()
        self.assertNotIn("PYTHONPATH", environment)
        self.assertIn("PYTHONUTF8", environment)
        self.assertIn("PYTHONIOENCODING", environment)

    def test_cli_subprocess_environment_sanitizes_encoding_overrides(self) -> None:
        with patch.dict(
            "os.environ",
            {"PYTHONPATH": "x", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            clear=True,
        ):
            environment = _subprocess_environment(sanitize_cli_encoding=True)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONUTF8", environment)
        self.assertNotIn("PYTHONIOENCODING", environment)

    def test_cli_smoke_output_requires_semantic_markers(self) -> None:
        _assert_cli_smoke_output("q0: ─[H]─\nq1: ─[X]─\n0.5")
        with self.assertRaisesRegex(ReleaseSmokeError, "semantic markers"):
            _assert_cli_smoke_output("q0: missing semantic content")

    def test_extract_numpy_version_requires_reported_version(self) -> None:
        self.assertEqual(_extract_numpy_version("numpy-smoke-ok:2.4.6"), "2.4.6")
        with self.assertRaisesRegex(ReleaseSmokeError, "did not report"):
            _extract_numpy_version("numpy-smoke-ok:")

    def test_run_release_smoke_base_uses_cli_env_sanitization_and_no_numpy_download(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-root-"))
        wheelhouse = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-wheelhouse-"))
        venv_dir = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-venv-"))
        try:
            distributions = [
                {"name": "ariadion", "path": root / "packages" / "sdk"},
                {"name": "ariadion-cli", "path": root / "apps" / "cli"},
            ]
            commands: list[tuple[list[str], bool]] = []

            def fake_run_command(
                command: list[str],
                *,
                cwd: Path | None = None,
                sanitize_cli_encoding: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                del cwd
                commands.append((command, sanitize_cli_encoding))
                if command[-2:] == ["demo", "bell"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="q0: ─[H]─\nq1: ─[X]─\n0.5\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

            with patch("tools.release_smoke.publishable_distributions", return_value=distributions), patch(
                "tools.release_smoke._missing_distribution_wheels", return_value=[]
            ), patch("tools.release_smoke._run_command", side_effect=fake_run_command):
                result = run_release_smoke(
                    root=root,
                    wheelhouse=wheelhouse,
                    venv_dir=venv_dir,
                    with_numpy=False,
                )

            self.assertFalse(result["with_numpy"])
            self.assertIsNone(result["numpy_version"])
            self.assertFalse(any("download" in command for command, _ in commands))
            self.assertFalse(any("ariadion-simulator-numpy" in " ".join(command) for command, _ in commands))
            expected_venv_python = str(
                venv_dir / "Scripts" / "python.exe"
                if os.name == "nt"
                else venv_dir / "bin" / "python"
            )
            generated_report_script = installed_report_smoke_script()
            installed_report_commands = [
                command
                for command, _ in commands
                if len(command) > 2
                and command[0] == expected_venv_python
                and command[1] == "-c"
                and generated_report_script in command[2]
                and "installed-report-smoke-ok" in command[2]
            ]
            self.assertEqual(len(installed_report_commands), 1)
            self.assertTrue(any(sanitized for command, sanitized in commands if command[-2:] == ["demo", "bell"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(wheelhouse, ignore_errors=True)
            shutil.rmtree(venv_dir, ignore_errors=True)

    def test_run_release_smoke_numpy_reports_resolved_version(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-root-"))
        wheelhouse = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-wheelhouse-"))
        venv_dir = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-venv-"))
        try:
            distributions = [
                {"name": "ariadion", "path": root / "packages" / "sdk"},
                {"name": "ariadion-cli", "path": root / "apps" / "cli"},
            ]

            def fake_run_command(
                command: list[str],
                *,
                cwd: Path | None = None,
                sanitize_cli_encoding: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, sanitize_cli_encoding
                if command[-2:] == ["demo", "bell"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="q0: ─[H]─\nq1: ─[X]─\n0.5\n",
                        stderr="",
                    )
                if len(command) > 2 and command[1] == "-c" and "numpy-smoke-ok" in command[2]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"numpy-smoke-ok:{RELEASE_SMOKE_NUMPY_VERSION}\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

            with patch("tools.release_smoke.publishable_distributions", return_value=distributions), patch(
                "tools.release_smoke._missing_distribution_wheels", return_value=[]
            ), patch("tools.release_smoke._run_command", side_effect=fake_run_command):
                result = run_release_smoke(
                    root=root,
                    wheelhouse=wheelhouse,
                    venv_dir=venv_dir,
                    with_numpy=True,
                )

            self.assertEqual(result["numpy_version"], RELEASE_SMOKE_NUMPY_VERSION)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(wheelhouse, ignore_errors=True)
            shutil.rmtree(venv_dir, ignore_errors=True)

    def test_run_release_smoke_numpy_mismatch_fails_with_actionable_message(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-root-"))
        wheelhouse = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-wheelhouse-"))
        venv_dir = Path(tempfile.mkdtemp(prefix="ariadion-release-foundations-venv-"))
        try:
            distributions = [
                {"name": "ariadion", "path": root / "packages" / "sdk"},
                {"name": "ariadion-cli", "path": root / "apps" / "cli"},
            ]

            def fake_run_command(
                command: list[str],
                *,
                cwd: Path | None = None,
                sanitize_cli_encoding: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, sanitize_cli_encoding
                if command[-2:] == ["demo", "bell"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="q0: ─[H]─\nq1: ─[X]─\n0.5\n",
                        stderr="",
                    )
                if len(command) > 2 and command[1] == "-c" and "numpy-smoke-ok" in command[2]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="numpy-smoke-ok:2.4.5\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

            with patch("tools.release_smoke.publishable_distributions", return_value=distributions), patch(
                "tools.release_smoke._missing_distribution_wheels", return_value=[]
            ), patch("tools.release_smoke._run_command", side_effect=fake_run_command):
                with self.assertRaisesRegex(
                    ReleaseSmokeError,
                    "resolved numpy 2.4.5, expected pinned 2.4.6",
                ):
                    run_release_smoke(
                        root=root,
                        wheelhouse=wheelhouse,
                        venv_dir=venv_dir,
                        with_numpy=True,
                    )
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(wheelhouse, ignore_errors=True)
            shutil.rmtree(venv_dir, ignore_errors=True)

    def test_ci_workflow_runs_release_smoke_in_separate_pristine_job(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  test:\n", workflow)
        self.assertIn("  release-smoke:\n", workflow)
        self.assertIn('python-version: ["3.11", "3.12"]', workflow)
        release_block = workflow.split("  release-smoke:\n", 1)[1]
        self.assertIn("actions/checkout@v4", release_block)
        self.assertIn("tools/release_smoke.py --wheelhouse build/wheels", release_block)
        self.assertIn("tools/release_smoke.py --wheelhouse build/numpy-wheels --with-numpy", release_block)
        self.assertNotIn("tools/test.py", release_block)
        self.assertNotIn("compileall", release_block)

    def test_run_release_smoke_lists_distributions(self) -> None:
        wheelhouse = Path(tempfile.mkdtemp(prefix="ariadion-wheelhouse-"))
        try:
            result = run_release_smoke(
                root=Path(__file__).resolve().parents[1],
                wheelhouse=wheelhouse,
                venv_dir=None,
                list_only=True,
            )
        finally:
            if wheelhouse.exists():
                shutil.rmtree(wheelhouse)
        self.assertTrue(result["list_only"])
        self.assertTrue(result["distributions"])
        self.assertIn("ariadion", result["distributions"])
        self.assertIn("ariadion-cli", result["distributions"])


if __name__ == "__main__":
    unittest.main()
