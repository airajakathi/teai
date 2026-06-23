"""Signed workspace-file helpers for the WebUI canvas HTML/file preview.

Mirrors the signed-media pattern in :mod:`teai_builder.webui.media_api`, but serves
text/document assets (HTML, CSS, JS, JSON, SVG) from inside the workspace so the
canvas ``html`` type can render a file path. A signed URL is the capability:
only the gateway (which holds the per-process HMAC secret) can mint one, so an
iframe ``src`` works without a Bearer header while still being unforgeable.
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
import mimetypes
from pathlib import Path

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from teai_builder.webui.http_utils import http_error as _http_error
from teai_builder.webui.http_utils import http_response as _http_response
from teai_builder.webui.media_api import b64url_decode, b64url_encode

# Text/document MIME types we are willing to serve from a workspace file path.
# HTML is served with a sandboxing CSP; everything else with nosniff so a
# signed URL can never be coerced into executing in the gateway's own origin.
_FILES_ALLOWED_MIMES: dict[str, str] = {
    "text/html": "text/html; charset=utf-8",
    "text/css": "text/css; charset=utf-8",
    "text/javascript": "text/javascript; charset=utf-8",
    "application/javascript": "text/javascript; charset=utf-8",
    "application/json": "application/json; charset=utf-8",
    "text/plain": "text/plain; charset=utf-8",
    "image/svg+xml": "image/svg+xml",
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}

# CSP applied to served HTML so a canvas preview cannot exfiltrate or reach back
# into the gateway. Scripts/styles run inline (the previewed app needs them) but
# the document is sandboxed and cannot navigate the top frame.
_HTML_PREVIEW_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'self' data: blob:; "
        "img-src 'self' data: blob: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; "
        "frame-ancestors 'self'; sandbox allow-scripts allow-forms allow-popups allow-same-origin",
    ),
    ("X-Content-Type-Options", "nosniff"),
)

_MAX_FILE_BYTES = 8 * 1024 * 1024


def sign_workspace_file(
    abs_path: Path,
    *,
    secret: bytes,
    workspace_root: Path,
) -> str | None:
    """Return a signed ``/api/files/<sig>/<payload>`` URL for a workspace file."""
    try:
        root = workspace_root.resolve()
        rel = abs_path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    suffix = abs_path.suffix.lower()
    mime, _ = mimetypes.guess_type(f"x{suffix}")
    if mime not in _FILES_ALLOWED_MIMES:
        return None
    payload = b64url_encode(rel.as_posix().encode("utf-8"))
    mac = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()[:16]
    return f"/api/files/{b64url_encode(mac)}/{payload}"


def serve_signed_workspace_file(
    sig: str,
    payload: str,
    *,
    secret: bytes,
    workspace_root: Path,
    request: WsRequest | None = None,  # noqa: ARG001 - parity with media serve signature
) -> Response:
    """Serve a signed workspace file with a sandboxing CSP for HTML."""
    try:
        provided_mac = b64url_decode(sig)
    except (ValueError, binascii.Error):
        return _http_error(401, "invalid signature")
    expected_mac = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(expected_mac, provided_mac):
        return _http_error(401, "invalid signature")
    try:
        rel_str = b64url_decode(payload).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return _http_error(400, "invalid payload")
    try:
        root = workspace_root.resolve()
        candidate = (root / rel_str).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return _http_error(404, "not found")
    if not candidate.is_file():
        return _http_error(404, "not found")

    mime, _ = mimetypes.guess_type(candidate.name)
    served_mime = _FILES_ALLOWED_MIMES.get(mime or "")
    if served_mime is None:
        return _http_error(415, "unsupported file type")
    try:
        if candidate.stat().st_size > _MAX_FILE_BYTES:
            return _http_error(413, "file too large")
        body = candidate.read_bytes()
    except OSError:
        return _http_error(500, "read error")

    extra_headers = [("Cache-Control", "private, max-age=60")]
    if (mime or "") in {"text/html", "image/svg+xml"}:
        extra_headers.extend(_HTML_PREVIEW_HEADERS)
    else:
        extra_headers.append(("X-Content-Type-Options", "nosniff"))
    return _http_response(body, status=200, content_type=served_mime, extra_headers=extra_headers)
