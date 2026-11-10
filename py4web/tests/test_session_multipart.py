"""Regression coverage for malformed multipart requests reaching session loading."""

import secrets
from io import BytesIO

import pytest
from common.fixtures.session import PoppableSession

from py4web import HTTP, action, request

BOUNDARY = "pytest-multipart-boundary"


def _set_request_body(body: bytes, content_type: str, cookie: str = "") -> None:
    """Pass raw request bytes to Ombott without pre-populating parsed forms."""
    request.environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(body),
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_COOKIE": cookie,
    }
    request.app_name = "_default"


@pytest.fixture()
def multipart_session(default_app_request_context: None) -> PoppableSession:
    """Use a real cookie-backed session without accessing Redis."""
    return PoppableSession(secret=secrets.token_hex(32), name="multipart_test_session")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"A" * 64, id="invalid-boundary"),
        pytest.param(
            (f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="message"\r\n\r\n').encode()
            + b"\x82\r\n"
            + f"--{BOUNDARY}--\r\n".encode(),
            id="invalid-utf8-field",
        ),
    ],
)
@pytest.mark.parametrize("cookie", ["", "multipart_test_session=invalid-token"])
def test_session_rejects_malformed_multipart(multipart_session: PoppableSession, body: bytes, cookie: str) -> None:
    """Bad multipart data returns 400 even when a cookie skips session form lookup."""
    _set_request_body(body, f"multipart/form-data; boundary={BOUNDARY}", cookie=cookie)
    calls: list[str] = []

    @action.uses(multipart_session)
    def endpoint() -> str:
        calls.append("called")
        return "accepted"

    with pytest.raises(HTTP) as rejected:
        endpoint()

    assert rejected.value.status == 400
    assert calls == []


def test_session_preserves_multipart_fields_and_binary_uploads(multipart_session: PoppableSession) -> None:
    """Parsing before session loading preserves Unicode fields and arbitrary file bytes."""
    upload = b"\x82\x00\xffbinary upload"
    body = (
        (
            f"--{BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="message"\r\n\r\n'
            "Café\r\n"
            f"--{BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="upload"; filename="sample.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + upload
        + f"\r\n--{BOUNDARY}--\r\n".encode()
    )
    _set_request_body(body, f"multipart/form-data; boundary={BOUNDARY}")

    @action.uses(multipart_session)
    def endpoint() -> dict[str, str | bytes]:
        multipart_session["loaded"] = True
        return {
            "message": request.forms["message"],
            "upload": request.files["upload"].file.read(),
        }

    assert endpoint() == {"message": "Café", "upload": upload}


def test_session_preserves_urlencoded_forms(multipart_session: PoppableSession) -> None:
    """Ordinary forms continue through the session fixture unchanged."""
    _set_request_body(b"message=Caf%C3%A9", "application/x-www-form-urlencoded")

    @action.uses(multipart_session)
    def endpoint() -> str:
        return request.forms["message"]

    assert endpoint() == "Café"


def test_session_does_not_hide_application_decode_errors(multipart_session: PoppableSession) -> None:
    """A decode failure in the controller remains an application error."""
    _set_request_body(b"message=valid", "application/x-www-form-urlencoded")

    @action.uses(multipart_session)
    def endpoint() -> str:
        return b"\x82".decode("utf-8")

    with pytest.raises(UnicodeDecodeError):
        endpoint()
