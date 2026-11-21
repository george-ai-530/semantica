"""
Authentication REST API Routes.

Exposes endpoints for user authentication and session management:
  - POST /api/auth/login: Dual authentication against corporate Active Directory
    (LDAP 389) for enterprise employees, and local password verification for
    external guest users. Issues signed HMAC-SHA256 JWT bearer tokens.
  - GET /api/auth/me: Retrieve caller identity and workspace context from JWT bearer token.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .crypto import verify_password
from .dependencies import get_current_identity, require_auth
from .ldap import (
    LDAPClientProtocol,
    get_ldap_client_dependency,
)
from .models import RequestContext
from .store import AuthStore, get_auth_store
from .tokens import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Payload for user authentication."""

    username: str = Field(..., description="AD sAMAccountName or local guest username")
    password: str = Field(..., description="User password")
    login_type: Optional[str] = Field(
        None,
        description="Explicit auth provider: 'ad', 'local', or None for auto-detection",
    )
    domain: Optional[str] = Field(None, description="Optional AD domain override")


class LoginResponse(BaseModel):
    """Successful authentication response containing JWT bearer token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 7200
    user: Dict[str, Any]


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    ldap_client: LDAPClientProtocol = Depends(get_ldap_client_dependency),
):
    """Authenticate internal employee via AD LDAP (Port 389) or external guest via AuthStore.

    Validates credentials and issues a signed HMAC-SHA256 JWT access token carrying
    identity claims (sub, type, groups, exp).

    - For domain employees: Binds against AD over Port 389, queries and normalizes
      memberOf groups, caches/syncs user profile into AuthStore, and issues token
      with type='ad'.
    - For external guests: Validates against local salted password hash in AuthStore,
      strictly enforces account expiration (expires_at in the future), and issues
      token with type='local'.
    """
    username = credentials.username.strip()
    password = credentials.password
    login_type = (credentials.login_type or "").strip().lower() or None
    client_ip = request.client.host if request.client else "unknown"

    if not username or not password:
        logger.warning(
            "auth_login_failed_missing_credentials: empty username or password from %s",
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )

    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    existing_user = store.get_user_by_username(username) if store else None

    # Check whether caller targets local external guest account
    should_try_local = False
    if login_type in ("local", "guest"):
        should_try_local = True
    elif (
        login_type is None
        and existing_user is not None
        and existing_user.user_type in ("local", "guest")
        and existing_user.password_hash is not None
    ):
        should_try_local = True

    # -------------------------------------------------------------------------
    # Track 1: Local External Guest User Authentication
    # -------------------------------------------------------------------------
    if should_try_local:
        if not existing_user or not existing_user.password_hash:
            logger.warning(
                "auth_login_failed_unknown_local: user '%s' from %s",
                username,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )

        if not existing_user.is_active:
            logger.warning(
                "auth_login_failed_inactive: user '%s' from %s",
                username,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated.",
            )

        # Strictly validate that account is not expired
        if existing_user.is_expired():
            logger.warning(
                "auth_login_failed_expired: user '%s' expired at %s from %s",
                username,
                existing_user.expires_at,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account has expired.",
            )

        # Verify password hash
        if not verify_password(password, existing_user.password_hash):
            logger.warning(
                "auth_login_failed_bad_password: user '%s' from %s",
                username,
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )

        user_id = existing_user.id
        global_role = existing_user.global_role
        local_groups = store.get_user_groups(user_id) if store else []
        group_names = [g.name for g in local_groups]

        workspace_roles = (
            store.get_user_workspace_roles(user_id, group_names)
            if store
            else {}
        )
        authorized_workspaces = list(workspace_roles.keys()) or ["default"]

        token_payload = {
            "sub": existing_user.username,
            "user_id": user_id,
            "username": existing_user.username,
            "type": "local",
            "groups": group_names,
            "role": global_role,
            "roles": [global_role],
            "workspaces": authorized_workspaces,
            "workspace_roles": workspace_roles,
            "email": existing_user.email,
            "display_name": existing_user.display_name,
        }
        token = create_access_token(token_payload, expires_delta_seconds=7200)

        logger.info(
            "auth_login_success_local: user '%s' id=%s from %s",
            username,
            user_id,
            client_ip,
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 7200,
            "user": {
                "id": user_id,
                "username": existing_user.username,
                "display_name": existing_user.display_name,
                "email": existing_user.email,
                "type": "local",
                "global_role": global_role,
                "groups": group_names,
                "authorized_workspaces": authorized_workspaces,
                "workspace_roles": workspace_roles,
            },
        }

    # -------------------------------------------------------------------------
    # Track 2: Active Directory LDAP (Port 389) Direct Bind
    # -------------------------------------------------------------------------
    ldap_user = None
    try:
        ldap_user = await ldap_client.authenticate(username, password)
    except Exception as exc:
        logger.warning(
            "auth_ldap_bind_exception: user '%s' from %s: %s",
            username,
            client_ip,
            exc,
        )
        ldap_user = None

    if not ldap_user:
        # Fallback check for local store if login_type was unspecified
        if login_type is None and existing_user and existing_user.password_hash:
            if not existing_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated.",
                )
            if existing_user.is_expired():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account has expired.",
                )
            if verify_password(password, existing_user.password_hash):
                user_id = existing_user.id
                global_role = existing_user.global_role
                local_groups = store.get_user_groups(user_id) if store else []
                group_names = [g.name for g in local_groups]
                workspace_roles = (
                    store.get_user_workspace_roles(user_id, group_names)
                    if store
                    else {}
                )
                authorized_workspaces = list(workspace_roles.keys()) or ["default"]
                token_payload = {
                    "sub": existing_user.username,
                    "user_id": user_id,
                    "username": existing_user.username,
                    "type": "local",
                    "groups": group_names,
                    "role": global_role,
                    "roles": [global_role],
                    "workspaces": authorized_workspaces,
                    "workspace_roles": workspace_roles,
                    "email": existing_user.email,
                    "display_name": existing_user.display_name,
                }
                token = create_access_token(token_payload, expires_delta_seconds=7200)
                return {
                    "access_token": token,
                    "token_type": "bearer",
                    "expires_in": 7200,
                    "user": {
                        "id": user_id,
                        "username": existing_user.username,
                        "display_name": existing_user.display_name,
                        "email": existing_user.email,
                        "type": "local",
                        "global_role": global_role,
                        "groups": group_names,
                        "authorized_workspaces": authorized_workspaces,
                        "workspace_roles": workspace_roles,
                    },
                }

        logger.warning(
            "auth_login_failed_invalid_credentials: user '%s' from %s",
            username,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    # Sync / Cache Active Directory profile into AuthStore
    if store:
        existing = store.get_user_by_username(ldap_user.username)
        meta = dict(existing.extra_metadata if existing else {})
        meta["ldap_dn"] = ldap_user.dn
        meta["ldap_groups"] = ldap_user.groups

        # Determine global role: check SEMANTICA_ADMIN_USERS env var
        admin_names = [
            x.strip().lower()
            for x in os.environ.get("SEMANTICA_ADMIN_USERS", "").split(",")
            if x.strip()
        ]
        is_admin = ldap_user.username.lower() in admin_names
        assigned_role = "admin" if is_admin else "user"

        if existing:
            current_role = "admin" if is_admin else existing.global_role
            user = store.update_user(
                user_id=existing.id,
                email=ldap_user.email or existing.email,
                display_name=ldap_user.display_name or existing.display_name,
                global_role=current_role,
                extra_metadata=meta,
            ) or existing
            user_id = user.id
            global_role = current_role
        else:
            user = store.create_user(
                username=ldap_user.username,
                email=ldap_user.email,
                display_name=ldap_user.display_name,
                user_type="ad",
                global_role=assigned_role,
                extra_metadata=meta,
            )
            user_id = user.id
            global_role = assigned_role

        # Refresh AD security group memberships on each interactive login
        current_groups = store.get_user_groups(user_id)
        for g in current_groups:
            if g.group_type == "ad" and g.name not in ldap_user.groups:
                store.remove_user_from_group(g.id, user_id)

        for grp_name in ldap_user.groups:
            g = store.get_group_by_name(grp_name)
            if not g:
                g = store.create_group(name=grp_name, group_type="ad")
            store.add_user_to_group(g.id, user_id)

        workspace_roles = store.get_user_workspace_roles(user_id, ldap_user.groups)
        authorized_workspaces = list(workspace_roles.keys()) or ["default"]
    else:
        user_id = ldap_user.username
        global_role = "user"
        workspace_roles = {"default": "Viewer"}
        authorized_workspaces = ["default"]

    token_payload = {
        "sub": ldap_user.username,
        "user_id": user_id,
        "username": ldap_user.username,
        "type": "ad",
        "groups": ldap_user.groups,
        "role": global_role,
        "roles": [global_role],
        "workspaces": authorized_workspaces,
        "workspace_roles": workspace_roles,
        "email": ldap_user.email,
        "display_name": ldap_user.display_name,
    }
    token = create_access_token(token_payload, expires_delta_seconds=7200)

    logger.info(
        "auth_login_success_ad: user '%s' id=%s groups=%d from %s",
        username,
        user_id,
        len(ldap_user.groups),
        client_ip,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 7200,
        "user": {
            "id": user_id,
            "username": ldap_user.username,
            "display_name": ldap_user.display_name,
            "email": ldap_user.email,
            "type": "ad",
            "global_role": global_role,
            "groups": ldap_user.groups,
            "authorized_workspaces": authorized_workspaces,
            "workspace_roles": workspace_roles,
        },
    }


@router.get("/me")
async def get_current_user_profile(
    identity: RequestContext = Depends(get_current_identity),
):
    """Retrieve caller identity and workspace permissions from validated JWT token."""
    return identity.to_dict()


# -----------------------------------------------------------------------------
# Personal API Key Self-Service Endpoints
# -----------------------------------------------------------------------------


class CreatePersonalApiKeyRequest(BaseModel):
    """Payload for user self-service personal API key creation."""

    name: str = Field(..., description="Human-readable label for the API key")
    allowed_workspaces: Optional[List[str]] = Field(
        None,
        description="Workspaces the key is permitted to access. Must be a subset of user's authorized workspaces.",
    )
    expires_at: Optional[str] = Field(
        None,
        description="Optional ISO 8601 expiration timestamp",
    )


class PersonalApiKeyResponse(BaseModel):
    """API key response with one-time raw secret token."""

    id: str
    name: str
    key_prefix: str
    is_service: bool
    allowed_workspaces: List[str]
    scopes: List[str]
    created_at: str
    expires_at: Optional[str] = None
    raw_key: Optional[str] = Field(
        None,
        description="One-time plaintext API key. Only returned upon creation.",
    )


class ApiKeyListItem(BaseModel):
    """API key metadata without secret material."""

    id: str
    name: str
    key_prefix: str
    is_service: bool
    allowed_workspaces: List[str]
    scopes: List[str]
    is_active: bool
    created_at: str
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    last_used_ip: Optional[str] = None
    revoked_at: Optional[str] = None


@router.post("/keys", response_model=PersonalApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_api_key(
    request: Request,
    payload: CreatePersonalApiKeyRequest,
    identity: RequestContext = Depends(get_current_identity),
):
    """Generate a personal API key strictly inheriting caller's workspace permissions."""
    if identity.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Anonymous callers cannot generate personal API keys.",
        )

    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metadata database store is not configured.",
        )

    # Determine permitted workspaces with strict inheritance
    if identity.global_role == "admin":
        allowed_workspaces = payload.allowed_workspaces or ["*"]
    else:
        user_workspaces = set(identity.authorized_workspaces)
        if "*" in user_workspaces:
            allowed_workspaces = payload.allowed_workspaces or ["*"]
        elif payload.allowed_workspaces is None or "*" in payload.allowed_workspaces:
            allowed_workspaces = list(user_workspaces)
        else:
            unauthorized = [
                ws for ws in payload.allowed_workspaces if ws not in user_workspaces
            ]
            if unauthorized:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot grant workspaces caller is not authorized for: {unauthorized}",
                )
            allowed_workspaces = payload.allowed_workspaces

    key_obj, raw_key = store.create_api_key(
        name=payload.name.strip(),
        user_id=identity.user_id,
        is_service=False,
        scopes=["*"],
        allowed_workspaces=allowed_workspaces,
        expires_at=payload.expires_at,
    )

    logger.info(
        "personal_api_key_created: id=%s name='%s' user_id=%s",
        key_obj.id,
        key_obj.name,
        identity.user_id,
    )

    return PersonalApiKeyResponse(
        id=key_obj.id,
        name=key_obj.name,
        key_prefix=key_obj.key_prefix,
        is_service=key_obj.is_service,
        allowed_workspaces=key_obj.allowed_workspaces,
        scopes=key_obj.scopes,
        created_at=key_obj.created_at,
        expires_at=key_obj.expires_at,
        raw_key=raw_key,
    )


