"""Verify a complete Ariadion release from the PyPI or TestPyPI JSON API.

This module intentionally uses only the Python standard library.  It compares
approved artifact filenames and SHA-256 digests to HTTPS index metadata before
optionally downloading the artifacts for an offline installation smoke test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

RELEASE_VERSION = "0.1.0rc2"
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
MAX_REDIRECTS = 3
METADATA_TIMEOUT_SECONDS = 30
ARTIFACT_TIMEOUT_SECONDS = 60
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_WHEEL_RE = re.compile(
    r"(?P<component>[A-Za-z0-9_-]+)-"
    r"(?P<version>[0-9][A-Za-z0-9.]*)-"
    r"(?P<python>[A-Za-z0-9.]+)-(?P<abi>[A-Za-z0-9.]+)-"
    r"(?P<platform>[A-Za-z0-9.]+)\.whl\Z"
)
_SDIST_RE = re.compile(
    r"(?P<component>[A-Za-z0-9_-]+)-(?P<version>[0-9][A-Za-z0-9.]*)\.tar\.gz\Z"
)
_DISTRIBUTION_COMPONENTS = {
    component: distribution
    for distribution in PUBLISHABLE_DISTRIBUTIONS
    for component in {distribution, distribution.replace("-", "_")}
}


class IndexName(StrEnum):
    """The only public indexes accepted by this fixed RC2 verifier."""

    PYPI = "pypi"
    TESTPYPI = "testpypi"


_INDEX_METADATA_HOSTS = {
    IndexName.PYPI: "pypi.org",
    IndexName.TESTPYPI: "test.pypi.org",
}


class IndexReleaseError(RuntimeError):
    """Raised when index metadata does not exactly match the approved release."""


class _Response(Protocol):
    headers: Mapping[str, str]

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> bool | None: ...

    def getcode(self) -> int | None: ...

    def geturl(self) -> str: ...

    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class _UrlPolicy:
    host: str
    path_prefix: str


@dataclass(frozen=True)
class ArtifactIdentity:
    """The approved project and artifact kind represented by one filename."""

    distribution: str
    kind: str


def _coerce_index(index: IndexName | str) -> IndexName:
    try:
        return IndexName(index)
    except ValueError as exc:
        raise IndexReleaseError(f"unsupported index: {index!r}") from exc


def _metadata_url(index: IndexName, distribution: str) -> str:
    return (
        f"https://{_INDEX_METADATA_HOSTS[index]}/pypi/"
        f"{quote(distribution, safe='')}/{RELEASE_VERSION}/json"
    )


def _has_unsafe_filename_characters(filename: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in filename)


def parse_artifact_filename(filename: str) -> ArtifactIdentity:
    """Parse a safe, approved RC2 wheel or source-distribution filename."""
    if (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or filename.startswith(("/", "\\"))
        or any(character in filename for character in ("/", "\\", ":"))
        or _has_unsafe_filename_characters(filename)
    ):
        raise IndexReleaseError(f"unsafe artifact filename: {filename!r}")
    match = _WHEEL_RE.fullmatch(filename)
    kind = "wheel"
    if match is None:
        match = _SDIST_RE.fullmatch(filename)
        kind = "sdist"
    if match is None:
        raise IndexReleaseError(f"invalid RC2 artifact filename: {filename!r}")
    distribution = _DISTRIBUTION_COMPONENTS.get(match.group("component"))
    if distribution is None:
        raise IndexReleaseError(f"unknown RC2 artifact distribution: {filename!r}")
    if match.group("version") != RELEASE_VERSION:
        raise IndexReleaseError(
            f"artifact filename version is not {RELEASE_VERSION}: {filename!r}"
        )
    return ArtifactIdentity(distribution=distribution, kind=kind)


def _validate_manifest_entries(manifest: Mapping[str, str]) -> dict[str, ArtifactIdentity]:
    if not isinstance(manifest, Mapping) or len(manifest) != ARTIFACT_COUNT:
        raise IndexReleaseError(
            f"release manifest must contain exactly {ARTIFACT_COUNT} artifact entries"
        )
    identities: dict[str, ArtifactIdentity] = {}
    observed: dict[str, set[str]] = {
        distribution: set() for distribution in PUBLISHABLE_DISTRIBUTIONS
    }
    for filename, digest in manifest.items():
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise IndexReleaseError(f"invalid lowercase SHA-256 manifest digest: {filename!r}")
        identity = parse_artifact_filename(filename)
        if identity.kind in observed[identity.distribution]:
            raise IndexReleaseError(
                f"duplicate {identity.kind} for {identity.distribution}: {filename!r}"
            )
        observed[identity.distribution].add(identity.kind)
        identities[filename] = identity
    missing = {
        distribution: sorted({"wheel", "sdist"} - kinds)
        for distribution, kinds in observed.items()
        if kinds != {"wheel", "sdist"}
    }
    if missing:
        raise IndexReleaseError(f"manifest projects need exactly one wheel and sdist: {missing!r}")
    return identities


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IndexReleaseError(f"duplicate JSON object key in manifest: {key!r}")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict[str, str]:
    """Load the fixed 30-entry, lowercase-SHA-256 RC2 manifest exactly."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise IndexReleaseError(f"cannot read release manifest {path}: {exc}") from exc
    if len(payload) > MAX_METADATA_BYTES:
        raise IndexReleaseError("release manifest exceeds the metadata size bound")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_object_keys)
    except (IndexReleaseError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, IndexReleaseError):
            raise
        raise IndexReleaseError(f"cannot parse release manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IndexReleaseError("release manifest must be a JSON object")
    manifest = dict(sorted(value.items()))
    _validate_manifest_entries(manifest)
    return manifest


def _require_approved_url(url: str, policy: _UrlPolicy) -> None:
    if not isinstance(url, str):
        raise IndexReleaseError("index response URL is not a string")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise IndexReleaseError(f"malformed index response URL: {url!r}") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != policy.host
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or not parsed.path.startswith(policy.path_prefix)
    ):
        raise IndexReleaseError(f"index response URL violates the HTTPS policy: {url!r}")


