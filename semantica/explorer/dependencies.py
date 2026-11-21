"""
Semantica Explorer : FastAPI Dependencies

Provides ``Depends()``-compatible callables for injecting the
current ``GraphSession`` into route handlers, and for enforcing authentication
and caller identity (JWT bearer tokens and API keys) on protected routes.
WebSocket manager access is handled directly via ``app.state.ws_manager``.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security.api_key import APIKeyHeader

from ..auth.dependencies import (
    anonymous_access_allowed,
    get_current_identity,
    get_expected_api_key,
    is_auth_configured,
    is_valid_api_key,
    require_auth,
    require_workspace_role,
)
from ..auth.models import RequestContext
from ..auth.store import AuthStore, get_auth_store
from ..context.agent_memory import AgentMemory
from .markdown_resources import MarkdownResourceRegistry
from .session import GraphSession

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_session(request: Request) -> GraphSession:
    """Retrieve the ``GraphSession`` for the current request's workspace.

    Resolution order:
    1. If a ``WorkspaceSessionRegistry`` is available on ``app.state``, resolve
       the workspace from the caller's ``RequestContext`` (set by the auth
       ingress pipeline) and return the per-workspace session.
    2. Fall back to the legacy single ``app.state.session`` for backwards
       compatibility with single-tenant deployments.
    """
    from .workspace_registry import WorkspaceSessionRegistry

    registry: Optional[WorkspaceSessionRegistry] = getattr(
        request.app.state, "workspace_registry", None
    )

    if registry is not None:
        # Resolve active workspace from the identity injected by get_current_identity.
        identity: Optional[RequestContext] = getattr(request.state, "identity", None)
        ws_id = "default"
        if identity is not None:
            ws_id = identity.current_workspace or "default"
        else:
            # Fallback: read workspace from request headers/query directly
            ws_id = (
                request.headers.get("X-Workspace-ID")
                or request.query_params.get("workspace")
                or "default"
            )
        try:
            return registry.get(ws_id)
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Workspace session registry is shut down.",
            )

    # Legacy path: single global session
    if not hasattr(request.app.state, "session") or request.app.state.session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GraphSession not initialized."
        )
    return request.app.state.session


def get_workspace_session(required_role: str = "Viewer"):
    """Dependency factory returning a ``GraphSession`` with RBAC enforcement.

    The caller must have at least *required_role* on the target workspace;
    otherwise an HTTP 403 is raised.
    """

    def _resolve(
        request: Request,
        identity: RequestContext = Depends(get_current_identity),
    ) -> GraphSession:
        ws_id = identity.current_workspace or "default"
        if not identity.has_workspace_access(ws_id, required_role=required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: required role '{required_role}' on workspace '{ws_id}'.",
            )
        return get_session(request)

    return _resolve


def get_markdown_resources(request: Request) -> MarkdownResourceRegistry:
    """Retrieve the Markdown resource registry stored on ``app.state``."""
    resources = getattr(request.app.state, "markdown_resources", None)
    if resources is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Markdown resources are not initialized.",
        )
    return resources


def get_agent_memory(request: Request) -> AgentMemory:
    """Retrieve the optional AgentMemory configured for Explorer."""
    memory = getattr(request.app.state, "agent_memory", None)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AgentMemory is not configured for this Explorer instance.",
        )
    return memory


__all__ = [
    "RequestContext",
    "anonymous_access_allowed",
    "get_agent_memory",
    "get_auth_store",
    "get_current_identity",
    "get_expected_api_key",
    "get_markdown_resources",
    "get_session",
    "get_workspace_session",
    "is_auth_configured",
    "is_valid_api_key",
    "require_auth",
    "require_workspace_role",
]
