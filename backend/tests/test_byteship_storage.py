"""M10.2: Byteship artifact storage and delivery.

Two layers are tested separately:

  1. `ByteshipClient` / `ByteshipArtifactStore` against an httpx mock
     transport, asserting the real endpoint, auth, path, byte size, content
     type, upload headers and completion upload id.
  2. One realistic CGEN generation (`run_rebuild`, no AI) producing *real*
     CadQuery bytes and handing them to a mocked Byteship boundary, proving
     the whole generate -> store -> delivery-URL path.

No test needs a live Byteship account, and no test ever sends CAD bytes to
Groq or performs a second CadQuery build.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.cad.schema import BoxOperation, CADSpec
from app.services import byteship as bs
from app.services.byteship import (
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactUrls,
    ByteshipArtifactStore,
    ByteshipClient,
    LocalArtifactStore,
    artifact_delivery_path,
    artifact_path,
    artifact_path_from_name,
    default_artifact_store,
)
from app.services.file_store import FileStore

KEY = "bship_test_key_value"
CDN = "https://cdn.byteship.cloud/f/p_test"


def _remote_path(api_path: str) -> str:
    """`/v1/files/cgen/req/part.step` -> `cgen/req/part.step`."""
    return api_path[len("/v1/files/") :]


def _spec(width: float = 40.0, depth: float = 30.0, height: float = 20.0) -> dict:
    return CADSpec(
        name="part",
        operation=BoxOperation(width=width, depth=depth, height=height),
    ).model_dump()


class Recorder:
    """Collects requests and serves canned Byteship responses."""

    def __init__(
        self,
        *,
        session_status: int = 201,
        bytes_status: int = 200,
        complete_status: int = 200,
        fetch_status: int = 200,
        session_body: object | None = None,
    ) -> None:
        self.session_status = session_status
        self.bytes_status = bytes_status
        self.complete_status = complete_status
        self.fetch_status = fetch_status
        self.session_body = session_body
        self.calls: list[httpx.Request] = []
        self.uploaded: list[bytes] = []
        self.stored: dict[str, bytes] = {}
        self.pending: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if request.method == "GET":
            if "/v1/files/" in path:
                remote = _remote_path(path)
                if remote not in self.stored:
                    return httpx.Response(404, json={"error": "not_found"})
                if self.fetch_status >= 400:
                    return httpx.Response(self.fetch_status, json={"error": "gone"})
                return httpx.Response(200, content=self.stored[remote])
            return httpx.Response(404)
        if path.endswith("/upload/complete"):
            return self._complete_response(path)
        if path == "/object-storage/put":
            self.uploaded.append(request.content)
            if self.pending:
                self.stored[self.pending.pop(0)] = request.content
            return httpx.Response(self.bytes_status)
        if self.session_status >= 400:
            return httpx.Response(self.session_status, json={"error": "nope"})
        remote = _remote_path(path)
        if self.session_body is None:
            self.pending.append(remote)
        body = (
            self.session_body
            if self.session_body is not None
            else {
                "file": {
                    "id": "f1",
                    "path": _remote_path(path),
                    "status": "pending",
                    "url": f"{CDN}/{_remote_path(path)}",
                },
                "upload": {
                    "id": "up1",
                    "fileId": "f1",
                    "method": "single",
                    "url": "https://storage.test/object-storage/put",
                    "headers": {"content-type": "model/stl", "x-amz-meta-run": "abc"},
                    "key": "k",
                },
            }
        )
        return httpx.Response(self.session_status, json=body)

    def _complete_response(self, api_path: str) -> httpx.Response:
        if self.complete_status >= 400:
            return httpx.Response(self.complete_status, json={"error": "boom"})
        remote = _remote_path(api_path.removesuffix("/upload/complete"))
        return httpx.Response(
            200,
            json={
                "file": {
                    "id": "f1",
                    "path": remote,
                    "status": "ready",
                    "url": f"{CDN}/{remote}",
                },
                "upload": {"id": "up1", "status": "completed"},
            },
        )

    @property
    def session_request(self) -> httpx.Request:
        return self.calls[0]

    @property
    def bytes_request(self) -> httpx.Request:
        return self.calls[1]

    @property
    def complete_request(self) -> httpx.Request:
        return self.calls[2]


def _client(rec: Recorder) -> ByteshipClient:
    transport = httpx.MockTransport(rec.handler)
    return ByteshipClient(KEY, client=httpx.Client(transport=transport))


# --- Configuration ---------------------------------------------------------


def test_missing_api_key_falls_back_to_local_store(monkeypatch):
    monkeypatch.delenv(bs.BYTESHIP_KEY_ENV, raising=False)
    store = default_artifact_store(FileStore())
    assert isinstance(store, LocalArtifactStore)


def test_api_key_present_selects_byteship(monkeypatch):
    monkeypatch.setenv(bs.BYTESHIP_KEY_ENV, KEY)
    store = default_artifact_store(FileStore())
    assert isinstance(store, ByteshipArtifactStore)


def test_api_key_is_read_from_environment_only():
    assert bs.BYTESHIP_KEY_ENV == "BYTESHIP_API_KEY"
    assert bs.byteship_api_key() == ""


def test_empty_api_key_rejected_at_client_construction():
    with pytest.raises(ValueError, match="must not be empty"):
        ByteshipClient("   ")


def test_artifact_paths_are_deterministic_and_prompt_free():
    a = artifact_path(request_id="abc123", stem="part", fmt="step")
    b = artifact_path(request_id="abc123", stem="part", fmt="step")
    assert a == b == "cgen/abc123/part.step"
    assert artifact_path(request_id="abc123", stem="part", fmt="stl") == (
        "cgen/abc123/part.stl"
    )
    assert ".." not in a


def test_never_exposes_key_in_paths_or_errors():
    rec = Recorder(session_status=401)
    client = _client(rec)
    with pytest.raises(ArtifactStorageError) as exc:
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    assert KEY not in str(exc.value)
    for call in rec.calls:
        assert KEY not in call.url.path


# --- Upload session --------------------------------------------------------


def test_session_request_contract():
    rec = Recorder()
    client = _client(rec)
    client.upload_file(
        path="cgen/req1/part.step",
        data=b"ISO-10303-21;",
        content_type="application/step",
        metadata={"source": "cgen"},
    )
    request = rec.session_request
    assert request.method == "PUT"
    assert request.url.path == "/v1/files/cgen/req1/part.step"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "application/json"
    payload = json.loads(request.content)
    assert payload["byteSize"] == len(b"ISO-10303-21;")
    assert payload["contentType"] == "application/step"
    assert payload["visibility"] == "public"
    assert payload["method"] == "auto"
    assert payload["metadata"] == {"source": "cgen"}


def test_session_uses_matching_content_types():
    assert bs.CONTENT_TYPES["step"] == "application/step"
    assert bs.CONTENT_TYPES["stl"] == "model/stl"
    rec = Recorder()
    client = _client(rec)
    client.upload_file(path="cgen/r/p.stl", data=b"solid", content_type="model/stl")
    payload = json.loads(rec.session_request.content)
    assert payload["contentType"] == "model/stl"


# --- Byte upload -----------------------------------------------------------


def test_byte_upload_uses_returned_url_headers_and_exact_bytes():
    rec = Recorder()
    client = _client(rec)
    payload = b"solid x\nendsolid x\n"
    client.upload_file(path="cgen/r/p.stl", data=payload, content_type="model/stl")
    upload = rec.bytes_request
    assert upload.method == "PUT"
    assert upload.url.host == "storage.test"
    # Headers returned by Byteship are used exactly as given.
    assert upload.headers["x-amz-meta-run"] == "abc"
    assert upload.content == payload
    assert rec.uploaded == [payload]
    # The API key must not be sent to object storage.
    assert "authorization" not in upload.headers


def test_empty_artifact_rejected_before_network():
    rec = Recorder()
    client = _client(rec)
    with pytest.raises(ArtifactStorageError, match="empty"):
        client.upload_file(path="cgen/r/p.step", data=b"", content_type="application/step")
    assert rec.calls == []


# --- Completion ------------------------------------------------------------


def test_completion_uses_upload_id_from_session():
    rec = Recorder()
    client = _client(rec)
    client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    complete = rec.complete_request
    assert complete.method == "POST"
    assert complete.url.path == "/v1/files/cgen/r/p.step/upload/complete"
    assert complete.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(complete.content) == {"uploadId": "up1"}


def test_delivery_url_returned_from_completion():
    rec = Recorder()
    client = _client(rec)
    url = client.upload_file(
        path="cgen/r/p.step", data=b"x", content_type="application/step"
    )
    assert url == f"{CDN}/cgen/r/p.step"


def test_fetch_returns_stored_bytes_with_server_side_key():
    """Read-back goes through the API; the CDN URL is never used server-side."""
    rec = Recorder()
    client = _client(rec)
    payload = b"solid x\nendsolid x\n"
    client.upload_file(path="cgen/r/p.stl", data=payload, content_type="model/stl")
    rec.calls.clear()

    fetched = client.fetch_file("cgen/r/p.stl")
    request = rec.calls[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/files/cgen/r/p.stl"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert fetched == payload


def test_fetch_missing_artifact_is_not_found():
    rec = Recorder(fetch_status=404)
    client = _client(rec)
    with pytest.raises(ArtifactNotFoundError):
        client.fetch_file("cgen/r/gone.stl")


def test_fetch_storage_failure_is_controlled():
    rec = Recorder(fetch_status=502)
    rec.stored["cgen/r/p.stl"] = b"solid\nendsolid\n"
    client = _client(rec)
    with pytest.raises(ArtifactStorageError, match="unavailable"):
        client.fetch_file("cgen/r/p.stl")


def test_malformed_session_response_is_controlled():
    rec = Recorder(session_body={"upload": {}})
    client = _client(rec)
    with pytest.raises(ArtifactStorageError, match="upload id"):
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")


# --- Failure handling ------------------------------------------------------


def test_session_failure_is_controlled():
    rec = Recorder(session_status=403)
    client = _client(rec)
    with pytest.raises(ArtifactStorageError) as exc:
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    assert "credentials" in str(exc.value)
    assert len(rec.calls) == 1


def test_byte_upload_failure_is_controlled():
    rec = Recorder(bytes_status=502)
    client = _client(rec)
    with pytest.raises(ArtifactStorageError) as exc:
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    assert "unavailable" in str(exc.value)
    assert len(rec.calls) == 2


def test_completion_failure_is_controlled():
    rec = Recorder(complete_status=409)
    client = _client(rec)
    with pytest.raises(ArtifactStorageError) as exc:
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    assert "finalize" in str(exc.value) or "again" in str(exc.value)
    assert len(rec.calls) == 3


def test_network_failure_is_controlled():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    client = ByteshipClient(KEY, client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(ArtifactStorageError, match="unreachable"):
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")


def test_error_messages_never_contain_secret_material():
    rec = Recorder(session_status=401)
    client = _client(rec)
    with pytest.raises(ArtifactStorageError) as exc:
        client.upload_file(path="cgen/r/p.step", data=b"x", content_type="application/step")
    message = str(exc.value)
    assert KEY not in message
    assert "Bearer" not in message
    assert "bship_" not in message


# --- Store: real generation, mocked storage -------------------------------


def test_rebuild_uploads_real_bytes_and_returns_delivery_urls():
    """Real CadQuery build -> real bytes -> mocked Byteship -> delivery URL."""
    from app.services.generation import run_rebuild

    rec = Recorder()
    store = ByteshipArtifactStore(_client(rec))
    base = _spec()
    wider = _spec(width=80.0)

    result = run_rebuild(
        base,
        wider,
        request_id="req-real-1",
        file_store=FileStore(),
        artifacts=store,
    )

    # Real STEP/STL bytes were uploaded, one session + upload + complete each.
    assert len(rec.uploaded) == 2
    step_blob, stl_blob = rec.uploaded
    assert b"ISO-10303" in step_blob  # STEP is ASCII
    assert len(stl_blob) > 84  # binary STL: 80-byte header + uint32 count + data
    assert stl_blob != step_blob

    # Delivery URLs are same-origin CGEN paths, not raw CDN URLs: the viewer
    # fetches these bytes and the Byteship CDN sends no CORS headers.
    assert result.files["step"].download_url == "/artifacts/req-real-1/part.step"
    assert result.files["stl"].download_url == "/artifacts/req-real-1/part.stl"
    assert "cdn.byteship.cloud" not in result.files["step"].download_url
    assert result.files["step"].bytes > 0
    assert result.files["stl"].bytes > 0

    # One session + upload + complete per artifact: three calls each, and the
    # declared byteSize matches the bytes actually uploaded.
    assert len(rec.calls) == 6
    session_calls = rec.calls[0::3]
    for session, blob in zip(session_calls, rec.uploaded, strict=True):
        assert json.loads(session.content)["byteSize"] == len(blob)


def test_store_pair_uses_deterministic_paths(tmp_path):
    step = tmp_path / "part.step"
    stl = tmp_path / "part.stl"
    step.write_bytes(b"ISO-10303-21;")
    stl.write_bytes(b"solid part\nendsolid part\n")

    rec = Recorder()
    store = ByteshipArtifactStore(_client(rec))
    urls = store.store_pair(
        step_path=step, stl_path=stl, stem="part", request_id="req-9"
    )
    assert urls.step == "/artifacts/req-9/part.step"
    assert urls.stl == "/artifacts/req-9/part.stl"
    session_paths = [c.url.path for c in rec.calls[0::3]]
    assert session_paths == [
        "/v1/files/cgen/req-9/part.step",
        "/v1/files/cgen/req-9/part.stl",
    ]


def test_store_pair_does_not_fabricate_urls_for_missing_files(tmp_path):
    rec = Recorder()
    store = ByteshipArtifactStore(_client(rec))
    with pytest.raises(OSError):
        store.store_pair(
            step_path=tmp_path / "nope.step",
            stl_path=tmp_path / "nope.stl",
            stem="part",
            request_id="r",
        )
    assert rec.calls == []


def test_local_store_keeps_pre_milestone_url_shape(tmp_path):
    step = tmp_path / "part.step"
    stl = tmp_path / "part.stl"
    step.write_bytes(b"ISO-10303-21;")
    stl.write_bytes(b"solid\nendsolid\n")
    store = LocalArtifactStore(FileStore())
    urls = store.store_pair(
        step_path=step, stl_path=stl, stem="part", request_id="r"
    )
    assert urls.step.startswith("/download/")
    assert urls.stl.startswith("/download/")
    assert urls.step.endswith("?format=step")
    assert urls.stl.endswith("?format=stl")
    token = urls.step.removeprefix("/download/").split("?")[0]
    assert urls.stl.removeprefix("/download/").split("?")[0] == token


def test_storage_failure_never_returns_success_urls():
    """A dead upload must raise, not yield an undeliverable URL."""
    from app.services.generation import run_rebuild

    rec = Recorder(bytes_status=502)
    store = ByteshipArtifactStore(_client(rec))
    with pytest.raises(ArtifactStorageError):
        run_rebuild(
            _spec(),
            _spec(width=80.0),
            request_id="req-fail",
            file_store=FileStore(),
            artifacts=store,
        )


def test_api_error_response_never_contains_key(monkeypatch):
    """A 500 from the API must not echo credentials back to the browser."""
    from fastapi.testclient import TestClient

    from app import main as main_module

    monkeypatch.setenv(bs.BYTESHIP_KEY_ENV, KEY)
    rec = Recorder(bytes_status=502)
    monkeypatch.setattr(
        main_module, "artifact_store", ByteshipArtifactStore(_client(rec))
    )
    client = TestClient(main_module.app, raise_server_exceptions=False)
    response = client.post(
        "/rebuild",
        json={"base_specification": _spec(), "specification": _spec(width=55.0)},
    )
    assert response.status_code >= 500
    assert KEY not in response.text
    assert "bship_" not in response.text
    assert "Bearer" not in response.text


# --- Delivery path safety and endpoint ------------------------------------


def test_delivery_path_is_same_origin_and_encoded():
    url = artifact_delivery_path(request_id="req 1", stem="my part", fmt="step")
    assert url.startswith("/artifacts/")
    assert " " not in url
    assert artifact_delivery_path(request_id="r", stem="p", fmt="stl") == (
        "/artifacts/r/p.stl"
    )


def test_filenames_are_sanitized_into_paths():
    from app.services.byteship import safe_filename

    assert safe_filename("../../etc/passwd", "step").endswith(".step")
    assert "/" not in safe_filename("../../etc/passwd", "step")
    assert safe_filename("we ird:name*", "stl") == "we_ird_name_.stl"


def test_path_rebuild_rejects_traversal_and_bad_format():
    good = artifact_path_from_name("req-1", "part.step")
    assert good == "cgen/req-1/part.step"
    # Traversal is neutralised rather than escaping the prefix.
    rebuilt = artifact_path_from_name("req-1", "..%2F..%2Fsecrets.step")
    assert rebuilt.startswith("cgen/req-1/")
    assert ".." not in rebuilt
    with pytest.raises(ArtifactNotFoundError):
        artifact_path_from_name("req-1", "part.exe")


def test_artifact_endpoint_serves_stored_bytes(monkeypatch):
    """The endpoint returns the same bytes a viewer fetch would receive."""
    from fastapi.testclient import TestClient

    from app import main as main_module

    rec = Recorder()
    store = ByteshipArtifactStore(_client(rec))
    monkeypatch.setattr(main_module, "artifact_store", store)
    # Seed the mock store through a real upload so the path/bytes match.
    store._client.upload_file(
        path="cgen/req-77/part.stl",
        data=b"solid part\nendsolid part\n",
        content_type="model/stl",
    )
    client = TestClient(main_module.app)
    response = client.get("/artifacts/req-77/part.stl")
    assert response.status_code == 200
    assert response.content == b"solid part\nendsolid part\n"
    assert response.headers["content-type"].startswith("model/stl")
    assert KEY not in response.text


def test_artifact_endpoint_404_for_unknown_artifact(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main as main_module

    monkeypatch.setattr(
        main_module, "artifact_store", ByteshipArtifactStore(_client(Recorder()))
    )
    client = TestClient(main_module.app)
    assert client.get("/artifacts/nope/missing.stl").status_code == 404


def test_artifact_endpoint_404_when_local_store_configured(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main as main_module

    monkeypatch.setattr(main_module, "artifact_store", LocalArtifactStore(FileStore()))
    client = TestClient(main_module.app)
    assert client.get("/artifacts/req-1/part.stl").status_code == 404