@router.get("/keys", response_model=List[ApiKeyListItem])
async def list_personal_api_keys(
    request: Request,
    identity: RequestContext = Depends(get_current_identity),
):
    """List all personal API keys belonging to the authenticated caller."""
    if identity.is_anonymous:
        return []

    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    if not store:
        return []

    keys = store.list_api_keys(user_id=identity.user_id)
    return [
        ApiKeyListItem(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            is_service=k.is_service,
            allowed_workspaces=k.allowed_workspaces,
            scopes=k.scopes,
            is_active=k.is_active,
            created_at=k.created_at,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
            last_used_ip=k.last_used_ip,
            revoked_at=k.revoked_at,
        )
        for k in keys
    ]


@router.delete("/keys/{key_id}")
async def revoke_personal_api_key(
    key_id: str,
    request: Request,
    identity: RequestContext = Depends(get_current_identity),
):
    """Revoke a personal API key owned by the caller."""
    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metadata database store is not configured.",
        )

    key_obj = store.get_api_key(key_id)
    if not key_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found.",
        )

    if key_obj.user_id != identity.user_id and identity.global_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to revoke this API key.",
        )

    store.revoke_api_key(key_id)
    logger.info("personal_api_key_revoked: id=%s by user=%s", key_id, identity.user_id)
    return {"status": "revoked", "id": key_id}


@router.get("/workspaces")
async def list_user_workspaces(
    request: Request,
    identity: RequestContext = Depends(get_current_identity),
):
    """List workspaces the caller is authorized to access with names and roles."""
    store: Optional[AuthStore] = getattr(
        request.app.state, "auth_store", None
    ) or get_auth_store()

    if not store:
        return [
            {
                "id": "default",
                "name": "Default Workspace",
                "description": "Default global workspace",
                "is_default": True,
                "role": "Admin",
            }
        ]

    all_workspaces = store.list_workspaces()
    if identity.global_role == "admin" or "*" in identity.authorized_workspaces:
        return [
            {
                "id": ws.id,
                "name": ws.name,
                "description": ws.description,
                "is_default": ws.is_default,
                "role": identity.workspace_roles.get(ws.id, "Admin"),
            }
            for ws in all_workspaces
        ]

    user_ws = set(identity.authorized_workspaces)
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "is_default": ws.is_default,
            "role": identity.workspace_roles.get(ws.id, "Viewer"),
        }
        for ws in all_workspaces
        if ws.id in user_ws
    ]
