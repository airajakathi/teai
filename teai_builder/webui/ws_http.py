"""HTTP API handler extracted from WebSocketChannel.

Handles all non-WebSocket HTTP routes: bootstrap, sessions, settings,
media, commands, sidebar state, static file serving, and token management.

Also houses shared HTTP utility functions used by both this module and
``websocket.py`` to avoid circular imports.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from teai_builder.bus.events import InboundMessage
from teai_builder.command.builtin import builtin_command_palette
from teai_builder.utils.subagent_channel_display import scrub_subagent_messages_for_channel
from teai_builder.webui.file_preview import (
    WebUIFilePreviewError,
    file_preview_payload,
    file_symbol_payload,
)
from teai_builder.webui.gateway_tokens import GatewayTokenStore, token_response_payload
from teai_builder.webui.http_utils import (
    case_insensitive_header as _case_insensitive_header,
)
from teai_builder.webui.http_utils import (
    host_for_url as _host_for_url,
)
from teai_builder.webui.http_utils import (
    http_error as _http_error,
)
from teai_builder.webui.http_utils import (
    http_json_response as _http_json_response,
)
from teai_builder.webui.http_utils import (
    http_response as _http_response,
)
from teai_builder.webui.http_utils import (
    is_localhost as _is_localhost,
)
from teai_builder.webui.http_utils import (
    issue_route_secret_matches as _issue_route_secret_matches,
)
from teai_builder.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from teai_builder.webui.http_utils import (
    parse_query as _parse_query,
)
from teai_builder.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from teai_builder.webui.http_utils import (
    query_first as _query_first,
)
from teai_builder.webui.http_utils import (
    safe_host_header as _safe_host_header,
)
from teai_builder.webui.media_gateway import WebUIMediaGateway
from teai_builder.webui.session_automations import (
    serialize_automation_jobs,
    session_automation_jobs,
    session_automations_payload,
)
from teai_builder.webui.session_list_index import list_webui_sessions
from teai_builder.webui.sidebar_state import (
    read_webui_sidebar_state,
    write_webui_sidebar_state,
)
from teai_builder.webui.projects import bootstrap_project
from teai_builder.webui.skills_api import webui_skill_detail_payload, webui_skills_payload
from teai_builder.webui.tools_api import webui_tools_payload
from teai_builder.webui.thread_disk import delete_webui_thread
from teai_builder.webui.transcript import build_webui_thread_response
from teai_builder.webui.workspaces import WebUIWorkspaceController

if TYPE_CHECKING:
    from teai_builder.bus.queue import MessageBus
    from teai_builder.cron.service import CronService
    from teai_builder.session.manager import SessionManager


def _decode_api_key(raw_key: str) -> str | None:
    from urllib.parse import unquote

    key = unquote(raw_key)
    _api_key_re = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")
    if _api_key_re.match(key) is None:
        return None
    return key


def _default_model_name_from_config() -> str | None:
    try:
        from teai_builder.config.loader import load_config
        model = load_config().resolve_preset().model.strip()
        return model or None
    except Exception as e:
        logger.debug("bootstrap model_name could not load from config: {}", e)
        return None


def _resolve_bootstrap_model_name(
    runtime_name: Callable[[], str | None] | None,
) -> str:
    if runtime_name is not None:
        try:
            raw = runtime_name()
        except Exception as e:
            logger.debug("bootstrap runtime model resolver failed: {}", e)
        else:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped:
                    return stripped
    return _default_model_name_from_config() or ""


# ---------------------------------------------------------------------------
# GatewayHTTPHandler
# ---------------------------------------------------------------------------


class GatewayHTTPHandler:
    """Handles all HTTP routes served alongside the WebSocket endpoint.

    Routes HTTP requests and delegates stateful work to explicit gateway
    services owned by the composition layer.
    """

    def __init__(
        self,
        *,
        config: Any,  # WebSocketConfig
        session_manager: SessionManager | None,
        static_dist_path: Path | None,
        runtime_model_name: Callable[[], str | None] | None,
        runtime_surface: str,
        runtime_capabilities_overrides: dict[str, Any] | None,
        bus: MessageBus,
        tokens: GatewayTokenStore,
        media: WebUIMediaGateway,
        workspaces: WebUIWorkspaceController,
        skills_workspace_path: Path,
        tools_config: Any,
        disabled_skills: set[str] | None = None,
        cron_service: CronService | None = None,
        cron_pending_job_ids: Callable[[str], set[str]] | None = None,
        log: Any = logger,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.static_dist_path = static_dist_path
        self.runtime_model_name = runtime_model_name
        self.bus = bus
        self.tokens = tokens
        self.media = media
        self.workspaces = workspaces
        self.skills_workspace_path = skills_workspace_path
        self.tools_config = tools_config
        self.disabled_skills = disabled_skills or set()
        self.cron_service = cron_service
        self.cron_pending_job_ids = cron_pending_job_ids
        self._log = log
        self._runtime_surface = runtime_surface

        from teai_builder.webui.settings_api import runtime_capabilities as _rc
        from teai_builder.webui.settings_routes import WebUISettingsRouter

        self._capabilities = _rc(runtime_surface, runtime_capabilities_overrides or {})
        self.settings_routes = WebUISettingsRouter(
            bus=bus,
            logger=self._log,
            check_api_token=self.check_api_token,
            parse_query=_parse_query,
            json_response=_http_json_response,
            error_response=_http_error,
            runtime_surface=runtime_surface,
            runtime_capabilities=self._capabilities,
        )

    def workspace_controls_available(self, connection: Any) -> bool:
        return self._runtime_surface == "native" or _is_localhost(connection)

    # -- Token management ---------------------------------------------------

    def check_api_token(self, request: WsRequest) -> bool:
        return self.tokens.check_api_token(request)

    # -- Main dispatch ------------------------------------------------------

    async def dispatch(self, connection: Any, request: WsRequest) -> Any | None:
        """Route an HTTP request. Returns Response or None."""
        got, _ = _parse_request_path(request.path)

        # Health check
        if got == "/health":
            return _http_json_response({"status": "ok"})

        # Token issue endpoint
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue(connection, request)

        # Bootstrap
        if got == "/webui/bootstrap":
            return self._handle_bootstrap(connection, request)

        # Settings routes (delegated)
        response = await self.settings_routes.dispatch(request, got)
        if response is not None:
            return response

        # Session routes
        response = self._dispatch_session_routes(request, got)
        if response is not None:
            return response

        # Media routes
        response = self._dispatch_media_routes(request, got)
        if response is not None:
            return response

        # Misc routes
        response = self._dispatch_misc_routes(connection, request, got)
        if response is not None:
            return response

        # API 404 (never serve SPA for /api/ routes)
        if got.startswith("/api/"):
            return _http_error(404, "API route not found")

        # Static SPA serving
        if self.static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response
            
            # Fallback to index.html for SPA routing if no other route matched
            response = self._serve_static("index.html")
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    # -- Token issue --------------------------------------------------------

    def _handle_token_issue(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self._log.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        if not self.tokens.can_issue():
            self._log.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self.tokens.issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = self.tokens.issue_token(self.config.token_ttl_s)
        return _http_json_response(token_response_payload(token_value, self.config.token_ttl_s))

    # -- Bootstrap ----------------------------------------------------------

    def _handle_bootstrap(self, connection: Any, request: Any) -> Response:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return _http_error(401, "Unauthorized")
        # Allow bootstrap from non-localhost in sandbox environment
        # elif not _is_localhost(connection):
        #     return _http_error(403, "bootstrap is localhost-only")

        if not self.tokens.can_issue(include_api_token=True):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
            )
        token = self.tokens.issue_token(self.config.token_ttl_s, api_token=True)

        ws_url = self._bootstrap_ws_url(request)
        expected_path = _normalize_config_path(self.config.path)
        return _http_json_response(
            {
                "token": token,
                "ws_path": expected_path,
                "ws_url": ws_url,
                "expires_in": self.config.token_ttl_s,
                "model_name": _resolve_bootstrap_model_name(self.runtime_model_name),
                "runtime_surface": self._runtime_surface,
                "runtime_capabilities": self._capabilities,
            }
        )

    def _bootstrap_ws_url(self, request: Any) -> str:
        headers = getattr(request, "headers", {}) or {}
        host = _safe_host_header(_case_insensitive_header(headers, "Host"))
        if not host:
            host = _host_for_url(self.config.host, self.config.port)
        proto = _case_insensitive_header(headers, "X-Forwarded-Proto")
        proto = proto.split(",", 1)[0].strip().lower()
        secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())
        scheme = "wss" if secure else "ws"
        expected_path = _normalize_config_path(self.config.path)
        return f"{scheme}://{host}{expected_path}"

    # -- Session routes -----------------------------------------------------

    def _dispatch_session_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return self._handle_session_messages(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/webui-thread$", got)
        if m:
            return self._handle_webui_thread_get(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/file-preview$", got)
        if m:
            return self._handle_file_preview(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/file-symbols$", got)
        if m:
            return self._handle_file_symbols(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/workspace-tree$", got)
        if m:
            return self._handle_workspace_tree(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/workspace-search$", got)
        if m:
            return self._handle_workspace_search(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/workspace-content-search$", got)
        if m:
            return self._handle_workspace_content_search(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/workspace-symbol-search$", got)
        if m:
            return self._handle_workspace_symbol_search(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/workspace-reference-search$", got)
        if m:
            return self._handle_workspace_reference_search(request, m.group(1))
        m = re.match(r"^/api/sessions/([^/]+)/workspace-problems$", got)
        if m:
            return self._handle_workspace_problems(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/automations$", got)
        if m:
            return self._handle_session_automations(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/workflow-runs/([^/]+)/([^/]+)$", got)
        if m:
            return self._handle_session_workflow_run_action(request, m.group(1), m.group(2), m.group(3))

        m = re.match(r"^/api/sessions/([^/]+)/workflow-runs/([^/]+)$", got)
        if m:
            return self._handle_session_workflow_run_detail(request, m.group(1), m.group(2))

        m = re.match(r"^/api/sessions/([^/]+)/workflow-runs$", got)
        if m:
            return self._handle_session_workflow_runs(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/checkpoints/([^/]+)/rebuild$", got)
        if m:
            return self._handle_session_checkpoint_rebuild(request, m.group(1), m.group(2))

        m = re.match(r"^/api/sessions/([^/]+)/checkpoints/([^/]+)/restore$", got)
        if m:
            return self._handle_session_checkpoint_restore(request, m.group(1), m.group(2))

        m = re.match(r"^/api/sessions/([^/]+)/checkpoints$", got)
        if m:
            return self._handle_session_checkpoints(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return self._handle_session_delete(request, m.group(1))

        return None

    def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        sessions = list_webui_sessions(self.session_manager)
        from teai_builder.session.webui_turns import websocket_turn_wall_started_at

        cleaned = []
        for s in sessions:
            key = s.get("key")
            if not (isinstance(key, str) and key.startswith("websocket:")):
                continue
            row = {k: v for k, v in s.items() if k != "path"}
            chat_id = key.split(":", 1)[1]
            started_at = websocket_turn_wall_started_at(chat_id)
            if started_at is not None:
                row["run_started_at"] = started_at
            scope = self.workspaces.scope_for_session_key(key)
            row["workspace_scope"] = scope.payload()
            project = self.workspaces.project_for_session_key(key)
            if project is not None:
                row["project"] = project
            cleaned.append(row)
        return _http_json_response({"sessions": cleaned})

    def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = self.session_manager.read_session_file(decoded_key)
        if data is None:
            return _http_error(404, "session not found")
        messages = data.get("messages")
        if isinstance(messages, list):
            scrub_subagent_messages_for_channel(messages)
        self.media.augment_media_urls(data)
        scope = self.workspaces.scope_for_session_key(decoded_key)
        data["workspace_scope"] = scope.payload()
        project = self.workspaces.project_for_session_key(decoded_key)
        if project is not None:
            data["project"] = project
        return _http_json_response(data)

    def _handle_webui_thread_get(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        scope = self.workspaces.scope_for_session_key(decoded_key)
        session_messages: list[dict[str, Any]] | None = None
        if self.session_manager is not None:
            session_data = self.session_manager.read_session_file(decoded_key)
            raw_messages = session_data.get("messages") if isinstance(session_data, dict) else None
            if isinstance(raw_messages, list):
                session_messages = [m for m in raw_messages if isinstance(m, dict)]
        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit: int | None = None
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        direction = _query_first(query, "direction")
        if direction is not None and direction not in {"latest"}:
            return _http_error(400, "invalid direction")
        before = _query_first(query, "before")
        data = build_webui_thread_response(
            decoded_key,
            augment_user_media=self.media.augment_transcript_media,
            augment_assistant_media=self.media.augment_transcript_media,
            augment_assistant_text=lambda text: self.media.rewrite_local_markdown_images(
                text,
                workspace_path=scope.project_path,
            ),
            augment_canvas_content=self.media.sign_canvas_content,
            session_messages=session_messages,
            limit=limit,
            direction=direction,
            before=before,
        )
        if data is None:
            return _http_error(404, "webui thread not found")
        data["workspace_scope"] = scope.payload()
        project = self.workspaces.project_for_session_key(decoded_key)
        if project is not None:
            data["project"] = project
        return _http_json_response(data)

    def _handle_file_preview(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        path = _query_first(_parse_query(request.path), "path")
        try:
            payload = file_preview_payload(
                path,
                scope=self.workspaces.scope_for_session_key(decoded_key),
            )
        except WebUIFilePreviewError as e:
            return _http_error(e.status, e.message)
        return _http_json_response(payload)

    def _handle_file_symbols(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        path = _query_first(_parse_query(request.path), "path")
        try:
            payload = file_symbol_payload(
                path,
                scope=self.workspaces.scope_for_session_key(decoded_key),
            )
        except WebUIFilePreviewError as e:
            return _http_error(e.status, e.message)
        return _http_json_response(payload)

    def _handle_workspace_tree(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.webui.workspace_tree import workspace_tree_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(workspace_tree_payload(scope=scope))

    def _handle_workspace_search(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit = 40
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        from teai_builder.webui.workspace_search import workspace_search_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(
            workspace_search_payload(
                scope=scope,
                query=_query_first(query, "q") or "",
                limit=limit,
            )
        )

    def _handle_workspace_content_search(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit = 40
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        from teai_builder.webui.workspace_search import workspace_content_search_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(
            workspace_content_search_payload(
                scope=scope,
                query=_query_first(query, "q") or "",
                limit=limit,
            )
        )

    def _handle_workspace_symbol_search(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit = 40
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        from teai_builder.webui.workspace_search import workspace_symbol_search_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(
            workspace_symbol_search_payload(
                scope=scope,
                query=_query_first(query, "q") or "",
                limit=limit,
            )
        )

    def _handle_workspace_reference_search(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit = 40
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        from teai_builder.webui.workspace_search import workspace_reference_search_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(
            workspace_reference_search_payload(
                scope=scope,
                query=_query_first(query, "q") or "",
                limit=limit,
            )
        )

    def _handle_workspace_problems(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit = 40
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        from teai_builder.webui.workspace_search import workspace_problems_payload

        scope = self.workspaces.scope_for_session_key(decoded_key)
        return _http_json_response(
            workspace_problems_payload(
                scope=scope,
                query=_query_first(query, "q") or "",
                limit=limit,
            )
        )

    def _handle_session_automations(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        pending_job_ids: set[str] = set()
        if self.cron_pending_job_ids is not None:
            pending_job_ids = self.cron_pending_job_ids(decoded_key)
        return _http_json_response(
            session_automations_payload(
                self.cron_service,
                decoded_key,
                pending_job_ids=pending_job_ids,
            )
        )

    def _handle_session_workflow_runs(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.agent.llm3.workflow_service import LLM3WorkflowService

        items = []
        runs = LLM3WorkflowService.list_runs_from_storage(
            limit=50,
        )
        for run in runs:
            if run.metadata.get("session_key") != decoded_key:
                continue
            items.append(
                {
                    "run_id": run.run_id,
                    "workflow_id": run.workflow_id,
                    "goal_id": run.goal_id,
                    "state": run.state,
                    "current_step": run.current_step,
                    "updated_at": run.updated_at,
                    "finished_at": run.finished_at,
                    "error": run.error,
                    "step_count": len(run.step_states),
                    "completed_steps": sum(
                        1
                        for step in run.step_states.values()
                        if step.state == "completed"
                    ),
                }
            )
        return _http_json_response({"items": items})

    def _handle_session_workflow_run_detail(
        self,
        request: WsRequest,
        key: str,
        run_id: str,
    ) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.agent.llm3.workflow_service import LLM3WorkflowService

        run = LLM3WorkflowService.load_run_from_storage(run_id)
        if run is None or run.metadata.get("session_key") != decoded_key:
            return _http_error(404, "workflow run not found")
        checkpoints = []
        for item in run.metadata.get("checkpoints", []) or []:
            if isinstance(item, dict):
                checkpoints.append(
                    {
                        "step_id": item.get("step_id"),
                        "saved_at": item.get("saved_at"),
                        "checkpoint_id": item.get("checkpoint_id"),
                        "result_keys": item.get("result_keys", []),
                    }
                )
        return _http_json_response(
            {
                "run": {
                    "run_id": run.run_id,
                    "workflow_id": run.workflow_id,
                    "goal_id": run.goal_id,
                    "state": run.state,
                    "current_step": run.current_step,
                    "started_at": run.started_at,
                    "updated_at": run.updated_at,
                    "finished_at": run.finished_at,
                    "error": run.error,
                    "cancel_requested": run.cancel_requested,
                    "step_count": len(run.step_states),
                    "completed_steps": sum(
                        1
                        for step in run.step_states.values()
                        if step.state == "completed"
                    ),
                    "step_results": run.step_results,
                    "status_history": [
                        {
                            "state": item.get("state"),
                            "detail": item.get("detail"),
                            "at": item.get("at", item.get("timestamp")),
                        }
                        for item in run.status_history
                        if isinstance(item, dict)
                    ],
                    "checkpoints": checkpoints,
                    "step_states": [
                        {
                            "step_id": step_id,
                            "name": step_run.name,
                            "state": step_run.state,
                            "attempts": step_run.attempts,
                            "started_at": step_run.started_at,
                            "finished_at": step_run.finished_at,
                            "error": step_run.error,
                            "output": step_run.output,
                        }
                        for step_id, step_run in run.step_states.items()
                    ],
                }
            }
        )

    def _dispatch_workflow_command(self, session_key: str, command: str) -> bool:
        if self.bus is None:
            return False
        try:
            _, chat_id = session_key.split(":", 1)
        except ValueError:
            return False
        published = self.bus.publish_inbound(
            InboundMessage(
                channel="websocket",
                sender_id="webui",
                chat_id=chat_id,
                content=command,
            )
        )
        if not asyncio.iscoroutine(published):
            return False
        try:
            asyncio.get_running_loop().create_task(published)
        except RuntimeError:
            asyncio.run(published)
        return True

    def _handle_session_workflow_run_action(
        self,
        request: WsRequest,
        key: str,
        run_id: str,
        action: str,
    ) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        action_name = action.lower()
        if action_name not in {"resume", "cancel"}:
            return _http_error(404, "workflow action not found")
        command = f"/workflow {action_name} {run_id}"
        if not self._dispatch_workflow_command(decoded_key, command):
            return _http_error(503, "workflow control unavailable")
        return _http_json_response(
            {
                "accepted": True,
                "action": action_name,
                "command": command,
            }
        )

    def _handle_session_checkpoints(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.agent.checkpoint import (
            Checkpoint,
            get_checkpoint_store,
            summarize_checkpoint,
        )

        store = get_checkpoint_store()
        request_method = getattr(request, "method", "GET")
        if str(request_method).upper() == "POST":
            if self.session_manager is None:
                return _http_error(503, "session manager unavailable")
            session = self.session_manager.get_or_create(decoded_key)
            checkpoint = Checkpoint(
                checkpoint_id=f"{int(time.time())}",
                session_key=session.key,
                created_at=time.time(),
                context_budget_pct=0.0,
                state={},
                messages=session.get_history(max_messages=0),
                metadata={"kind": "session"},
            )
            store.save(checkpoint)
            return _http_json_response({"checkpoint_id": checkpoint.checkpoint_id})
        items = [
            summarize_checkpoint(item)
            for item in [
                store.load(decoded_key, raw["checkpoint_id"])
                for raw in store.list_for_session(decoded_key)
            ]
            if item is not None
        ]
        items.sort(key=lambda row: row.get("created_at", 0), reverse=True)
        return _http_json_response({"items": items})

    def _handle_session_checkpoint_rebuild(
        self,
        request: WsRequest,
        key: str,
        checkpoint_id: str,
    ) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.agent.checkpoint import (
            build_rebuild_summary,
            get_checkpoint_store,
            summarize_checkpoint,
        )

        store = get_checkpoint_store()
        checkpoint = store.load(decoded_key, checkpoint_id)
        if checkpoint is None:
            return _http_error(404, "checkpoint not found")
        return _http_json_response(
            {
                "summary": build_rebuild_summary(checkpoint),
                "checkpoint": summarize_checkpoint(checkpoint),
            }
        )

    def _handle_session_checkpoint_restore(
        self,
        request: WsRequest,
        key: str,
        checkpoint_id: str,
    ) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        from teai_builder.agent.checkpoint import get_checkpoint_store

        store = get_checkpoint_store()
        restored = store.load(decoded_key, checkpoint_id)
        if restored is None:
            return _http_error(404, "checkpoint not found")
        session = self.session_manager.get_or_create(decoded_key)
        session.messages = restored.messages
        self.session_manager.save(session)
        return _http_json_response({"restored": True})

    def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        query = _parse_query(request.path)
        delete_automations = (_query_first(query, "delete_automations") or "").lower()
        automation_jobs = session_automation_jobs(self.cron_service, decoded_key)
        if automation_jobs and delete_automations not in {"1", "true", "yes"}:
            return _http_json_response(
                {
                    "deleted": False,
                    "blocked_by_automations": True,
                    "automations": serialize_automation_jobs(automation_jobs),
                }
            )
        if automation_jobs and self.cron_service is not None:
            for job in automation_jobs:
                self.cron_service.remove_job(job.id)
        deleted = self.session_manager.delete_session(decoded_key)
        delete_webui_thread(decoded_key)
        return _http_json_response({"deleted": bool(deleted)})

    # -- Media routes -------------------------------------------------------

    def _dispatch_media_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2), request)
        m = re.match(r"^/api/files/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self.media.serve_workspace_file(m.group(1), m.group(2), request=request)
        return None

    def _handle_media_fetch(
        self, sig: str, payload: str, request: WsRequest | None = None
    ) -> Response:
        return self.media.serve_signed_media(
            sig,
            payload,
            request=request,
        )

    # -- Misc routes --------------------------------------------------------

    def _dispatch_misc_routes(
        self, connection: Any, request: WsRequest, got: str
    ) -> Response | None:
        if got == "/api/sessions":
            return self._handle_sessions_list(request)
        if got == "/api/commands":
            return self._handle_commands(request)
        if got == "/api/workspaces":
            return self._handle_workspaces(connection, request)
        if got == "/api/projects":
            return self._handle_projects(request)
        if got == "/api/projects/bootstrap":
            return self._handle_projects_bootstrap(connection, request)
        if got == "/api/workspace-folders":
            return self._handle_workspace_folders(request)
        if got == "/api/webui/skills":
            return self._handle_webui_skills(request)
        if got == "/api/webui/tools":
            return self._handle_webui_tools(request)
        if got == "/api/workflows":
            return self._handle_workflows(request)
        m = re.match(r"^/api/webui/skills/([^/]+)$", got)
        if m:
            return self._handle_webui_skill_detail(request, m.group(1))
        if got == "/api/webui/sidebar-state":
            return self._handle_webui_sidebar_state(request)
        if got == "/api/webui/sidebar-state/update":
            return self._handle_webui_sidebar_state_update(request)
        return None

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_workspaces(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            self.workspaces.payload(
                controls_available=self.workspace_controls_available(connection)
            )
        )

    def _handle_projects(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(self.workspaces.projects_payload())

    def _handle_projects_bootstrap(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if not self.workspace_controls_available(connection):
            return _http_error(403, "workspace controls are localhost-only")
        query = _parse_query(request.path)
        project_name = (_query_first(query, "name") or "").strip()
        access_mode = (_query_first(query, "access_mode") or "restricted").strip()
        try:
            payload = bootstrap_project(
                project_name,
                default_workspace=self.workspaces.default_workspace(),
                access_mode=access_mode,
                source_channel="websocket",
            )
        except ValueError as e:
            return _http_error(400, str(e))
        except Exception:
            self._log.exception("failed to bootstrap project")
            return _http_error(500, "failed to bootstrap project")
        return _http_json_response(payload)

    def _handle_workspace_folders(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        folders = []
        try:
            workspace_root = Path(self.workspaces.default_workspace()).resolve()
            if workspace_root.is_dir():
                for entry in sorted(workspace_root.iterdir(), key=lambda p: p.name.lower()):
                    if entry.is_dir() and entry.name not in {"sessions", "cron", "memory", "webui"}:
                        folders.append({
                            "path": str(entry),
                            "name": entry.name,
                        })
        except OSError:
            pass
        return _http_json_response({"folders": folders})

    def _handle_webui_skills(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            webui_skills_payload(
                self.skills_workspace_path,
                disabled_skills=self.disabled_skills,
            )
        )

    def _handle_webui_tools(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            webui_tools_payload(
                workspace_path=self.skills_workspace_path,
                tools_config=self.tools_config,
                bus=self.bus,
                cron_service=self.cron_service,
                sessions=self.session_manager,
            )
        )

    def _handle_workflows(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from teai_builder.agent.llm3.workflow_library import list_workflows

        return _http_json_response(
            {
                "workflows": [
                    {
                        "workflow_id": workflow.workflow_id,
                        "name": workflow.name,
                        "description": workflow.description,
                    }
                    for workflow in list_workflows()
                ]
            }
        )

    def _handle_webui_skill_detail(self, request: WsRequest, raw_name: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from urllib.parse import unquote

        name = unquote(raw_name)
        if not name or "/" in name or "\\" in name:
            return _http_error(400, "invalid skill name")
        payload = webui_skill_detail_payload(
            self.skills_workspace_path,
            name,
            disabled_skills=self.disabled_skills,
        )
        if payload is None:
            return _http_error(404, "skill not found")
        return _http_json_response(payload)

    def _handle_webui_sidebar_state(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(read_webui_sidebar_state())

    def _handle_webui_sidebar_state_update(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        query = _parse_query(request.path)
        raw_state = _query_first(query, "state")
        if raw_state is None:
            return _http_error(400, "missing state")
        try:
            decoded = json.loads(raw_state)
        except json.JSONDecodeError:
            return _http_error(400, "state must be JSON")
        if not isinstance(decoded, dict):
            return _http_error(400, "state must be an object")
        try:
            state = write_webui_sidebar_state(decoded)
        except ValueError as e:
            return _http_error(400, str(e))
        except OSError:
            self._log.exception("failed to write webui sidebar state")
            return _http_error(500, "failed to write sidebar state")
        return _http_json_response(state)

    # -- Static file serving ------------------------------------------------

    def _serve_static(self, request_path: str) -> Response | None:
        assert self.static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self.static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self.static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            index = self.static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            self._log.warning("static: failed to read {}: {}", candidate, e)
            return _http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )

def _is_websocket_channel_session_key(key: str) -> bool:
    return key.startswith("websocket:")
