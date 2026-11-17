"""
Administrative Governance REST API Routes.

Exposes endpoints for system administrators:
  - /api/admin/users/external: Guest credentials, password management, and account expiry
  - /api/admin/groups: Local ad-hoc groups and membership management
  - /api/admin/workspaces/{id}/grants: Workspace ACL matrices and role mappings
  - /api/admin/keys: Global API key audit inventory, service account provisioning, and instant revocation
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .dependencies import get_current_identity
from .models import RequestContext
from .store import AuthStore, get_auth_store

logger = logging.getLogger(__name__)


def require_admin(
    identity: RequestContext = Depends(get_current_identity),
) -> RequestContext:
    """Dependency enforcing that caller holds the global 'admin' role."""
    if identity.global_role != "admin":
        logger.warning(
            "admin_access_denied: user_id=%s role=%s",
            identity.user_id,
            identity.global_role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required for this endpoint.",
        )
    return identity


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _get_store(request: Request) -> AuthStore:
    store = getattr(request.app.state, "auth_store", None) or get_auth_store()
    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metadata database store is not configured.",
        )
    return store


# =============================================================================
# 1. External Guest Users CRUD (/api/admin/users/external)
# =============================================================================


class CreateExternalUserRequest(BaseModel):
    username: str = Field(..., description="Unique username for the external user")
    password: str = Field(..., description="Initial plaintext password")
    display_name: Optional[str] = Field(None, description="Display name")
    email: Optional[str] = Field(None, description="Email address")
    expires_at: Optional[str] = Field(None, description="Mandatory/optional ISO 8601 expiry timestamp")
    is_active: bool = Field(True, description="Account active state")
    global_role: str = Field("guest", description="System role: 'guest' or 'user'")


class UpdateExternalUserRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    global_role: Optional[str] = None


def _user_to_dict(user) -> Dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "user_type": user.user_type,
        "is_active": user.is_active,
        "global_role": user.global_role,
        "expires_at": user.expires_at,
        "is_expired": user.is_expired(),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@router.post("/users/external", status_code=status.HTTP_201_CREATED)
async def create_external_user(
    request: Request,
    payload: CreateExternalUserRequest,
):
    """Create a new external guest user with password and expiration timestamp."""
    store = _get_store(request)
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )

    if store.get_user_by_username(username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{username}' already exists.",
        )

    user = store.create_user(
        username=username,
        password=payload.password,
        display_name=payload.display_name,
        email=payload.email,
        user_type="guest",
        expires_at=payload.expires_at,
        global_role=payload.global_role,
    )
    logger.info("admin_create_external_user_success: username=%s id=%s", username, user.id)
    return _user_to_dict(user)


@router.get("/users/external")
async def list_external_users(request: Request):
    """List all external guest and local users."""
    store = _get_store(request)
    users = store.list_users()
    external = [u for u in users if u.user_type in ("guest", "local")]
    return [_user_to_dict(u) for u in external]


@router.get("/users/external/{user_id}")
async def get_external_user(user_id: str, request: Request):
    """Retrieve external user details by ID or username."""
    store = _get_store(request)
    user = store.get_user_by_id_or_username(user_id)
    if not user or user.user_type not in ("guest", "local"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External user '{user_id}' not found.",
        )
    return _user_to_dict(user)


@router.put("/users/external/{user_id}")
async def update_external_user(
    user_id: str,
    payload: UpdateExternalUserRequest,
    request: Request,
):
    """Update external user properties (expiry, active toggle, password reset)."""
    store = _get_store(request)
    user = store.get_user_by_id_or_username(user_id)
    if not user or user.user_type not in ("guest", "local"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External user '{user_id}' not found.",
        )

    updated = store.update_user(
        user_id=user.id,
        display_name=payload.display_name,
        email=payload.email,
        expires_at=payload.expires_at,
        is_active=payload.is_active,
        password=payload.password,
        global_role=payload.global_role,
    )
    logger.info("admin_update_external_user: id=%s", user.id)
    return _user_to_dict(updated)


@router.delete("/users/external/{user_id}")
async def delete_external_user(user_id: str, request: Request):
    """Delete an external guest user."""
    store = _get_store(request)
    user = store.get_user_by_id_or_username(user_id)
    if not user or user.user_type not in ("guest", "local"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External user '{user_id}' not found.",
        )

    store.delete_user(user.id)
    logger.info("admin_delete_external_user: id=%s", user.id)
    return {"status": "deleted", "id": user.id}


# =============================================================================
# 2. Local Ad-Hoc Groups (/api/admin/groups)
# =============================================================================


class CreateGroupRequest(BaseModel):
    name: str = Field(..., description="Unique name of the local ad-hoc group")
    description: Optional[str] = Field(None, description="Group description")
    group_type: str = Field("local", description="Group type ('local' or 'ad')")


class GroupMemberRequest(BaseModel):
    user_id: str = Field(..., description="ID or username of the user to add/remove")


def _group_to_dict(group) -> Dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "group_type": group.group_type,
        "description": group.description,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    request: Request,
    payload: CreateGroupRequest,
):
    """Create a new local ad-hoc project group."""
    store = _get_store(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name is required.",
        )

    if store.get_group_by_name(name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group with name '{name}' already exists.",
        )

    group = store.create_group(
        name=name,
        group_type=payload.group_type,
        description=payload.description,
    )
    logger.info("admin_create_group: id=%s name=%s", group.id, group.name)
    return _group_to_dict(group)


@router.get("/groups")
async def list_groups(request: Request):
    """List all registered groups."""
    store = _get_store(request)
    groups = store.list_groups()
    return [_group_to_dict(g) for g in groups]


@router.get("/groups/{group_id}")
async def get_group(group_id: str, request: Request):
    """Retrieve group details and current member users."""
    store = _get_store(request)
    group = store.get_group(group_id) or store.get_group_by_name(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found.",
        )
    members = store.list_group_members(group.id)
    return {
        "group": _group_to_dict(group),
        "members": [_user_to_dict(m) for m in members],
    }


@router.post("/groups/{group_id}/members")
async def add_group_member(
    group_id: str,
    payload: GroupMemberRequest,
    request: Request,
):
    """Add a user to a local group."""
    store = _get_store(request)
    group = store.get_group(group_id) or store.get_group_by_name(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found.",
        )

    user = store.get_user_by_id_or_username(payload.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{payload.user_id}' not found.",
        )

    store.add_user_to_group(group.id, user.id)
    logger.info("admin_group_member_added: group=%s user=%s", group.id, user.id)
    return {"status": "added", "group_id": group.id, "user_id": user.id}


@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_group_member(
    group_id: str,
    user_id: str,
    request: Request,
):
    """Remove a user from a local group."""
    store = _get_store(request)
    group = store.get_group(group_id) or store.get_group_by_name(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found.",
        )

    user = store.get_user_by_id_or_username(user_id)
    target_uid = user.id if user else user_id

    store.remove_user_from_group(group.id, target_uid)
    logger.info("admin_group_member_removed: group=%s user=%s", group.id, target_uid)
    return {"status": "removed", "group_id": group.id, "user_id": target_uid}


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, request: Request):
    """Delete a local group."""
    store = _get_store(request)
    group = store.get_group(group_id) or store.get_group_by_name(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_id}' not found.",
        )

    store.delete_group(group.id)
    logger.info("admin_delete_group: id=%s", group.id)
    return {"status": "deleted", "id": group.id}


# =============================================================================
# 3. Workspace Tenancy & Grants Management (/api/admin/workspaces)
# =============================================================================


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., description="Human-readable workspace name")
    workspace_id: Optional[str] = Field(None, description="Optional custom workspace ID slug")
    description: Optional[str] = Field(None, description="Optional description")


@router.get("/workspaces")
async def list_admin_workspaces(request: Request):
    """List all tenant workspaces in the metadata database."""
    store = _get_store(request)
    workspaces = store.list_workspaces()
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "graph_id": ws.graph_id,
            "is_default": ws.is_default,
            "created_by": ws.created_by,
            "created_at": ws.created_at,
            "updated_at": ws.updated_at,
        }
        for ws in workspaces
    ]


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_admin_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    identity: RequestContext = Depends(require_admin),
):
    """Create a new tenant workspace."""
    store = _get_store(request)
    ws = store.create_workspace(
        name=payload.name.strip(),
        description=payload.description,
        workspace_id=payload.workspace_id.strip() if payload.workspace_id else None,
        created_by=identity.user_id,
    )
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "graph_id": ws.graph_id,
        "is_default": ws.is_default,
        "created_by": ws.created_by,
        "created_at": ws.created_at,
        "updated_at": ws.updated_at,
    }


class CreateGrantRequest(BaseModel):
    grantee_type: str = Field(..., description="'user' or 'group'")
    grantee_id: str = Field(..., description="User ID, Group ID, or AD Security Group Name")
    role: str = Field("Viewer", description="Workspace role: 'Viewer', 'Editor', or 'Admin'")


def _grant_to_dict(grant) -> Dict[str, Any]:
    return {
        "id": grant.id,
        "workspace_id": grant.workspace_id,
        "grantee_type": grant.grantee_type,
        "grantee_id": grant.grantee_id,
        "role": grant.role,
        "created_at": grant.created_at,
        "updated_at": grant.updated_at,
    }


@router.get("/workspaces/{workspace_id}/grants")
async def list_workspace_grants(workspace_id: str, request: Request):
    """List all access control grants for a specific workspace."""
    store = _get_store(request)
    ws = store.get_workspace(workspace_id)
    if not ws:
        created_by = (
            request.state.identity.user_id
            if hasattr(request.state, "identity") and request.state.identity
            else "admin"
        )
        ws = store.create_workspace(
            workspace_id=workspace_id,
            name=workspace_id,
            created_by=created_by,
        )
    grants = store.list_workspace_grants(workspace_id=workspace_id)
    return [_grant_to_dict(g) for g in grants]


@router.post("/workspaces/{workspace_id}/grants", status_code=status.HTTP_201_CREATED)
async def create_workspace_grant(
    workspace_id: str,
    payload: CreateGrantRequest,
    request: Request,
):
    """Assign an AD group or user to a workspace role (Admin, Editor, Viewer)."""
    store = _get_store(request)
    ws = store.get_workspace(workspace_id)
    if not ws:
        created_by = (
            request.state.identity.user_id
            if hasattr(request.state, "identity") and request.state.identity
            else "admin"
        )
        ws = store.create_workspace(
            workspace_id=workspace_id,
            name=workspace_id,
            created_by=created_by,
        )

    grantee_type = payload.grantee_type.lower()
    if grantee_type not in ("user", "group"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="grantee_type must be either 'user' or 'group'.",
        )

    valid_roles = {"Admin", "Editor", "Viewer"}
    # Normalize role capitalizations
    role_norm = next((r for r in valid_roles if r.lower() == payload.role.lower()), None)
    if not role_norm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{payload.role}'. Must be one of: {list(valid_roles)}.",
        )

    grant = store.create_workspace_grant(
        workspace_id=workspace_id,
        grantee_type=grantee_type,
        grantee_id=payload.grantee_id.strip(),
        role=role_norm,
    )
    logger.info(
        "admin_grant_created: ws=%s grantee=%s:%s role=%s",
        workspace_id,
        grantee_type,
        payload.grantee_id,
        role_norm,
    )
    return _grant_to_dict(grant)


@router.delete("/workspaces/{workspace_id}/grants/{grant_id}")
async def delete_workspace_grant(
    workspace_id: str,
    grant_id: str,
    request: Request,
):
    """Revoke/delete an access control grant."""
    store = _get_store(request)
    ws = store.get_workspace(workspace_id)
    if not ws:
        created_by = (
            request.state.identity.user_id
            if hasattr(request.state, "identity") and request.state.identity
            else "admin"
        )
        ws = store.create_workspace(
            workspace_id=workspace_id,
            name=workspace_id,
            created_by=created_by,
        )

    deleted = store.delete_workspace_grant(grant_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Grant '{grant_id}' not found.",
        )
    logger.info("admin_grant_deleted: ws=%s grant=%s", workspace_id, grant_id)
    return {"status": "deleted", "grant_id": grant_id}


# =============================================================================
# 4. Global API Key Inventory & Revocation (/api/admin/keys)
# =============================================================================


class CreateServiceApiKeyRequest(BaseModel):
    name: str = Field(..., description="Service account or token name")
    is_service: bool = Field(True, description="True for machine/service accounts")
    allowed_workspaces: List[str] = Field(default_factory=lambda: ["*"])
    scopes: List[str] = Field(default_factory=lambda: ["*"])
    expires_at: Optional[str] = Field(None, description="Optional ISO timestamp expiration")
    user_id: Optional[str] = Field(None, description="Optional owner user ID")


@router.get("/keys")
async def list_all_api_keys(request: Request):
    """Global inventory of all active and inactive API keys with audit details."""
    store = _get_store(request)
    keys = store.list_api_keys()

    result = []
    for k in keys:
        owner_name = None
        owner_username = None
        if k.user_id:
            u = store.get_user(k.user_id)
            if u:
                owner_name = u.display_name or u.username
                owner_username = u.username

        result.append(
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "user_id": k.user_id,
                "owner_name": owner_name,
                "owner_username": owner_username,
                "is_service": k.is_service,
                "allowed_workspaces": k.allowed_workspaces,
                "scopes": k.scopes,
                "is_active": k.is_active,
                "created_at": k.created_at,
                "expires_at": k.expires_at,
                "is_expired": k.is_expired(),
                "last_used_at": k.last_used_at,
                "last_used_ip": k.last_used_ip,
                "revoked_at": k.revoked_at,
            }
        )
    return result


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_service_api_key(
    request: Request,
    payload: CreateServiceApiKeyRequest,
):
    """Provision a dedicated Service Account API key with explicit workspace scopes."""
    store = _get_store(request)
    key_obj, raw_key = store.create_api_key(
        name=payload.name.strip(),
        user_id=payload.user_id,
        is_service=payload.is_service,
        scopes=payload.scopes,
        allowed_workspaces=payload.allowed_workspaces,
        expires_at=payload.expires_at,
    )
    logger.info(
        "admin_api_key_created: id=%s name=%s is_service=%s",
        key_obj.id,
        key_obj.name,
        key_obj.is_service,
    )
    return {
        "id": key_obj.id,
        "name": key_obj.name,
        "raw_key": raw_key,
        "key_prefix": key_obj.key_prefix,
        "is_service": key_obj.is_service,
        "allowed_workspaces": key_obj.allowed_workspaces,
        "scopes": key_obj.scopes,
        "created_at": key_obj.created_at,
        "expires_at": key_obj.expires_at,
    }


@router.delete("/keys/{key_id}")
async def revoke_api_key_emergency(
    key_id: str,
    request: Request,
):
    """Emergency instant revocation of any API key across the system."""
    store = _get_store(request)
    key_obj = store.get_api_key(key_id)
    if not key_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found.",
        )

    store.revoke_api_key(key_id)
    logger.info("admin_api_key_emergency_revoked: id=%s", key_id)
    return {"status": "revoked", "id": key_id}
