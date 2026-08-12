from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import warnings
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from tools.release_smoke import (
    EXPECTED_RC3_DEPENDENCY_GRAPH,
    PUBLISHABLE_DISTRIBUTION_COUNT,
    RELEASE_SMOKE_MINIMUM_NUMPY_VERSION,
    RELEASE_SMOKE_NUMPY_VERSION,
    ROOT,
    ReleaseSmokeError,
    _assert_cli_smoke_output,
    _assert_numpy_version_matches_pin,
    _extract_numpy_version,
    _is_within,
    _missing_distribution_wheels,
    _subprocess_environment,
    _validate_argument_combinations,
    all_imports_smoke_script,
    authoritative_distribution_records,
    build_argument_parser,
    build_sdist_command,
    build_wheel_command,
    cli_smoke_command,
    discover_workspace_distributions,
    download_numpy_command,
    generate_sha256_manifest,
    install_all_distributions_command,
    install_from_wheelhouse_command,
    installed_report_smoke_script,
    main,
    numpy_smoke_script,
    publishable_distributions,
    run_release_smoke,
    runtime_version_check_script,
    sdk_smoke_script,
    twine_check_command,
    validate_artifact_set,
)
from tools.release_contract import (
    PUBLISHABLE_PROJECTS,
    RELEASE_BUNDLE_NAME,
    RELEASE_TAG,
    RELEASE_VERSION,
)
from tools.verify_index_release import (
    ARTIFACT_COUNT,
    MAX_ARTIFACT_BYTES,
    MAX_METADATA_BYTES,
    MAX_REDIRECTS,
    PUBLISHABLE_DISTRIBUTIONS,
    IndexName,
    IndexReleaseError,
    _ApprovedRedirectHandler,
    _UrlPolicy,
    download_verified_artifacts,
    fetch_release_metadata,
    load_manifest,
    require_release_absent,
    verify_release_files,
    wait_for_verified_release,
)


