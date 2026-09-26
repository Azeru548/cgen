"""Artifact storage and delivery (M10.2).

CGEN generates CAD bytes with CadQuery and then has to *deliver* them. Until
this milestone the only delivery mechanism was the in-process `FileStore`:
an ephemeral, in-memory token -> local path map served by `/download/{token}`.
That store is single-process and dies with deploys, so it cannot be a
production delivery layer.

Byteship is introduced behind a small abstraction so both delivery mechanisms
sit in the same place:

    CAD generation -> ArtifactStore -> delivery URL

Two implementations:

  * `LocalArtifactStore`  - the existing FileStore behaviour (dev / no key).
  * `ByteshipArtifactStore` - uploads the bytes to Byteship and returns the
    CDN delivery URL.

The artifact *bytes* are never regenerated: the exporters hand over the
already-written files, and Byteship receives those exact bytes. CadQuery runs
once, and no CAD data ever passes through an LLM.

Security: the Byteship project key is read from the environment, held only on
the server, and is never placed in a response, a log line, or a URL.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

import httpx

from .file_store import FileStore

logger = logging.getLogger(__name__)

#: Conservative filename allowlist. Artifact names come from the AI-proposed
#: part name, so they are sanitized before they ever reach a path.
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")

BYTESHIP_API_BASE = "https://api.byteship.dev"
BYTESHIP_KEY_ENV = "BYTESHIP_API_KEY"

#: CAD content types. `application/step` is the registered media type for
#: ISO 10303 files; `model/stl` is the registered type for STL.
CONTENT_TYPES = {
    "step": "application/step",
    "stl": "model/stl",
}

#: Remote path prefix for CGEN artifacts. The generation request id makes each
#: path unique and collision-resistant; the user prompt is never used.
PATH_PREFIX = "cgen"

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class ArtifactStorageError(RuntimeError):
    """A generated artifact could not be stored or delivered.

    Raised instead of silently reporting success with a dead download link.
    The message is safe to show a user: it never contains the API key,
    authorization headers, or signed URL tokens.
    """


class ArtifactNotFoundError(ArtifactStorageError):
    """The requested artifact is not in the store (maps to HTTP 404)."""


@dataclass(frozen=True)
class ArtifactUrls:
    """Delivery URLs for one generated STEP/STL pair."""

    step: str
    stl: str


class ArtifactStore(Protocol):
    """Delivery backend for generated CAD artifacts."""

    def store_pair(
        self,
        *,
        step_path: Path,
        stl_path: Path,
        stem: str,
        request_id: str,
    ) -> ArtifactUrls:
        """Deliver both files and return their download URLs."""
        ...


class LocalArtifactStore:
    """Existing behaviour: register the pair and serve it from this process."""

    def __init__(self, file_store: FileStore) -> None:
        self._file_store = file_store

    def store_pair(
        self,
        *,
        step_path: Path,
        stl_path: Path,
        stem: str,
        request_id: str,
    ) -> ArtifactUrls:
        token = self._file_store.put(
            step_path=str(step_path), stl_path=str(stl_path), stem=stem
        )
        return ArtifactUrls(
            step=f"/download/{token}?format=step",
            stl=f"/download/{token}?format=stl",
        )


class ByteshipClient:
    """Minimal Byteship path-keyed upload client.

    Flow, per the Byteship API reference:
      1. PUT  {base}/v1/files/{path}          -> upload session
      2. PUT  {upload.url}                    -> raw bytes (+ returned headers)
      3. POST {base}/v1/files/{path}/upload/complete
                                            -> ready file + delivery URL
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BYTESHIP_API_BASE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Byteship API key must not be empty")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout)

    @contextmanager
    def _session(self) -> Iterator[httpx.Client]:
        """Yield an HTTP client, closing only one this object created.

        An injected client is owned by the caller (and may be reused across
        the three calls of one upload), so it must never be closed here.
        """
        if self._client is not None:
            yield self._client
            return
        client = httpx.Client(timeout=self._timeout)
        try:
            yield client
        finally:
            client.close()

    def upload_file(
        self, *, path: str, data: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> str:
        """Upload one artifact and return its delivery URL."""
        encoded = _encode_path(path)
        endpoint = f"{self._base_url}/v1/files/{encoded}"
        byte_size = len(data)
        if byte_size == 0:
            raise ArtifactStorageError("generated artifact is empty")
        if byte_size > MAX_UPLOAD_BYTES:
            raise ArtifactStorageError("generated artifact exceeds the upload limit")

        session = self._create_session(
            endpoint=endpoint,
            path=path,
            byte_size=byte_size,
            content_type=content_type,
            metadata=metadata,
        )
        upload_id, upload_url, upload_headers = _session_parts(session, path)

        self._put_bytes(upload_url, data, upload_headers, content_type, path)
        return self._complete(endpoint=endpoint, path=path, upload_id=upload_id)

    def fetch_file(self, path: str) -> bytes:
        """Read a stored artifact's bytes through the Byteship API.

        Used by the delivery endpoint so the browser gets CAD bytes from a
        same-origin URL. The CDN delivery URL cannot be fetched directly by
        the browser: it serves no CORS headers, so a cross-origin `fetch()`
        for the WebGL preview is blocked. The project key never leaves the
        server.
        """
        encoded = _encode_path(path)
        endpoint = f"{self._base_url}/v1/files/{encoded}"
        with self._session() as http:
            try:
                response = http.get(endpoint, headers=self._headers())
            except httpx.HTTPError as exc:
                logger.error("artifact_fetch_failed path=%s", path)
                raise ArtifactStorageError(
                    "Artifact storage is unreachable. Try again shortly."
                ) from exc
        if response.status_code == 404:
            logger.warning("artifact_fetch_failed path=%s reason=not_found", path)
            raise ArtifactNotFoundError("Artifact not found.")
        if response.status_code >= 400:
            logger.error(
                "artifact_fetch_failed path=%s status=%d", path, response.status_code
            )
            raise _storage_error(response.status_code, "retrieve")
        logger.info("artifact_fetch_completed path=%s bytes=%d", path, len(response.content))
        return response.content

    def _create_session(
        self,
        *,
        endpoint: str,
        path: str,
        byte_size: int,
        content_type: str,
        metadata: dict[str, str] | None,
    ) -> object:
        payload: dict[str, object] = {
            "byteSize": byte_size,
            "contentType": content_type,
            "method": "auto",
            "visibility": "public",
        }
        if metadata:
            payload["metadata"] = metadata
        logger.info(
            "artifact_upload_started path=%s bytes=%d content_type=%s",
            path,
            byte_size,
            content_type,
        )
        with self._session() as http:
            try:
                response = http.put(endpoint, headers=self._headers(), json=payload)
            except httpx.HTTPError as exc:
                logger.error("artifact_upload_failed path=%s stage=session", path)
                raise ArtifactStorageError(
                    "Artifact storage is unreachable. Try again shortly."
                ) from exc
        if response.status_code >= 400:
            logger.error(
                "artifact_upload_failed path=%s stage=session status=%d",
                path,
                response.status_code,
            )
            raise _storage_error(response.status_code, "session")
        try:
            return response.json()
        except ValueError as exc:
            logger.error("artifact_upload_failed path=%s stage=session body", path)
            raise ArtifactStorageError("Artifact storage returned an invalid response.") from exc

    def _put_bytes(
        self,
        upload_url: str,
        data: bytes,
        upload_headers: dict[str, str],
        content_type: str,
        path: str,
    ) -> None:
        headers = dict(upload_headers)
        headers.setdefault("content-type", content_type)
        with self._session() as http:
            try:
                response = http.put(upload_url, headers=headers, content=data)
            except httpx.HTTPError as exc:
                logger.error("artifact_upload_failed path=%s stage=bytes", path)
                raise ArtifactStorageError(
                    "Artifact upload was interrupted. Try again."
                ) from exc
        if response.status_code >= 400:
            logger.error(
                "artifact_upload_failed path=%s stage=bytes status=%d",
                path,
                response.status_code,
            )
            raise _storage_error(response.status_code, "upload")

    def _complete(self, *, endpoint: str, path: str, upload_id: str) -> str:
        with self._session() as http:
            try:
                response = http.post(
                    f"{endpoint}/upload/complete",
                    headers=self._headers(),
                    json={"uploadId": upload_id},
                )
            except httpx.HTTPError as exc:
                logger.error("artifact_upload_failed path=%s stage=complete", path)
                raise ArtifactStorageError(
                    "Artifact upload could not be finalized. Try again."
                ) from exc
        if response.status_code >= 400:
            logger.error(
                "artifact_upload_failed path=%s stage=complete status=%d",
                path,
                response.status_code,
            )
            raise _storage_error(response.status_code, "finalize")
        try:
            body = response.json()
        except ValueError as exc:
            logger.error("artifact_upload_failed path=%s stage=complete body", path)
            raise ArtifactStorageError("Artifact storage returned an invalid response.") from exc
        url = _delivery_url(body)
        logger.info("artifact_upload_completed path=%s", path)
        return url


class ByteshipArtifactStore:
    """ArtifactStore backed by Byteship.

    Storage lives in Byteship, but the URL handed back to the client is a
    same-origin CGEN path (`/artifacts/...`). The viewer fetches STL bytes to
    build the WebGL mesh, and the Byteship CDN sends no CORS headers, so a
    direct CDN URL would fail that fetch while a plain download link still
    worked. The backend streams the bytes from Byteship instead, so preview
    and download behave identically.
    """

    def __init__(self, client: ByteshipClient) -> None:
        self._client = client

    def store_pair(
        self,
        *,
        step_path: Path,
        stl_path: Path,
        stem: str,
        request_id: str,
    ) -> ArtifactUrls:
        return ArtifactUrls(
            step=self._store(step_path, "step", stem, request_id),
            stl=self._store(stl_path, "stl", stem, request_id),
        )

    def _store(
        self, path: Path, fmt: str, stem: str, request_id: str
    ) -> str:
        remote_path = artifact_path(request_id=request_id, stem=stem, fmt=fmt)
        data = path.read_bytes()
        self._client.upload_file(
            path=remote_path,
            data=data,
            content_type=CONTENT_TYPES[fmt],
            metadata={"source": "cgen", "format": fmt},
        )
        return artifact_delivery_path(request_id=request_id, stem=stem, fmt=fmt)

    def fetch(self, request_id: str, filename: str) -> bytes:
        return self._client.fetch_file(artifact_path_from_name(request_id, filename))


def artifact_path(*, request_id: str, stem: str, fmt: str) -> str:
    """Deterministic Byteship path: `cgen/{request_id}/{stem}.{fmt}`."""
    return f"{PATH_PREFIX}/{request_id}/{safe_filename(stem, fmt)}"


def safe_filename(stem: str, fmt: str) -> str:
    """Filename used in both the remote path and the public URL."""
    return f"{_sanitize_stem(stem)}.{fmt}"


def _sanitize_stem(stem: str) -> str:
    """Reduce a proposed name to one safe path segment.

    Dots are allowed inside a name (`v2`) but never as a leading dot or as a
    `..` sequence, so a crafted filename can never walk out of its prefix.
    """
    candidate = _FILENAME_SAFE.sub("_", (stem or "").strip())
    candidate = re.sub(r"\.{2,}", ".", candidate).strip(".")
    return candidate[:80] or "part"


def artifact_delivery_path(*, request_id: str, stem: str, fmt: str) -> str:
    """Same-origin URL the browser uses for preview and download."""
    from urllib.parse import quote

    return (
        f"/artifacts/{quote(request_id, safe='')}"
        f"/{quote(safe_filename(stem, fmt), safe='')}"
    )


def artifact_path_from_name(request_id: str, filename: str) -> str:
    """Rebuild the Byteship path from the request id and public filename.

    The filename is sanitized again here, so a crafted request cannot escape
    the `cgen/{request_id}/` prefix or reach an unsupported format.
    """
    from urllib.parse import unquote

    name = unquote(filename)
    stem, dot, extension = name.rpartition(".")
    if not dot or extension not in CONTENT_TYPES:
        raise ArtifactNotFoundError("Unknown artifact format.")
    return f"{PATH_PREFIX}/{request_id}/{_sanitize_stem(stem)}.{extension}"


def byteship_api_key() -> str:
    """Server-side API key from the environment. Never logged or returned."""
    return os.environ.get(BYTESHIP_KEY_ENV, "").strip()


def default_artifact_store(file_store: FileStore) -> ArtifactStore:
    """Byteship when configured, otherwise the existing local delivery.

    Byteship is an optional deployment dependency: without a key the app keeps
    working exactly as before, using the in-process FileStore.
    """
    key = byteship_api_key()
    if not key:
        logger.info("artifact_storage_backend=local reason=no_api_key")
        return LocalArtifactStore(file_store)
    logger.info("artifact_storage_backend=byteship")
    return ByteshipArtifactStore(ByteshipClient(key))


def _encode_path(path: str) -> str:
    """URL-encode each path segment, per the Byteship path rules."""
    from urllib.parse import quote

    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def _session_parts(
    session: object, path: str
) -> tuple[str, str, dict[str, str]]:
    if not isinstance(session, dict):
        raise ArtifactStorageError("Artifact storage returned an invalid response.")
    upload = session.get("upload")
    if not isinstance(upload, dict):
        raise ArtifactStorageError("Artifact storage returned no upload session.")
    upload_id = upload.get("id")
    upload_url = upload.get("url")
    headers = upload.get("headers")
    if not isinstance(upload_id, str) or not upload_id:
        raise ArtifactStorageError("Artifact storage returned no upload id.")
    if not isinstance(upload_url, str) or not upload_url:
        raise ArtifactStorageError("Artifact storage returned no upload url.")
    clean: dict[str, str] = {}
    if isinstance(headers, dict):
        clean = {str(k): str(v) for k, v in headers.items()}
    return upload_id, upload_url, clean


def _delivery_url(body: object) -> str:
    if not isinstance(body, dict):
        raise ArtifactStorageError("Artifact storage returned an invalid response.")
    file_obj = body.get("file")
    if not isinstance(file_obj, dict):
        raise ArtifactStorageError("Artifact storage returned no file.")
    url = file_obj.get("url")
    if not isinstance(url, str) or not url:
        raise ArtifactStorageError("Artifact storage returned no delivery url.")
    return url


def _storage_error(status: int, stage: str) -> ArtifactStorageError:
    """Map a Byteship status code to a safe, user-facing message."""
    if status in (401, 403):
        return ArtifactStorageError(
            "Artifact storage rejected the request. Check the server storage credentials."
        )
    if status == 413:
        return ArtifactStorageError("The generated file is too large to store.")
    if status == 410:
        return ArtifactStorageError("The artifact upload expired. Try again.")
    if status >= 500:
        return ArtifactStorageError("Artifact storage is unavailable. Try again shortly.")
    return ArtifactStorageError(
        f"Artifact storage could not {stage} the file. Try again."
    )
