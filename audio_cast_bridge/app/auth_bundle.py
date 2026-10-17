"""Hash-pinned Cast authentication-bundle acquisition.

Downloads the separately released experimental cert window bundle once into
/data/private/certs.json. Bundle bytes are never logged. Existing local state
is never silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

LOGGER = logging.getLogger("acb.auth")

DATA_DIR = Path(os.environ.get("ACB_DATA_DIR", "/data"))
PRIVATE_DIR = DATA_DIR / "private"
CERTS_PATH = PRIVATE_DIR / "certs.json"
MAX_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024

# Trusted digest of config/bundle-release.json (content-addressed pin).
DEFAULT_MANIFEST_SHA256 = (
    "2a8edc6897c5763c97c25762cf248f3926b6725550d9a736b358ffcf87a62d51"
)
DEFAULT_MANIFEST_PATH = Path(
    os.environ.get(
        "ACB_BUNDLE_MANIFEST",
        str(Path(__file__).resolve().parent / "bundle-release.json"),
    )
)


def certs_present() -> bool:
    return CERTS_PATH.is_file() and CERTS_PATH.stat().st_size > 0


def certs_path() -> Path:
    return CERTS_PATH


class _HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _require_https(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("artifact transport must use HTTPS without credentials")


def _read_manifest(path: Path, expected_sha256: str) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("manifest trusted digest mismatch")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid manifest JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("invalid manifest schema")
    if manifest.get("withdrawn"):
        raise ValueError("artifact version has been withdrawn")
    size = manifest.get("size")
    sha = manifest.get("sha256")
    url = manifest.get("url")
    if not isinstance(size, int) or not 0 < size <= MAX_BYTES:
        raise ValueError("invalid manifest size")
    if not isinstance(sha, str) or len(sha) != 64:
        raise ValueError("invalid manifest sha256")
    if not isinstance(url, str):
        raise ValueError("invalid manifest url")
    _require_https(url)
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment:
        raise ValueError("manifest requires a stable unsigned artifact URL")
    return manifest


def _import_local(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("certificate bundle must be a regular file")
    size = source.stat().st_size
    if not 0 < size <= MAX_BYTES:
        raise ValueError("certificate bundle size is invalid")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".certs-import-", dir=str(destination.parent))
    temporary = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            os.fchmod(out.fileno(), 0o600)
            shutil.copyfileobj(inp, out, length=64 * 1024)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _download(manifest: dict, destination: Path) -> str:
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fetch = build_opener(_HTTPSRedirects()).open
    fd, tmp_name = tempfile.mkstemp(prefix=".artifact-", dir=str(parent))
    temporary = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        count = 0
        deadline = time.monotonic() + 90
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            try:
                with fetch(manifest["url"], timeout=45) as response:
                    _require_https(response.geturl())
                    while True:
                        if time.monotonic() > deadline:
                            raise ValueError("artifact download exceeded time budget")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > manifest["size"]:
                            raise ValueError("artifact exceeds pinned size")
                        digest.update(chunk)
                        output.write(chunk)
            except (OSError, ValueError, HTTPException):
                raise ValueError(
                    "artifact unavailable or download rejected; local copy unchanged"
                ) from None
            output.flush()
            os.fsync(output.fileno())
        if count != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
            raise ValueError("artifact size or digest mismatch; local copy unchanged")
        try:
            value = json.loads(temporary.read_bytes())
            if not isinstance(value, (dict, list)) or not value:
                raise ValueError("empty bundle")
        except (ValueError, UnicodeError, RecursionError, json.JSONDecodeError):
            raise ValueError("artifact is not a nonempty JSON bundle") from None
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return str(manifest.get("version") or "unknown")
    finally:
        temporary.unlink(missing_ok=True)


def ensure_auth_bundle() -> Path:
    """Ensure /data/private/certs.json exists; download once if missing.

    Raises ValueError on failure when no usable local bundle exists.
    """
    override = os.environ.get("ACB_CERTS_PATH", "").strip()
    if override:
        source = Path(override)
        LOGGER.info("Importing Cast auth bundle from configured ACB_CERTS_PATH")
        _import_local(source, CERTS_PATH)
        return CERTS_PATH

    if certs_present():
        LOGGER.info("Cast auth bundle present at %s", CERTS_PATH)
        return CERTS_PATH

    manifest_path = DEFAULT_MANIFEST_PATH
    pin = os.environ.get("ACB_BUNDLE_MANIFEST_SHA256", DEFAULT_MANIFEST_SHA256)
    LOGGER.info(
        "Cast auth bundle missing — acquiring pinned release (version from manifest)"
    )
    manifest = _read_manifest(manifest_path, pin)
    version = _download(manifest, CERTS_PATH)
    LOGGER.info("Cast auth bundle acquired (version=%s)", version)
    return CERTS_PATH