class ReleaseFoundationsTests(unittest.TestCase):
    _EXPECTED_RC_VERSION = RELEASE_VERSION
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
        return re.split(r"[ <>=!~\[]", token, maxsplit=1)[0]

    def _index_release_fixture(self) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        manifest: dict[str, str] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for index, distribution in enumerate(PUBLISHABLE_DISTRIBUTIONS):
            component = distribution.replace("-", "_")
            filenames = (
                f"{component}-0.1.0rc3-py3-none-any.whl",
                f"{component}-0.1.0rc3.tar.gz",
            )
            urls = []
            for offset, filename in enumerate(filenames):
                digest = f"{index * 2 + offset:064x}"
                manifest[filename] = digest
                urls.append(
                    {
                        "filename": filename,
                        "url": f"https://files.pythonhosted.org/packages/{filename}",
                        "digests": {"sha256": digest},
                        "yanked": False,
                        "yanked_reason": None,
                    }
                )
            metadata[distribution] = {"urls": urls}
        return manifest, metadata

    def _artifact_fixture(self) -> dict[str, Any]:
        """Create a valid, local 15-distribution source and artifact release set."""
        root = Path(tempfile.mkdtemp(prefix="ariadion-artifact-fixture-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        canonical_license = b"Synthetic Apache-2.0 license payload\n"
        (root / "LICENSE").write_bytes(canonical_license)

        names = sorted(EXPECTED_RC3_DEPENDENCY_GRAPH)
        fixture: dict[str, Any] = {
            "root": root,
            "license": canonical_license,
            "records": {},
            "distributions": [],
            "wheel_paths": {},
            "sdist_paths": {},
            "wheels": [],
            "sdists": [],
        }
        for index, name in enumerate(names):
            import_name = name.replace("-", "_")
            dependencies = list(EXPECTED_RC3_DEPENDENCY_GRAPH[name])
            package_root = root / "sources" / f"package_{index:02d}"
            package_root.mkdir(parents=True)
            readme = f"# {name}\n\nSynthetic artifact fixture for {name}."
            summary = f"Synthetic {name} distribution."
            (package_root / "README.md").write_text(readme, encoding="utf-8")
            (package_root / "LICENSE").write_bytes(canonical_license)
            source_package = package_root / "src" / import_name
            source_package.mkdir(parents=True)
            (source_package / "__init__.py").write_text("", encoding="utf-8")
            pyproject = "\n".join(
                [
                    "[project]",
                    f"name = {json.dumps(name)}",
                    'version = "0.1.0rc3"',
                    f"description = {json.dumps(summary)}",
                    'readme = "README.md"',
                    'requires-python = ">=3.11"',
                    'license = "Apache-2.0"',
                    'license-files = ["LICENSE"]',
                    'authors = [{ name = "Vi Connelly" }]',
                    'classifiers = ["Programming Language :: Python :: 3.11"]',
                    f"dependencies = {json.dumps(dependencies)}",
                    "",
                    "[project.urls]",
                    'Homepage = "https://example.invalid/home"',
                    'Repository = "https://example.invalid/repository"',
                    "",
                ]
            )
            pyproject_path = package_root / "pyproject.toml"
            pyproject_path.write_text(pyproject, encoding="utf-8")
            record = {
                "name": name,
                "import_name": import_name,
                "summary": summary,
                "readme": readme,
                "dependencies": dependencies,
                "path": package_root,
                "pyproject_path": pyproject_path,
            }
            fixture["records"][name] = record
            fixture["distributions"].append(
                {
                    "name": name,
                    "path": package_root,
                    "pyproject_path": pyproject_path,
                }
            )

        for name in names:
            self._write_fixture_wheel(fixture, name)
            self._write_fixture_sdist(fixture, name)
        return fixture

    def _fixture_metadata(
        self,
        record: dict[str, Any],
        overrides: dict[str, Any] | None = None,
    ) -> str:
        values: dict[str, list[str]] = {
            "Metadata-Version": ["2.4"],
            "Name": [record["name"]],
            "Version": ["0.1.0rc3"],
            "Summary": [record["summary"]],
            "Requires-Python": [">=3.11"],
            "Description-Content-Type": ["text/markdown"],
            "License-Expression": ["Apache-2.0"],
            "License-File": ["LICENSE"],
            "Author": ["Vi Connelly"],
            "Project-URL": [
                "Homepage, https://example.invalid/home",
                "Repository, https://example.invalid/repository",
            ],
            "Classifier": ["Programming Language :: Python :: 3.11"],
            "Requires-Dist": list(record["dependencies"]),
        }
        description = record["readme"]
        if overrides:
            description = overrides.get("__description__", description)
            for header, replacement in overrides.items():
                if header == "__description__":
                    continue
                if replacement is None:
                    values[header] = []
                elif isinstance(replacement, list):
                    values[header] = replacement
                else:
                    values[header] = [replacement]
        headers = [
            f"{header}: {value}"
            for header, header_values in values.items()
            for value in header_values
        ]
        return "\n".join(headers) + "\n\n" + description

    def _replace_fixture_path(
        self,
        fixture: dict[str, Any],
        *,
        kind: str,
        name: str,
        path: Path,
    ) -> None:
        mapping_name = f"{kind}_paths"
        paths_name = f"{kind}s"
        previous = fixture[mapping_name].get(name)
        fixture[mapping_name][name] = path
        if previous is None:
            fixture[paths_name].append(path)
        else:
            fixture[paths_name] = [path if item == previous else item for item in fixture[paths_name]]

    def _write_fixture_wheel(
        self,
        fixture: dict[str, Any],
        name: str,
        *,
        filename: str | None = None,
        metadata_overrides: dict[str, Any] | None = None,
        license_payload: bytes | None = None,
        include_license: bool = True,
        legacy_license: bool = False,
        extra_license_members: list[str] | None = None,
        include_import: bool = True,
        import_variant: str = "regular",
        include_entry_points: bool = True,
        entry_points: str | None = None,
        duplicate_entry_points: bool = False,
        malformed: bool = False,
    ) -> Path:
        record = fixture["records"][name]
        component = re.sub(r"[-.]+", "_", name)
        dist_info = f"{component}-0.1.0rc3.dist-info"
        path = fixture["root"] / "wheels" / (
            filename or f"{component}-0.1.0rc3-py3-none-any.whl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if malformed:
            path.write_bytes(b"not a wheel archive")
            self._replace_fixture_path(fixture, kind="wheel", name=name, path=path)
            return path
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                f"{dist_info}/METADATA",
                self._fixture_metadata(record, metadata_overrides),
            )
            if include_license:
                archive.writestr(
                    f"{dist_info}/licenses/LICENSE",
                    fixture["license"] if license_payload is None else license_payload,
                )
            if legacy_license:
                archive.writestr(f"{dist_info}/LICENSE", fixture["license"])
            for extra_member in extra_license_members or []:
                archive.writestr(extra_member, fixture["license"])
            init_member = f"{record['import_name']}/__init__.py"
            if include_import:
                if import_variant == "regular":
                    archive.writestr(init_member, "")
                elif import_variant == "directory":
                    info = zipfile.ZipInfo(init_member)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFDIR | 0o755) << 16
                    archive.writestr(info, b"")
                else:
                    raise AssertionError(f"unknown import fixture variant: {import_variant}")
            if name == "ariadion-cli" and include_entry_points:
                entry_point_member = f"{dist_info}/entry_points.txt"
                entry_point_payload = (
                    entry_points or "[console_scripts]\nariadion = ariadion_cli:main\n"
                )
                archive.writestr(
                    entry_point_member,
                    entry_point_payload,
                )
                if duplicate_entry_points:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        archive.writestr(entry_point_member, entry_point_payload)
            elif name != "ariadion-cli" and entry_points is not None:
                archive.writestr(f"{dist_info}/entry_points.txt", entry_points)
        self._replace_fixture_path(fixture, kind="wheel", name=name, path=path)
        return path

    def _write_fixture_sdist(
        self,
        fixture: dict[str, Any],
        name: str,
        *,
        filename: str | None = None,
        metadata_overrides: dict[str, Any] | None = None,
        license_payload: bytes | None = None,
        include_license: bool = True,
        include_import: bool = True,
        import_variant: str = "regular",
        root_name: str | None = None,
        malformed: bool = False,
    ) -> Path:
        record = fixture["records"][name]
        component = re.sub(r"[-.]+", "_", name)
        root = root_name or f"{component}-0.1.0rc3"
        path = fixture["root"] / "sdists" / (
            filename or f"{component}-0.1.0rc3.tar.gz"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if malformed:
            path.write_bytes(b"not an sdist archive")
            self._replace_fixture_path(fixture, kind="sdist", name=name, path=path)
            return path

        def add_regular_file(archive: tarfile.TarFile, member_name: str, payload: bytes) -> None:
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))

        with tarfile.open(path, "w:gz") as archive:
            add_regular_file(
                archive,
                f"{root}/PKG-INFO",
                self._fixture_metadata(record, metadata_overrides).encode("utf-8"),
            )
            if include_license:
                add_regular_file(
                    archive,
                    f"{root}/LICENSE",
                    fixture["license"] if license_payload is None else license_payload,
                )
            init_member = f"{root}/src/{record['import_name']}/__init__.py"
            if include_import:
                if import_variant == "regular":
                    add_regular_file(archive, init_member, b"")
                elif import_variant == "symlink":
                    info = tarfile.TarInfo(init_member)
                    info.type = tarfile.SYMTYPE
                    info.linkname = "elsewhere"
                    archive.addfile(info)
                else:
                    raise AssertionError(f"unknown import fixture variant: {import_variant}")
        self._replace_fixture_path(fixture, kind="sdist", name=name, path=path)
        return path

    def _assert_fixture_rejected(self, fixture: dict[str, Any], pattern: str) -> None:
        with self.assertRaisesRegex(ReleaseSmokeError, pattern):
            validate_artifact_set(
                fixture["distributions"],
                fixture["wheels"],
                fixture["sdists"],
                expected_version="0.1.0rc3",
                canonical_license_path=fixture["root"] / "LICENSE",
            )

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

    def test_central_release_contract_matches_the_publishable_source_set(self) -> None:
        root = Path(__file__).resolve().parents[1]
        declared = {Path(path): name for path, name in PUBLISHABLE_PROJECTS}
        discovered = set((root / "packages").glob("*/pyproject.toml")) | {
            root / "apps" / "cli" / "pyproject.toml"
        }
        self.assertEqual(
            {root / path for path in declared},
            discovered,
        )
        self.assertSetEqual(set(declared.values()), self._EXPECTED_PUBLISHABLE)
        self.assertEqual(RELEASE_TAG, f"v{RELEASE_VERSION}")

    def test_actual_source_metadata_forms_the_authoritative_release_set(self) -> None:
        root = Path(__file__).resolve().parents[1]
        records = authoritative_distribution_records(publishable_distributions(root))
        self.assertEqual(len(records), PUBLISHABLE_DISTRIBUTION_COUNT)
        self.assertSetEqual(
            {record["name"] for record in records.values()},
            self._EXPECTED_PUBLISHABLE,
        )
        self.assertSetEqual(set(EXPECTED_RC3_DEPENDENCY_GRAPH), self._EXPECTED_PUBLISHABLE)

    def test_independent_dependency_graph_rejects_deleted_and_duplicated_source_edges(self) -> None:
        root = Path(__file__).resolve().parents[1]
        distributions = publishable_distributions(root)
        ir_entry = next(entry for entry in distributions if entry["name"] == "ariadion-ir")
        source_text = ir_entry["pyproject_path"].read_text(encoding="utf-8")
        expected_dependency_line = 'dependencies = ["ariadion-core==0.1.0rc3"]'
        self.assertIn(expected_dependency_line, source_text)
        replacements = {
            "deleted": "dependencies = []",
            "duplicated": (
                'dependencies = ["ariadion-core==0.1.0rc3", '
                '"ariadion-core==0.1.0rc3"]'
            ),
        }
        for label, replacement in replacements.items():
            with self.subTest(source_mutation=label), tempfile.TemporaryDirectory() as temporary:
                mutated_pyproject = Path(temporary) / "pyproject.toml"
                mutated_pyproject.write_text(
                    source_text.replace(expected_dependency_line, replacement, 1),
                    encoding="utf-8",
                )
                mutated_distributions = [
                    {
                        **entry,
                        "pyproject_path": (
                            mutated_pyproject
                            if entry["name"] == "ariadion-ir"
                            else entry["pyproject_path"]
                        ),
                    }
                    for entry in distributions
                ]
                with self.assertRaisesRegex(
                    ReleaseSmokeError,
                    "source dependency graph differs from the independent RC3 baseline",
                ):
                    authoritative_distribution_records(mutated_distributions)

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

    def test_build_system_requires_pep639_capable_setuptools(self) -> None:
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
            self.assertEqual(build_system.get("requires"), ["setuptools>=77.0.3"])

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

    def test_minimum_numpy_download_command_uses_declared_boundary(self) -> None:
        command = download_numpy_command(
            Path("/tmp/wheels"),
            RELEASE_SMOKE_MINIMUM_NUMPY_VERSION,
        )
        self.assertEqual(
            command[-1],
            f"numpy=={RELEASE_SMOKE_MINIMUM_NUMPY_VERSION}",
        )

    def test_all_distribution_install_command_respects_optional_numpy_boundary(self) -> None:
        distributions = [
            {"name": "ariadion"},
            {"name": "ariadion-cli"},
            {"name": "ariadion-simulator-numpy"},
            {"name": "ariadion-syntax"},
        ]
        base = install_all_distributions_command(
            Path("/tmp/venv/python"),
            Path("/tmp/wheels"),
            distributions,
            with_numpy=False,
        )
        numpy = install_all_distributions_command(
            Path("/tmp/venv/python"),
            Path("/tmp/wheels"),
            distributions,
            with_numpy=True,
        )
        self.assertNotIn("ariadion-simulator-numpy", base)
        self.assertIn("ariadion-simulator-numpy", numpy)
        self.assertIn("ariadion-syntax", base)
        self.assertIn("--no-index", base)

    def test_all_imports_smoke_script_imports_normalized_packages(self) -> None:
        script = all_imports_smoke_script(
            ["ariadion", "ariadion-cli", "ariadion-simulator-numpy"]
        )
        self.assertIn("ariadion_cli", script)
        self.assertIn("ariadion_simulator_numpy", script)
        self.assertIn("all-imports-smoke-ok", script)
        compile(script, "<all-imports-smoke>", "exec")

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
            self.assertIsNotNone(result["runtime_version"])
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

    # ---------------------------------------------------------------------------
    # RC3 regression tests: metadata completeness
    # ---------------------------------------------------------------------------

    def test_publishable_distributions_have_spdx_license_metadata(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            project = self._load_project_metadata(entry["pyproject_path"])
            license_value = project.get("license")
            self.assertIsNotNone(
                license_value,
                msg=f"{entry['name']}: license field is missing",
            )
            self.assertEqual(
                license_value,
                "Apache-2.0",
                msg=f"{entry['name']}: expected SPDX license 'Apache-2.0', got {license_value!r}",
            )

    def test_publishable_distributions_have_license_files_configured(self) -> None:
        root = Path(__file__).resolve().parents[1]
        canonical_license = (root / "LICENSE").read_bytes()
        for entry in publishable_distributions(root):
            document = tomllib.loads(entry["pyproject_path"].read_text(encoding="utf-8"))
            project = document.get("project", {})
            assert isinstance(project, dict)
            license_files = project.get("license-files")
            self.assertIsNotNone(
                license_files,
                msg=f"{entry['name']}: license-files is missing",
            )
            self.assertIn(
                "LICENSE",
                license_files,
                msg=f"{entry['name']}: LICENSE not in license-files",
            )
            package_dir = entry["pyproject_path"].parent
            license_path = package_dir / "LICENSE"
            self.assertTrue(
                license_path.exists(),
                msg=f"{entry['name']}: LICENSE file absent at {license_path}",
            )
            self.assertEqual(
                license_path.read_bytes(),
                canonical_license,
                msg=f"{entry['name']}: LICENSE differs from the canonical root license",
            )

    def test_publishable_distributions_have_readme_configured(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            document = tomllib.loads(entry["pyproject_path"].read_text(encoding="utf-8"))
            project = document.get("project", {})
            assert isinstance(project, dict)
            readme = project.get("readme")
            self.assertIsNotNone(
                readme,
                msg=f"{entry['name']}: readme field is missing",
            )
            if isinstance(readme, str):
                readme_path = entry["pyproject_path"].parent / readme
                self.assertTrue(
                    readme_path.exists(),
                    msg=f"{entry['name']}: readme file {readme!r} does not exist at {readme_path}",
                )

    def test_public_package_readmes_are_pypi_safe(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative_path in ("packages/sdk/README.md", "apps/cli/README.md"):
            readme = (root / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("```mermaid", readme.lower())
            relative_links = re.findall(r"\[[^]]+\]\((?!https://)[^)]+\)", readme)
            self.assertEqual(
                relative_links,
                [],
                msg=f"{relative_path}: relative links are not PyPI-safe",
            )
            self.assertIn("0.1.0rc3", readme)
            self.assertIn("not yet published", readme.lower())

    def test_cli_entry_point_is_exact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = self._load_project_metadata(root / "apps" / "cli" / "pyproject.toml")
        self.assertEqual(project.get("scripts"), {"ariadion": "ariadion_cli:main"})

    def test_publishable_distributions_have_author_vi_connelly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            project = self._load_project_metadata(entry["pyproject_path"])
            authors = project.get("authors")
            self.assertIsInstance(
                authors,
                list,
                msg=f"{entry['name']}: authors field is missing or not a list",
            )
            assert isinstance(authors, list)
            author_names = [a.get("name") for a in authors if isinstance(a, dict)]
            self.assertIn(
                "Vi Connelly",
                author_names,
                msg=f"{entry['name']}: 'Vi Connelly' not found in authors",
            )
            self.assertFalse(
                any("email" in author for author in authors if isinstance(author, dict)),
                msg=f"{entry['name']}: author metadata must not include an email",
            )

    def test_publishable_distributions_have_required_project_urls(self) -> None:
        required_keys = {"Homepage", "Repository", "Issues", "Changelog"}
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            document = tomllib.loads(entry["pyproject_path"].read_text(encoding="utf-8"))
            urls = document.get("project", {}).get("urls", {})
            assert isinstance(urls, dict)
            for key in required_keys:
                self.assertIn(
                    key,
                    urls,
                    msg=f"{entry['name']}: project.urls is missing key {key!r}",
                )
            for url in urls.values():
                self.assertIn(
                    "github.com/redxe/ariadion",
                    url,
                    msg=f"{entry['name']}: URL {url!r} does not point to github.com/redxe/ariadion",
                )

    def test_publishable_distributions_have_required_classifiers(self) -> None:
        required_fragments = [
            "Development Status :: 3 - Alpha",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Intended Audience :: Developers",
            "Intended Audience :: Science/Research",
            "Topic :: Scientific/Engineering",
            "Operating System :: OS Independent",
        ]
        root = Path(__file__).resolve().parents[1]
        for entry in publishable_distributions(root):
            project = self._load_project_metadata(entry["pyproject_path"])
            classifiers = project.get("classifiers", [])
            assert isinstance(classifiers, list)
            for fragment in required_fragments:
                self.assertTrue(
                    any(fragment in c for c in classifiers),
                    msg=f"{entry['name']}: classifier {fragment!r} is absent",
                )

    def test_runtime_version_check_script_references_both_version_sources(self) -> None:
        script = runtime_version_check_script()
        self.assertIn("importlib.metadata", script)
        self.assertIn('version("ariadion")', script)
        self.assertIn("ariadion.__version__", script)
        self.assertIn("version-check-ok:", script)

    def test_runtime_version_check_script_compiles(self) -> None:
        compile(runtime_version_check_script(), "<runtime-version-check>", "exec")

    def test_sdk_public_version_matches_distribution_metadata(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = self._load_project_metadata(root / "packages" / "sdk" / "pyproject.toml")
        module_path = root / "packages" / "sdk" / "src" / "ariadion" / "__init__.py"
        module = ast.parse(module_path.read_text(encoding="utf-8"))
        public_versions = [
            node.value.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ]
        self.assertEqual(public_versions, [project.get("version")])
        self.assertEqual(public_versions, [self._EXPECTED_RC_VERSION])

    def test_generate_sha256_manifest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a-0.1.0rc3-py3-none-any.whl"
            p2 = Path(tmp) / "b-0.1.0rc3-py3-none-any.whl"
            p1.write_bytes(b"abc")
            p2.write_bytes(b"content-b")
            manifest1 = generate_sha256_manifest([p2, p1])
            manifest2 = generate_sha256_manifest([p1, p2])
            self.assertEqual(manifest1, manifest2)
            self.assertEqual(list(manifest1), sorted([p1.name, p2.name]))
            self.assertEqual(
                manifest1[p1.name],
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
            duplicate_dir = Path(tmp) / "duplicate"
            duplicate_dir.mkdir()
            duplicate = duplicate_dir / p1.name
            duplicate.write_bytes(b"different")
            with self.assertRaisesRegex(ReleaseSmokeError, "duplicate filenames"):
                generate_sha256_manifest([p1, duplicate])

    def test_validate_artifact_set_accepts_a_complete_source_authoritative_fixture(self) -> None:
        fixture = self._artifact_fixture()
        result = validate_artifact_set(
            fixture["distributions"],
            fixture["wheels"],
            fixture["sdists"],
            expected_version="0.1.0rc3",
            canonical_license_path=fixture["root"] / "LICENSE",
        )
        self.assertEqual(result["wheels"], PUBLISHABLE_DISTRIBUTION_COUNT)
        self.assertEqual(result["sdists"], PUBLISHABLE_DISTRIBUTION_COUNT)
        self.assertEqual(list(result["manifest"]), sorted(result["manifest"]))

    def test_validate_artifact_set_rejects_wrong_wheel_count(self) -> None:
        fixture = self._artifact_fixture()
        fixture["wheels"] = fixture["wheels"][:-1]
        self._assert_fixture_rejected(fixture, "expected 15 wheels")

    def test_validate_artifact_set_rejects_wrong_sdist_count(self) -> None:
        fixture = self._artifact_fixture()
        fixture["sdists"] = fixture["sdists"][:-1]
        self._assert_fixture_rejected(fixture, "expected 15 sdists")

    def test_validate_artifact_set_rejects_workspace_artifact_case_and_separator_variant(self) -> None:
        fixture = self._artifact_fixture()
        original = fixture["wheel_paths"]["ariadion"]
        workspace_artifact = original.with_name("Ariadion.Workspace-0.1.0rc3-py3-none-any.whl")
        original.rename(workspace_artifact)
        self._replace_fixture_path(
            fixture,
            kind="wheel",
            name="ariadion",
            path=workspace_artifact,
        )
        self._assert_fixture_rejected(fixture, "ariadion-workspace artifact")

    def test_artifact_validator_rejects_missing_extra_wrong_and_conditional_internal_dependencies(self) -> None:
        cases = {
            "missing": [],
            "extra": [
                "ariadion-core==0.1.0rc3",
                "ariadion-frontend-python==0.1.0rc3",
            ],
            "wrong-pin": ["ariadion-frontend-python==0.1.0rc1"],
            "conditional": [
                "ariadion-frontend-python==0.1.0rc3 ; python_version >= '3.11'"
            ],
        }
        for label, requirements in cases.items():
            with self.subTest(label=label):
                fixture = self._artifact_fixture()
                self._write_fixture_wheel(
                    fixture,
                    "ariadion",
                    metadata_overrides={"Requires-Dist": requirements},
                )
                self._assert_fixture_rejected(
                    fixture,
                    "Requires-Dist|internal dependency",
                )

    def test_artifact_validator_rejects_duplicate_requires_dist_headers(self) -> None:
        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion",
            metadata_overrides={
                "Requires-Dist": [
                    "ariadion-frontend-python==0.1.0rc3",
                    "ariadion-frontend-python==0.1.0rc3",
                ]
            },
        )
        self._assert_fixture_rejected(fixture, "unexpected Requires-Dist")

    def test_artifact_validator_rejects_wrong_filename_and_metadata_version(self) -> None:
        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion",
            metadata_overrides={"Version": "0.1.0rc1"},
        )
        self._assert_fixture_rejected(fixture, "Version")

        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion",
            filename="ariadion-0.1.0rc1-py3-none-any.whl",
        )
        self._assert_fixture_rejected(fixture, "wheel filename")

    def test_artifact_validator_rejects_duplicate_and_unknown_normalized_metadata_names(self) -> None:
        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion-core",
            metadata_overrides={"Name": "ariadion"},
        )
        self._assert_fixture_rejected(fixture, "duplicate normalized distribution names")

        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion",
            metadata_overrides={"Name": "unrecognized-package"},
        )
        self._assert_fixture_rejected(fixture, "unknown normalized metadata name")

    def test_artifact_validator_rejects_malformed_archives(self) -> None:
        fixture = self._artifact_fixture()
        self._write_fixture_wheel(fixture, "ariadion", malformed=True)
        self._assert_fixture_rejected(fixture, "not a zip file")

        fixture = self._artifact_fixture()
        self._write_fixture_sdist(fixture, "ariadion", malformed=True)
        self._assert_fixture_rejected(fixture, "not a gzip file")

    def test_artifact_validator_rejects_core_metadata_parity_failures(self) -> None:
        cases = {
            "wrong-requires-python": ({"Requires-Python": ">=3.10"}, "Requires-Python"),
            "missing-description-content-type": ({"Description-Content-Type": None}, "Description-Content-Type"),
            "wrong-description-content-type": ({"Description-Content-Type": "text/plain"}, "Description-Content-Type"),
            "empty-description": ({"__description__": ""}, "Description payload is empty"),
            "old-metadata-version": ({"Metadata-Version": "2.3"}, "PEP 639 minimum"),
            "missing-license-expression": ({"License-Expression": None}, "License-Expression"),
            "wrong-license-expression": ({"License-Expression": "MIT"}, "License-Expression"),
            "missing-license-file-header": ({"License-File": None}, "License-File headers"),
            "wrong-license-file-header": ({"License-File": ["COPYING"]}, "License-File headers"),
        }
        for label, (overrides, pattern) in cases.items():
            with self.subTest(label=label):
                fixture = self._artifact_fixture()
                self._write_fixture_wheel(
                    fixture,
                    "ariadion",
                    metadata_overrides=overrides,
                )
                self._assert_fixture_rejected(fixture, pattern)

    def test_artifact_validator_rejects_sdist_core_metadata_parity_failures(self) -> None:
        cases = {
            "version": ({"Version": "0.1.0rc1"}, "Version"),
            "requires-python": ({"Requires-Python": ">=3.10"}, "Requires-Python"),
            "description-content-type": ({"Description-Content-Type": "text/plain"}, "Description-Content-Type"),
            "license-expression": ({"License-Expression": "MIT"}, "License-Expression"),
        }
        for label, (overrides, pattern) in cases.items():
            with self.subTest(sdist_metadata=label):
                fixture = self._artifact_fixture()
                self._write_fixture_sdist(
                    fixture,
                    "ariadion",
                    metadata_overrides=overrides,
                )
                self._assert_fixture_rejected(fixture, pattern)

    def test_artifact_validator_rejects_license_member_and_payload_failures(self) -> None:
        cases: list[tuple[str, dict[str, Any], str]] = [
            (
                "missing-pep639-license",
                {"include_license": False},
                "sole PEP 639 license member",
            ),
            (
                "legacy-wheel-license",
                {"include_license": False, "legacy_license": True},
                "legacy license member",
            ),
            (
                "unexpected-pep639-license",
                {
                    "extra_license_members": [
                        "unexpected-0.1.0rc3.dist-info/licenses/LICENSE"
                    ]
                },
                "sole PEP 639 license member",
            ),
            (
                "wheel-license-byte-mismatch",
                {"license_payload": b"wrong license payload\n"},
                "LICENSE payload differs",
            ),
        ]
        for label, keyword_arguments, pattern in cases:
            with self.subTest(label=label):
                fixture = self._artifact_fixture()
                self._write_fixture_wheel(fixture, "ariadion", **keyword_arguments)
                self._assert_fixture_rejected(fixture, pattern)

        fixture = self._artifact_fixture()
        self._write_fixture_sdist(
            fixture,
            "ariadion",
            license_payload=b"wrong license payload\n",
        )
        self._assert_fixture_rejected(fixture, "LICENSE payload differs")

    def test_artifact_validator_rejects_wheel_and_sdist_import_structural_failures(self) -> None:
        cases: list[tuple[str, str, dict[str, Any]]] = [
            ("directory-only-wheel-init", "wheel", {"import_variant": "directory"}),
            ("missing-wheel-init", "wheel", {"include_import": False}),
            ("non-file-sdist-init", "sdist", {"import_variant": "symlink"}),
        ]
        for label, kind, keyword_arguments in cases:
            with self.subTest(label=label):
                fixture = self._artifact_fixture()
                if kind == "wheel":
                    self._write_fixture_wheel(fixture, "ariadion", **keyword_arguments)
                else:
                    self._write_fixture_sdist(fixture, "ariadion", **keyword_arguments)
                self._assert_fixture_rejected(fixture, "__init__\\.py.*regular file|archive member")

    def test_artifact_validator_rejects_malformed_duplicate_missing_wrong_section_and_wrong_target_cli_entry_points(self) -> None:
        cases = {
            "missing": {"include_entry_points": False},
            "malformed": {"entry_points": "[console_scripts\nariadion = ariadion_cli:main\n"},
            "duplicate-entry-file": {"duplicate_entry_points": True},
            "wrong-section": {
                "entry_points": "[gui_scripts]\nariadion = ariadion_cli:main\n"
            },
            "wrong-target": {
                "entry_points": "[console_scripts]\nariadion = wrong_target:main\n"
            },
            "wrong-command-name": {
                "entry_points": "[console_scripts]\nother = ariadion_cli:main\n"
            },
        }
        for label, keyword_arguments in cases.items():
            with self.subTest(label=label):
                fixture = self._artifact_fixture()
                self._write_fixture_wheel(
                    fixture,
                    "ariadion-cli",
                    **keyword_arguments,
                )
                self._assert_fixture_rejected(fixture, "entry_points|console_scripts|CLI entry point")

    def test_artifact_validator_rejects_non_cli_distribution_exposing_the_cli_target(self) -> None:
        fixture = self._artifact_fixture()
        self._write_fixture_wheel(
            fixture,
            "ariadion",
            entry_points="[console_scripts]\nariadion = ariadion_cli:main\n",
        )
        self._assert_fixture_rejected(fixture, "non-CLI distribution")

    def test_relative_artifact_invocation_resolves_outputs_outside_the_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ariadion-outside-cwd-") as temporary:
            outside = Path(temporary)
            observed: dict[str, Any] = {}

            def fake_validate_artifacts(**kwargs: Any) -> dict[str, Any]:
                observed.update(kwargs)
                return {"wheels": 15, "sdists": 15, "version": "0.1.0rc3", "manifest": {}}

            with contextlib.chdir(outside):
                with patch("tools.release_smoke.publishable_distributions", return_value=[]), patch(
                    "tools.release_smoke._run_validate_artifacts",
                    side_effect=fake_validate_artifacts,
                ), patch.object(
                    sys,
                    "argv",
                    [
                        "release_smoke.py",
                        "--wheelhouse",
                        "relative-wheelhouse",
                        "--validate-artifacts",
                        "relative-sdists",
                    ],
                ), patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(main(), 0)
        self.assertEqual(
            observed["wheelhouse"],
            outside / "relative-wheelhouse",
        )
        self.assertEqual(observed["sdist_dir"], outside / "relative-sdists")
        self.assertEqual(observed["root"], ROOT.resolve())

    def test_cli_rejects_incompatible_artifact_and_numpy_options(self) -> None:
        parser = build_argument_parser()
        self.assertIsNone(parser.parse_args(["--wheelhouse", "wheels"]).numpy_version)
        invalid_argument_sets = [
            ["--validate-artifacts", "sdists", "--list"],
            ["--validate-artifacts", "sdists", "--with-numpy"],
            ["--validate-artifacts", "sdists", "--numpy-version", "1.26.0"],
            ["--validate-artifacts", "sdists", "--venv-dir", "venv"],
            ["--numpy-version", "1.26.0"],
        ]
        for extra_arguments in invalid_argument_sets:
            with self.subTest(arguments=extra_arguments):
                args = parser.parse_args(["--wheelhouse", "wheels", *extra_arguments])
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit):
                        _validate_argument_combinations(parser, args)

    def test_twine_check_command_uses_strict_flag(self) -> None:
        artifacts = [Path("/tmp/a.whl"), Path("/tmp/b.tar.gz")]
        command = twine_check_command(artifacts)
        self.assertIn("--strict", command)
        self.assertIn("twine", command)
        self.assertIn("check", command)
        for artifact in artifacts:
            self.assertIn(str(artifact), command)

    def test_build_sdist_command_uses_build_module(self) -> None:
        member_dir = Path("/tmp/pkg")
        sdist_dir = Path("/tmp/sdists")
        command = build_sdist_command(member_dir, sdist_dir)
        self.assertEqual(command[0], sys.executable)
        self.assertIn("build", command)
        self.assertIn("--sdist", command)
        self.assertNotIn("--no-isolation", command)
        self.assertIn(str(sdist_dir), command)
        self.assertIn(str(member_dir), command)

    def test_root_workspace_is_excluded_from_publishable_distributions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        distributions = publishable_distributions(root)
        names = {entry["name"] for entry in distributions}
        self.assertNotIn("ariadion-workspace", names)

    def test_index_release_verifier_requires_exact_approved_remote_artifacts(self) -> None:
        manifest, metadata = self._index_release_fixture()
        urls = verify_release_files(manifest, metadata)
        self.assertEqual(list(urls), sorted(manifest))
        self.assertEqual(len(urls), ARTIFACT_COUNT)

        for label in ("missing", "extra", "mismatched"):
            with self.subTest(remote_artifact_mutation=label):
                manifest, metadata = self._index_release_fixture()
                if label == "missing":
                    metadata["ariadion"]["urls"].pop()
                elif label == "extra":
                    metadata["ariadion"]["urls"].append(
                        {
                            "filename": "unexpected-0.1.0rc3.tar.gz",
                            "url": (
                                "https://files.pythonhosted.org/packages/"
                                "unexpected-0.1.0rc3.tar.gz"
                            ),
                            "digests": {"sha256": "f" * 64},
                        }
                    )
                else:
                    metadata["ariadion"]["urls"][0]["digests"]["sha256"] = "e" * 64
                with self.assertRaises(IndexReleaseError):
                    verify_release_files(manifest, metadata)

    def test_index_release_verifier_rejects_cross_project_redistribution(self) -> None:
        manifest, metadata = self._index_release_fixture()
        moved = metadata["ariadion-core"]["urls"].pop()
        metadata["ariadion"]["urls"].append(moved)
        with self.assertRaisesRegex(IndexReleaseError, "artifact is assigned"):
            verify_release_files(manifest, metadata)

    def test_index_release_verifier_rejects_fully_and_partially_yanked_releases(self) -> None:
        for label, target_count in (("partial", 1), ("full", ARTIFACT_COUNT)):
            with self.subTest(yank_state=label):
                manifest, metadata = self._index_release_fixture()
                files = [
                    item
                    for distribution in PUBLISHABLE_DISTRIBUTIONS
                    for item in metadata[distribution]["urls"]
                ]
                for item in files[:target_count]:
                    item["yanked"] = True
                    item["yanked_reason"] = "superseded release"
                with self.assertRaisesRegex(
                    IndexReleaseError,
                    "yanked=True.*yanked_reason='superseded release'",
                ):
                    verify_release_files(manifest, metadata)

    def test_index_release_verifier_requires_explicit_unyanked_metadata(self) -> None:
        manifest, metadata = self._index_release_fixture()
        artifact = metadata["ariadion"]["urls"][0]
        artifact.pop("yanked")
        with self.assertRaisesRegex(IndexReleaseError, "yanked=None"):
            verify_release_files(manifest, metadata)

        manifest, metadata = self._index_release_fixture()
        artifact = metadata["ariadion"]["urls"][0]
        artifact["yanked_reason"] = "inconsistent reason"
        with self.assertRaisesRegex(IndexReleaseError, "inconsistent reason"):
            verify_release_files(manifest, metadata)

    def test_clean_publication_preflight_requires_every_project_version_absent(self) -> None:
        _, metadata = self._index_release_fixture()

        def missing(distribution: str, *, status: int = 404) -> IndexReleaseError:
            error = HTTPError(
                f"https://pypi.org/pypi/{distribution}/{RELEASE_VERSION}/json",
                status,
                "missing",
                None,
                None,
            )
            failure = IndexReleaseError(f"{distribution}: unavailable")
            failure.__cause__ = error
            return failure

        def all_missing(_index: IndexName, distribution: str) -> dict[str, Any]:
            raise missing(distribution)

        require_release_absent(all_missing, index=IndexName.PYPI)

        def one_existing(_index: IndexName, distribution: str) -> dict[str, Any]:
            if distribution == "ariadion":
                return metadata[distribution]
            raise missing(distribution)

        with self.assertRaisesRegex(
            IndexReleaseError,
            f"{re.escape(RELEASE_VERSION)} already exists.*ariadion",
        ):
            require_release_absent(one_existing, index=IndexName.PYPI)

        def registry_failure(_index: IndexName, distribution: str) -> dict[str, Any]:
            raise missing(distribution, status=503)

        with self.assertRaisesRegex(IndexReleaseError, "unavailable"):
            require_release_absent(registry_failure, index=IndexName.PYPI)

    def test_index_release_manifest_requires_exact_safe_lowercase_rc3_entries(self) -> None:
        manifest, _ = self._index_release_fixture()
        temporary = Path(tempfile.mkdtemp(prefix="ariadion-manifest-fixture-"))
        self.addCleanup(shutil.rmtree, temporary, ignore_errors=True)
        manifest_path = temporary / "manifest.json"

        def write_manifest(entries: dict[str, str]) -> None:
            manifest_path.write_text(json.dumps(entries), encoding="utf-8")

        write_manifest(manifest)
        self.assertEqual(load_manifest(manifest_path), manifest)

        mutations = {
            "uppercase digest": lambda entries: entries.__setitem__(
                next(iter(entries)), "A" * 64
            ),
            "malformed digest": lambda entries: entries.__setitem__(
                next(iter(entries)), "g" * 64
            ),
            "wrong version": lambda entries: entries.__setitem__(
                "ariadion-0.1.0rc1-py3-none-any.whl", entries.pop(next(iter(entries)))
            ),
            "unsafe filename": lambda entries: entries.__setitem__(
                "../ariadion-0.1.0rc3.tar.gz", entries.pop(next(iter(entries)))
            ),
            "unknown type": lambda entries: entries.__setitem__(
                "ariadion-0.1.0rc3.zip", entries.pop(next(iter(entries)))
            ),
            "duplicate wheel kind": lambda entries: entries.__setitem__(
                "ariadion-0.1.0rc3-py3-none-any.whl",
                entries.pop("ariadion-0.1.0rc3.tar.gz"),
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(manifest_mutation=label):
                candidate = dict(manifest)
                mutate(candidate)
                write_manifest(candidate)
                with self.assertRaises(IndexReleaseError):
                    load_manifest(manifest_path)

        encoded = json.dumps(manifest)
        duplicate_key = next(iter(manifest))
        manifest_path.write_text(
            encoded[:-1] + f', {json.dumps(duplicate_key)}: "f"}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(IndexReleaseError, "duplicate JSON object key"):
            load_manifest(manifest_path)

    def test_index_release_verifier_rejects_unapproved_artifact_urls(self) -> None:
        manifest, metadata = self._index_release_fixture()
        hazards = (
            "http://files.pythonhosted.org/packages/a.whl",
            "https://files.pythonhosted.org:443/packages/a.whl",
            "https://user@files.pythonhosted.org/packages/a.whl",
            "https://files.pythonhosted.org/packages/a.whl?token=1",
            "https://files.pythonhosted.org/packages/a.whl#fragment",
            "https://files.pythonhosted.org/not-packages/a.whl",
            "https://evil.example/packages/a.whl",
        )
        for url in hazards:
            with self.subTest(url=url):
                candidate = json.loads(json.dumps(metadata))
                candidate["ariadion"]["urls"][0]["url"] = url
                with self.assertRaises(IndexReleaseError):
                    verify_release_files(manifest, candidate)

    def test_index_release_metadata_fetch_enforces_url_and_response_bounds(self) -> None:
        class Response:
            def __init__(self, content: bytes, length: str | None = None) -> None:
                self.content = content
                self.headers = {"Content-Length": length or str(len(content))}

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def getcode(self) -> int:
                return 200

            def read(self, size: int = -1) -> bytes:
                if size < 0:
                    return self.content
                value, self.content = self.content[:size], self.content[size:]
                return value

            def geturl(self) -> str:
                return "https://pypi.org/pypi/ariadion/0.1.0rc3/json"

            def close(self) -> None:
                return None

        valid = json.dumps({"urls": []}).encode("utf-8")
        with patch("tools.verify_index_release._open_response", return_value=Response(valid)):
            self.assertEqual(
                fetch_release_metadata(IndexName.PYPI, "ariadion"), {"urls": []}
            )
        for label, response in (
            ("declared metadata size", Response(valid, str(MAX_METADATA_BYTES + 1))),
            ("malformed metadata length", Response(valid, "nan")),
            ("actual metadata size", Response(b"x" * (MAX_METADATA_BYTES + 1))),
        ):
            with self.subTest(response_mutation=label):
                with patch("tools.verify_index_release._open_response", return_value=response):
                    with self.assertRaises(IndexReleaseError):
                        fetch_release_metadata(IndexName.PYPI, "ariadion")

    def test_index_release_redirect_handler_rejects_unapproved_and_exhausted_hops(self) -> None:
        unsafe_handler = _ApprovedRedirectHandler(
            _UrlPolicy("files.pythonhosted.org", "/packages/")
        )
        request = Request("https://files.pythonhosted.org/packages/original.whl")
        with self.assertRaises(IndexReleaseError):
            unsafe_handler.redirect_request(
                request,
                None,
                302,
                "",
                {},
                "https://evil.example/file",
            )
        handler = _ApprovedRedirectHandler(
            _UrlPolicy("files.pythonhosted.org", "/packages/")
        )
        for _ in range(MAX_REDIRECTS):
            handler.redirect_request(
                request,
                None,
                302,
                "",
                {},
                "https://files.pythonhosted.org/packages/next.whl",
            )
        with self.assertRaisesRegex(IndexReleaseError, "exceeded 3 redirects"):
            handler.redirect_request(
                request,
                None,
                302,
                "",
                {},
                "https://files.pythonhosted.org/packages/next.whl",
            )

    def test_index_release_downloads_atomically_and_cleans_failed_files(self) -> None:
        class Response:
            def __init__(
                self,
                content: bytes,
                *,
                failure: bool = False,
                length: str | None = None,
            ) -> None:
                self.content = content
                self.failure = failure
                self.headers = {"Content-Length": length or str(len(content))}

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def getcode(self) -> int:
                return 200

            def read(self, size: int = -1) -> bytes:
                if self.failure:
                    raise OSError("network interrupted")
                if size < 0:
                    return self.content
                value, self.content = self.content[:size], self.content[size:]
                return value

            def geturl(self) -> str:
                return "https://files.pythonhosted.org/packages/ariadion-0.1.0rc3.tar.gz"

            def close(self) -> None:
                return None

        expected, _ = self._index_release_fixture()
        payloads = {name: name.encode("utf-8") for name in expected}
        manifest = {
            name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()
        }
        urls = {
            name: f"https://files.pythonhosted.org/packages/{name}" for name in manifest
        }
        root = Path(tempfile.mkdtemp(prefix="ariadion-download-fixture-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        destination = root / "verified"

        def open_response(url: str, _timeout: int) -> Response:
            return Response(payloads[url.rsplit("/", 1)[-1]])

        with patch(
            "tools.verify_index_release._open_response",
            side_effect=lambda url, **_: open_response(url, 0),
        ):
            download_verified_artifacts(urls, manifest, destination)
        filename = "ariadion-0.1.0rc3.tar.gz"
        self.assertEqual((destination / filename).read_bytes(), payloads[filename])
        self.assertFalse(list(destination.glob(".*.part")))

        first_filename = sorted(manifest)[0]
        for label, response, expected_message in (
            ("digest mismatch", Response(payloads[first_filename]), "digest differs"),
            (
                "partial response",
                Response(payloads[first_filename], failure=True),
                "download failed",
            ),
            (
                "oversized artifact",
                Response(payloads[first_filename], length=str(MAX_ARTIFACT_BYTES + 1)),
                "exceeds",
            ),
        ):
            with self.subTest(download_mutation=label):
                shutil.rmtree(destination, ignore_errors=True)
                candidate_manifest = dict(manifest)
                if label == "digest mismatch":
                    candidate_manifest[first_filename] = "0" * 64
                with patch("tools.verify_index_release._open_response", return_value=response):
                    with self.assertRaisesRegex(IndexReleaseError, expected_message):
                        download_verified_artifacts(urls, candidate_manifest, destination)
                self.assertFalse(destination.exists())

        real_link = os.link

        def link_then_fail(source: str | bytes, target: str | bytes) -> None:
            real_link(source, target)
            raise OSError("finalization interrupted")

        with patch(
            "tools.verify_index_release._open_response",
            side_effect=lambda url, **_: open_response(url, 0),
        ):
            with patch("tools.verify_index_release.os.link", side_effect=link_then_fail):
                with self.assertRaisesRegex(IndexReleaseError, "download failed"):
                    download_verified_artifacts(urls, manifest, destination)
        self.assertFalse(destination.exists())

        destination.mkdir()
        (destination / first_filename).write_bytes(b"already present")
        with self.assertRaisesRegex(IndexReleaseError, "new and empty"):
            download_verified_artifacts(urls, manifest, destination)

    def test_index_release_verifier_retries_metadata_propagation_with_a_bound(self) -> None:
        manifest, metadata = self._index_release_fixture()
        calls = 0
        sleeps: list[float] = []

        def fetch(index: IndexName, distribution: str) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls <= len(PUBLISHABLE_DISTRIBUTIONS):
                partial = {
                    name: {"urls": list(value["urls"])} for name, value in metadata.items()
                }
                partial["ariadion"]["urls"].pop()
                return partial[distribution]
            self.assertEqual(index, IndexName.TESTPYPI)
            return metadata[distribution]

        observed = wait_for_verified_release(
            fetch,
            manifest,
            index=IndexName.TESTPYPI,
            attempts=2,
            delay_seconds=0.0,
            sleep=sleeps.append,
        )
        self.assertEqual(list(observed), sorted(manifest))
        self.assertEqual(sleeps, [0.0])
        self.assertEqual(calls, len(PUBLISHABLE_DISTRIBUTIONS) * 2)

        with self.assertRaisesRegex(IndexReleaseError, "did not propagate"):
            wait_for_verified_release(
                lambda _index, distribution: {"urls": metadata[distribution]["urls"][:-1]},
                manifest,
                index=IndexName.TESTPYPI,
                attempts=1,
                delay_seconds=0.0,
                sleep=sleeps.append,
            )

    def _workflow_job_blocks(self, workflow: str) -> dict[str, str]:
        jobs = workflow.split("\njobs:\n", 1)[1]
        matches = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]+):\n", jobs))
        return {
            match.group(1): jobs[
                match.end() : matches[index + 1].start() if index + 1 < len(matches) else None
            ]
            for index, match in enumerate(matches)
        }

    def _publish_workflow_contract_errors(self, workflow: str) -> list[str]:
        errors: list[str] = []
        jobs = self._workflow_job_blocks(workflow)
        required_jobs = {
            "preflight-indexes",
            "build",
            "publish-testpypi",
            "verify-testpypi",
            "preflight-pypi",
            "publish-pypi",
            "verify-pypi",
        }
        if set(jobs) != required_jobs:
            errors.append("trusted publishing jobs differ from the approved seven-job topology")
        events = workflow.split("\npermissions:\n", 1)[0]
        unsupported_events = ("workflow_dispatch", "pull_request", "release:", "schedule:")
        if 'tags:\n      - "v*"' not in events or any(
            event in events for event in unsupported_events
        ):
            errors.append("workflow trigger is not tag-only")
        if not re.search(r"(?m)^permissions:\n  contents: read$", workflow):
            errors.append("root permissions are not least privilege")
        for variable, value in (
            ("RELEASE_VERSION", RELEASE_VERSION),
            ("RELEASE_TAG", RELEASE_TAG),
            ("RELEASE_BUNDLE_NAME", RELEASE_BUNDLE_NAME),
        ):
            if f"  {variable}: {value}" not in workflow:
                errors.append(f"workflow {variable} differs from the release contract")
        if "concurrency:" not in workflow or "github.ref" not in workflow:
            errors.append("same-tag concurrency is absent")
        if "fetch-depth: 0" not in workflow:
            errors.append("checkout is not full history")
        if "needs: preflight-indexes" not in jobs.get("build", ""):
            errors.append("build does not require the clean two-index preflight")
        if "needs: preflight-pypi" not in jobs.get("publish-pypi", ""):
            errors.append("production publication does not require its final clean preflight")
        if workflow.count("--require-absent") != 3:
            errors.append("clean publication preflights are incomplete")
        for action in re.findall(r"(?m)^\s*uses:\s*(\S+)", workflow):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", action):
                errors.append(f"action is not a full immutable SHA pin: {action}")
        gate = jobs.get("build", "")
        for required in (
            'test "$GITHUB_REF_TYPE" = "tag"',
            'test "$GITHUB_REF_NAME" = "$RELEASE_TAG"',
            'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
            'test "$(git rev-parse "${GITHUB_REF_NAME}^{commit}")" = "$GITHUB_SHA"',
            'test -z "$(git status --porcelain)"',
            "len(expected) != 15",
            "discovered != set(expected)",
            'root.get("project", {}).get("version") != version',
            'project.get("name") != name or project.get("version") != version',
            'os.environ["RELEASE_VERSION"] != RELEASE_VERSION',
            'os.environ["RELEASE_TAG"] != RELEASE_TAG',
        ):
            if required not in gate:
                errors.append(f"build provenance gate omits {required}")
        if gate.find("Require the approved") > gate.find("Install build validation tools"):
            errors.append("build tools install before provenance validation")
        if workflow.index("Require the approved") > workflow.index("- name: Set up Python"):
            errors.append("Python setup occurs before provenance validation")
        oidc_jobs = {
            name for name, block in jobs.items() if "id-token: write" in block
        }
        if oidc_jobs != {"publish-testpypi", "publish-pypi"}:
            errors.append("OIDC is not limited to the two publisher jobs")
        for name, environment in (
            ("publish-testpypi", "testpypi"),
            ("publish-pypi", "pypi"),
        ):
            if f"environment: {environment}" not in jobs.get(name, ""):
                errors.append(f"{name} is missing its approval environment")
        for name in ("publish-testpypi", "publish-pypi"):
            block = jobs.get(name, "")
            if block.count("pypa/gh-action-pypi-publish@") != 1:
                errors.append(f"{name} does not contain exactly one publisher call")
            if (
                "name: ${{ env.RELEASE_BUNDLE_NAME }}" not in block
                or "path: release" not in block
            ):
                errors.append(f"{name} does not consume the approved release bundle")
            forbidden_publish_tools = (
                "actions/checkout",
                "python -m pip",
                "python -m build",
            )
            if any(tool in block for tool in forbidden_publish_tools):
                errors.append(f"{name} accesses repository code or build dependencies")
            if "attestations: true" not in block:
                errors.append(f"{name} does not request a release attestation")
        test_publish = jobs.get("publish-testpypi", "")
        production_publish = jobs.get("publish-pypi", "")
        if (
            "https://test.pypi.org/legacy/" not in test_publish
            or "skip-existing" in test_publish
        ):
            errors.append("TestPyPI publisher contract is incomplete")
        if "repository-url:" in production_publish or "skip-existing" in production_publish:
            errors.append("PyPI publisher contract is mutable or not production-safe")
        if "--no-index" not in workflow or "--extra-index-url" in workflow:
            errors.append("isolated install can access an extra index")
        expected_pins = {
            f'"{distribution}==${{RELEASE_VERSION}}"'
            for _, distribution in PUBLISHABLE_PROJECTS
        }
        if not expected_pins.issubset(set(workflow.split())):
            errors.append("installed TestPyPI smoke does not pin all RC3 distributions")
        if "--version" in workflow:
            errors.append("verifier accepts an arbitrary workflow version")
        forbidden = ("gh release", "git tag", "password", "api-token", "secrets.")
        if any(token in workflow.lower() for token in forbidden):
            errors.append("workflow contains a forbidden release credential or side effect")
        return errors

    def test_publish_workflow_enforces_trusted_publishing_boundaries_offline(self) -> None:
        workflow_path = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"
        )
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertEqual(self._publish_workflow_contract_errors(workflow), [])
        production_block_start = workflow.index("  publish-pypi:\n")
        production_block_end = workflow.index("  verify-pypi:\n")
        production_block = workflow[production_block_start:production_block_end]
        altered_production_bundle = production_block.replace(
            "path: release",
            "path: altered",
            1,
        )
        artifact_divergence = (
            workflow[:production_block_start]
            + altered_production_bundle
            + workflow[production_block_end:]
        )
        mutations = {
            "branch trigger": workflow.replace('tags:\n      - "v*"', "branches: [main]"),
            "manual trigger": workflow.replace(
                "on:\n", "on:\n  workflow_dispatch:\n", 1
            ),
            "pull request trigger": workflow.replace(
                "on:\n", "on:\n  pull_request:\n", 1
            ),
            "release trigger": workflow.replace("on:\n", "on:\n  release:\n", 1),
            "scheduled trigger": workflow.replace("on:\n", "on:\n  schedule:\n", 1),
            "missing tag gate": workflow.replace('$RELEASE_TAG', "v0.1.0rc1", 1),
            "release contract divergence": workflow.replace(
                f"RELEASE_VERSION: {RELEASE_VERSION}",
                "RELEASE_VERSION: 0.1.0rc4",
                1,
            ),
            "missing head gate": workflow.replace(
                'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"\n', ""
            ),
            "missing initial preflight dependency": workflow.replace(
                "    needs: preflight-indexes\n", "", 1
            ),
            "missing production preflight dependency": workflow.replace(
                "    needs: preflight-pypi\n", "", 1
            ),
            "missing source-count gate": workflow.replace("len(expected) != 15", "False"),
            "missing source-version gate": workflow.replace(
                'project.get("name") != name or project.get("version") != version', "False"
            ),
            "root OIDC": workflow.replace(
                "permissions:\n  contents: read", "permissions:\n  id-token: write"
            ),
            "build OIDC": workflow.replace(
                "  build:\n",
                "  build:\n    permissions:\n      id-token: write\n",
            ),
            "verify OIDC": workflow.replace(
                "  verify-pypi:\n", "  verify-pypi:\n    permissions:\n      id-token: write\n"
            ),
            "wrong production environment": workflow.replace(
                "environment: pypi",
                "environment: testpypi",
            ),
            "credential": workflow + "\n# password\n",
            "mutable action": re.sub(r"@[0-9a-f]{40}", "@v4", workflow, count=1),
            "malformed action": re.sub(r"@[0-9a-f]{40}", "@not-a-sha", workflow, count=1),
            "publisher checkout": workflow.replace(
                "  publish-pypi:\n", "  publish-pypi:\n      - uses: actions/checkout@v4\n"
            ),
            "publisher build": workflow.replace(
                "  publish-pypi:\n", "  publish-pypi:\n      - run: python -m build\n"
            ),
            "publisher dependency install": workflow.replace(
                "  publish-pypi:\n",
                "  publish-pypi:\n      - run: python -m pip install build\n",
            ),
            "second publisher": workflow.replace(
                "  publish-pypi:\n",
                "  publish-pypi:\n"
                "      - uses: pypa/gh-action-pypi-publish@v1\n",
            ),
            "TestPyPI index divergence": workflow.replace(
                "https://test.pypi.org/legacy/", "https://upload.pypi.org/legacy/"
            ),
            "TestPyPI skip existing": workflow.replace(
                "          repository-url: https://test.pypi.org/legacy/\n",
                "          repository-url: https://test.pypi.org/legacy/\n"
                "          skip-existing: true\n",
            ),
            "artifact bundle divergence": artifact_divergence,
            "production skip existing": workflow.replace(
                "  publish-pypi:\n", "  publish-pypi:\n    skip-existing: true\n"
            ),
            "extra index": workflow.replace(
                "--no-index",
                "--no-index --extra-index-url https://x.invalid",
            ),
        }
        for label, candidate in mutations.items():
            with self.subTest(workflow_mutation=label):
                self.assertTrue(self._publish_workflow_contract_errors(candidate))


if __name__ == "__main__":
    unittest.main()
