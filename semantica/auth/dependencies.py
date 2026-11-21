"""
FastAPI authentication and authorization dependencies for the Gateway Ingress Pipeline.
"""

import hmac
import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader

from .models import RequestContext
from .store import AuthStore, get_auth_store
from .tokens import TokenError, TokenExpiredError, TokenInvalidError, verify_access_token

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_expected_api_key() -> Optional[str]:
    """Read legacy API key from environment on every call."""
    return os.environ.get("SEMANTICA_API_KEY") or None


def anonymous_access_allowed() -> bool:
    """Check if anonymous development access is enabled."""
    return os.environ.get("SEMANTICA_ALLOW_ANONYMOUS", "").strip().lower() == "true"


def is_auth_configured(store: Optional[AuthStore] = None) -> bool:
    """Return True if any authentication backend (store or legacy key) is configured."""
    if store is not None:
        return True
    return bool(get_expected_api_key())


def is_valid_api_key(
    candidate: Optional[str],
    store: Optional[AuthStore] = None,
    client_ip: Optional[str] = None,
) -> bool:
    """Return True if candidate matches the metadata store, legacy key, or anonymous access."""
    if anonymous_access_allowed():
        return True
    if not candidate:
        return False

    active_store = store or get_auth_store()
    if active_store:
        verified = active_store.verify_api_key(candidate, client_ip=client_ip)
        if verified is not None:
            return True

    expected = get_expected_api_key()
    if expected and hmac.compare_digest(candidate, expected):
        return True

    return False


def get_current_identity(
    request: Request,
    api_key_header: Optional[str] = Security(_api_key_header),
    authorization: Optional[str] = Header(None),
) -> RequestContext:
    """Unified FastAPI dependency extracting Bearer token or X-API-Key.

    Resolves to a standardized RequestContext. Supports:
      1. Anonymous access if SEMANTICA_ALLOW_ANONYMOUS=true
      2. Bearer <jwt> authorization header
      3. X-API-Key (or ?api_key= query parameter) against SQLite metadata store
      4. Fallback to legacy SEMANTICA_API_KEY
      5. Fail-closed HTTP 503 when no authentication is configured
    """
    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    client_ip = request.client.host if request.client else None
    target_workspace = (
        request.headers.get("X-Workspace-ID")
        or request.query_params.get("workspace")
        or "default"
    )

    # 1. Anonymous Access (Development Mode)
    if anonymous_access_allowed():
        context = RequestContext(
            user_id="anonymous",
            username="anonymous",
            is_service=False,
            authorized_workspaces=["*"],
            current_workspace=target_workspace,
            global_role="admin",
            workspace_roles={target_workspace: "Admin", "default": "Admin"},
            is_anonymous=True,
            auth_method="anonymous",
        )
        request.state.identity = context
        return context

    # 2. Bearer Token Verification
    if authorization and authorization.strip().lower().startswith("bearer "):
        token = authorization.strip()[7:].strip()
        try:
            claims = verify_access_token(token)
        except TokenExpiredError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired.",
            )
        except TokenInvalidError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {exc}",
            )
        except TokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed.",
            )

        sub = str(claims.get("sub", ""))
        user = store.get_user(sub) or store.get_user_by_username(sub) if store else None

        if user and (not user.is_active or user.is_expired()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated or expired.",
            )

        groups = claims.get("groups", [])
        workspace_roles = (
            store.get_user_workspace_roles(user.id if user else sub, groups)
            if store
            else {}
        )
        authorized_workspaces = (
            list(workspace_roles.keys())
            or claims.get("workspaces", ["default"])
        )
        global_role = user.global_role if user else claims.get("role", "user")

        has_explicit_ws = bool(
            request.headers.get("X-Workspace-ID") or request.query_params.get("workspace")
        )
        is_workspace_route = not request.url.path.startswith("/api/auth/")

        if (
            (has_explicit_ws or is_workspace_route)
            and "*" not in authorized_workspaces
            and global_role != "admin"
            and target_workspace not in authorized_workspaces
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to workspace '{target_workspace}'.",
            )

        context = RequestContext(
            user_id=user.id if user else sub,
            username=user.username if user else claims.get("username", sub),
            is_service=claims.get("type") == "service",
            authorized_workspaces=authorized_workspaces,
            current_workspace=target_workspace,
            global_role=global_role,
            workspace_roles=workspace_roles,
            groups=groups,
            auth_method="bearer",
            extra=claims,
        )
        request.state.identity = context
        return context

    # 3. API Key Verification (Header or Query Param)
    candidate_key = api_key_header or request.query_params.get("api_key")

    if candidate_key:
        if store:
            verified = store.verify_api_key(candidate_key, client_ip=client_ip)
            if verified is not None:
                api_key_obj, user_obj = verified
                authorized_workspaces, workspace_roles = (
                    store.get_effective_workspaces_for_api_key(api_key_obj)
                )
                global_role = (
                    user_obj.global_role
                    if user_obj
                    else ("admin" if api_key_obj.is_service else "user")
                )
                has_explicit_ws = bool(
                    request.headers.get("X-Workspace-ID") or request.query_params.get("workspace")
                )
                is_workspace_route = not request.url.path.startswith("/api/auth/")

                if (
                    (has_explicit_ws or is_workspace_route)
                    and "*" not in authorized_workspaces
                    and global_role != "admin"
                    and target_workspace not in authorized_workspaces
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied to workspace '{target_workspace}'.",
                    )
                context = RequestContext(
                    user_id=user_obj.id if user_obj else f"service_{api_key_obj.id}",
                    username=user_obj.username if user_obj else api_key_obj.name,
                    is_service=api_key_obj.is_service,
                    authorized_workspaces=authorized_workspaces,
                    current_workspace=target_workspace,
                    global_role=global_role,
                    workspace_roles=workspace_roles,
                    auth_method="api_key",
                    api_key_id=api_key_obj.id,
                    scopes=api_key_obj.scopes,
                )
                request.state.identity = context
                return context

        # 4. Fallback to Legacy SEMANTICA_API_KEY
        expected_legacy = get_expected_api_key()
        if expected_legacy and hmac.compare_digest(candidate_key, expected_legacy):
            context = RequestContext(
                user_id="legacy_api_user",
                username="legacy_admin",
                is_service=True,
                authorized_workspaces=["*"],
                current_workspace=target_workspace,
                global_role="admin",
                workspace_roles={target_workspace: "Admin", "default": "Admin"},
                auth_method="legacy",
            )
            request.state.identity = context
            return context

        # API key provided was invalid
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Send it as the X-API-Key header.",
        )

    # 5. Missing Credentials & Fail-Closed Logic
    if not is_auth_configured(store):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Server is not configured for authentication. Set the "
                "SEMANTICA_API_KEY environment variable, or explicitly opt "
                "into unauthenticated access (development only) with "
                "SEMANTICA_ALLOW_ANONYMOUS=true."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials. Send Authorization: Bearer <token> or X-API-Key header.",
    )


def require_auth(
    identity: RequestContext = Depends(get_current_identity),
) -> RequestContext:
    """Backwards-compatible dependency wrapper returning the resolved RequestContext."""
    return identity


def require_workspace_role(required_role: str = "Viewer"):
    """Dependency factory enforcing workspace-level RBAC on the current workspace."""
    def _guard(
        identity: RequestContext = Depends(get_current_identity),
    ) -> RequestContext:
        target = identity.current_workspace or "default"
        if not identity.has_workspace_access(target, required_role=required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: required role '{required_role}' on workspace '{target}'.",
            )
        return identity

    return _guard