class _ApprovedRedirectHandler(HTTPRedirectHandler):
    """Reject every unsafe redirect hop and stop after a small fixed bound."""

    def __init__(self, policy: _UrlPolicy) -> None:
        super().__init__()
        self._policy = policy
        self._redirects = 0

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        self._redirects += 1
        if self._redirects > MAX_REDIRECTS:
            raise IndexReleaseError(f"index response exceeded {MAX_REDIRECTS} redirects")
        _require_approved_url(newurl, self._policy)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_response(
    url: str,
    *,
    policy: _UrlPolicy,
    timeout: int,
    open_response: Callable[[str, int], _Response] | None = None,
) -> _Response:
    _require_approved_url(url, policy)
    if open_response is None:
        response = build_opener(_ApprovedRedirectHandler(policy)).open(url, timeout=timeout)
    else:
        response = open_response(url, timeout)
    _require_approved_url(response.geturl(), policy)
    if response.getcode() != 200:
        raise IndexReleaseError(f"index response status is not 200: {response.getcode()!r}")
    return response


def _declared_content_length(response: _Response, *, maximum: int) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise IndexReleaseError(f"invalid Content-Length header: {value!r}") from exc
    if length < 0 or length > maximum:
        raise IndexReleaseError(f"Content-Length exceeds the {maximum}-byte bound: {value!r}")
    return length


def _read_bounded_response(response: _Response, *, maximum: int) -> bytes:
    declared_length = _declared_content_length(response, maximum=maximum)
    payload = bytearray()
    while True:
        chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, maximum - len(payload) + 1))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > maximum:
            raise IndexReleaseError(f"index response exceeds the {maximum}-byte bound")
    if declared_length is not None and len(payload) != declared_length:
        raise IndexReleaseError(
            f"Content-Length {declared_length} does not match received {len(payload)} bytes"
        )
    return bytes(payload)


def _index_files(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    urls = metadata.get("urls")
    if not isinstance(urls, list):
        raise IndexReleaseError("index metadata has no urls list")
    files: list[Mapping[str, Any]] = []
    for item in urls:
        if not isinstance(item, Mapping):
            raise IndexReleaseError("index metadata contains a non-object artifact")
        files.append(item)
    return files


def verify_release_files(
    manifest: Mapping[str, str],
    metadata_by_distribution: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Return URLs only if each project exposes precisely its approved RC2 pair."""
    identities = _validate_manifest_entries(manifest)
    expected_names = set(PUBLISHABLE_DISTRIBUTIONS)
    if set(metadata_by_distribution) != expected_names:
        missing = sorted(expected_names - set(metadata_by_distribution))
        unexpected = sorted(set(metadata_by_distribution) - expected_names)
        raise IndexReleaseError(
            "release metadata distribution set differs: "
            f"missing={missing!r}; unexpected={unexpected!r}"
        )

    expected_for_distribution: dict[str, set[str]] = {
        distribution: {
            filename
            for filename, identity in identities.items()
            if identity.distribution == distribution
        }
        for distribution in PUBLISHABLE_DISTRIBUTIONS
    }
    remote_urls: dict[str, str] = {}
    file_policy = _UrlPolicy(
        host="files.pythonhosted.org",
        path_prefix="/packages/",
    )
    for distribution in PUBLISHABLE_DISTRIBUTIONS:
        observed: dict[str, str] = {}
        for item in _index_files(metadata_by_distribution[distribution]):
            filename = item.get("filename")
            url = item.get("url")
            digests = item.get("digests")
            digest = digests.get("sha256") if isinstance(digests, Mapping) else None
            if (
                not isinstance(filename, str)
                or not isinstance(url, str)
                or not isinstance(digest, str)
            ):
                raise IndexReleaseError(f"{distribution}: malformed artifact metadata")
            if _SHA256_RE.fullmatch(digest) is None:
                raise IndexReleaseError(
                    f"{distribution}: invalid lowercase SHA-256 for {filename!r}"
                )
            identity = parse_artifact_filename(filename)
            if identity.distribution != distribution:
                raise IndexReleaseError(
                    f"{distribution}: artifact is assigned to {identity.distribution}: {filename!r}"
                )
            _require_approved_url(url, file_policy)
            if filename in observed:
                raise IndexReleaseError(f"{distribution}: duplicate remote artifact: {filename!r}")
            observed[filename] = digest
            remote_urls[filename] = url
        missing = sorted(expected_for_distribution[distribution] - set(observed))
        unexpected = sorted(set(observed) - expected_for_distribution[distribution])
        mismatched = sorted(
            filename
            for filename in expected_for_distribution[distribution] & set(observed)
            if manifest[filename] != observed[filename]
        )
        if missing or unexpected or mismatched:
            raise IndexReleaseError(
                f"{distribution}: remote artifacts differ from approved manifest: "
                f"missing={missing!r}; unexpected={unexpected!r}; mismatched={mismatched!r}"
            )
    if set(remote_urls) != set(manifest):
        raise IndexReleaseError("remote artifacts differ from approved manifest")
    return {filename: remote_urls[filename] for filename in sorted(manifest)}


def fetch_release_metadata(
    index: IndexName | str,
    distribution: str,
    version: str = RELEASE_VERSION,
    *,
    open_response: Callable[[str, int], _Response] | None = None,
) -> Mapping[str, Any]:
    """Fetch one fixed RC2 JSON response from the selected public index."""
    if distribution not in PUBLISHABLE_DISTRIBUTIONS:
        raise IndexReleaseError(f"unsupported RC2 distribution: {distribution!r}")
    if version != RELEASE_VERSION:
        raise IndexReleaseError(f"unsupported release version: {version!r}")
    selected_index = _coerce_index(index)
    policy = _UrlPolicy(host=_INDEX_METADATA_HOSTS[selected_index], path_prefix="/pypi/")
    try:
        with _open_response(
            _metadata_url(selected_index, distribution),
            policy=policy,
            timeout=METADATA_TIMEOUT_SECONDS,
            open_response=open_response,
        ) as response:
            payload = _read_bounded_response(response, maximum=MAX_METADATA_BYTES)
    except (HTTPError, OSError) as exc:
        raise IndexReleaseError(f"{distribution}: index metadata is unavailable: {exc}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndexReleaseError(f"{distribution}: invalid index JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise IndexReleaseError(f"{distribution}: index JSON is not an object")
    return value


def wait_for_verified_release(
    fetch: Callable[[IndexName, str], Mapping[str, Any]],
    manifest: Mapping[str, str],
    *,
    index: IndexName | str,
    attempts: int,
    delay_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Retry a fixed number of times until the complete RC2 manifest verifies."""
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    selected_index = _coerce_index(index)
    last_error: IndexReleaseError | None = None
    for attempt in range(attempts):
        try:
            metadata = {
                distribution: fetch(selected_index, distribution)
                for distribution in PUBLISHABLE_DISTRIBUTIONS
            }
            return verify_release_files(manifest, metadata)
        except IndexReleaseError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                sleep(delay_seconds)
    raise IndexReleaseError(
        f"verified release metadata did not propagate within {attempts} attempts: {last_error}"
    ) from last_error


def _prepare_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise IndexReleaseError(f"download destination must be new and empty: {destination}")
    destination.mkdir(parents=True)


def _stream_verified_download(
    *,
    url: str,
    expected_digest: str,
    destination: Path,
    filename: str,
    open_response: Callable[[str, int], _Response] | None,
) -> Path:
    file_policy = _UrlPolicy(host="files.pythonhosted.org", path_prefix="/packages/")
    _require_approved_url(url, file_policy)
    final_path = destination / filename
    temporary_path = destination / f".{filename}.part"
    if final_path.exists() or final_path.is_symlink() or temporary_path.exists():
        raise IndexReleaseError(f"refusing to overwrite download output: {filename!r}")
    digest = hashlib.sha256()
    received = 0
    try:
        with _open_response(
            url,
            policy=file_policy,
            timeout=ARTIFACT_TIMEOUT_SECONDS,
            open_response=open_response,
        ) as response:
            declared_length = _declared_content_length(response, maximum=MAX_ARTIFACT_BYTES)
            with temporary_path.open("xb") as handle:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_ARTIFACT_BYTES:
                        raise IndexReleaseError(
                            f"artifact exceeds the {MAX_ARTIFACT_BYTES}-byte bound: {filename!r}"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            if declared_length is not None and received != declared_length:
                raise IndexReleaseError(
                    f"Content-Length {declared_length} does not match received {received} bytes"
                )
            if digest.hexdigest() != expected_digest:
                raise IndexReleaseError(
                    f"downloaded artifact digest differs from approved manifest: {filename}"
                )
        os.link(temporary_path, final_path)
        temporary_path.unlink()
        return final_path
    except (HTTPError, OSError) as exc:
        raise IndexReleaseError(f"artifact download failed for {filename}: {exc}") from exc
    finally:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def download_verified_artifacts(
    urls: Mapping[str, str],
    manifest: Mapping[str, str],
    destination: Path,
    *,
    open_response: Callable[[str, int], _Response] | None = None,
) -> None:
    """Atomically write only complete, bounded, digest-verified RC2 artifacts.

    The destination must not exist. On any failure every created artifact and
    temporary file is removed, so a later verification starts from a clean path.
    """
    _validate_manifest_entries(manifest)
    if set(urls) != set(manifest):
        raise IndexReleaseError("download URLs differ from the approved manifest")
    _prepare_destination(destination)
    try:
        for filename in sorted(manifest):
            _stream_verified_download(
                url=urls[filename],
                expected_digest=manifest[filename],
                destination=destination,
                filename=filename,
                open_response=open_response,
            )
    except IndexReleaseError as exc:
        for path in destination.iterdir():
            if path.is_dir() and not path.is_symlink():
                raise IndexReleaseError(
                    f"download destination contains an unexpected directory: {path.name!r}"
                ) from exc
            path.unlink()
        destination.rmdir()
        raise


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the fixed Ariadion RC2 release")
    parser.add_argument("--index", choices=[index.value for index in IndexName], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=15.0)
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    manifest = load_manifest(args.manifest)
    selected_index = IndexName(args.index)
    urls = wait_for_verified_release(
        lambda index, distribution: fetch_release_metadata(index, distribution),
        manifest,
        index=selected_index,
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
    )
    download_verified_artifacts(urls, manifest, args.download_dir)
    print(f"verified {len(urls)} {selected_index.value} artifacts for {RELEASE_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
