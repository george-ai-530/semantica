"""
Data models and RequestContext for enterprise authentication and authorization.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class RequestContext:
    """Standardized caller identity context passed to FastAPI route handlers.

    Attributes:
        user_id: Unique identifier of the authenticated user or service.
        username: Human-readable username or key label.
        is_service: True if caller is a machine/service account token.
        authorized_workspaces: List of workspace IDs caller has access to,
            or ``["*"]`` for full access across all workspaces.
        current_workspace: The active workspace targeted by the current request.
        global_role: Global system role ("admin", "user", "viewer", "guest").
        workspace_roles: Mapping of workspace ID to specific granted role
            ("Viewer", "Editor", "Admin").
        groups: AD or local groups the caller belongs to.
        is_anonymous: True if server is in anonymous development mode.
        auth_method: Method used to authenticate ("bearer", "api_key", "legacy", "anonymous").
        api_key_id: Optional ID of the API key used for authentication.
        scopes: API permissions or scopes (e.g. ["*"], ["read"], ["write"]).
        extra: Additional metadata or claims.
    """

    user_id: str
    username: Optional[str] = None
    is_service: bool = False
    authorized_workspaces: List[str] = field(default_factory=list)
    current_workspace: Optional[str] = None
    global_role: str = "user"
    workspace_roles: Dict[str, str] = field(default_factory=dict)
    groups: List[str] = field(default_factory=list)
    is_anonymous: bool = False
    auth_method: str = "api_key"
    api_key_id: Optional[str] = None
    scopes: List[str] = field(default_factory=lambda: ["*"])
    extra: Dict[str, Any] = field(default_factory=dict)

    def has_workspace_access(self, workspace_id: str, required_role: str = "Viewer") -> bool:
        """Check whether the caller is authorized for the given workspace at or above the role level."""
        if self.is_anonymous or self.global_role == "admin":
            return True
        if "*" in self.authorized_workspaces:
            return True
        if workspace_id not in self.authorized_workspaces:
            return False

        role_hierarchy = {"Viewer": 1, "Editor": 2, "Admin": 3}
        req_level = role_hierarchy.get(required_role, 1)
        user_role = self.workspace_roles.get(workspace_id, "Viewer")
        actual_level = role_hierarchy.get(user_role, 0)
        return actual_level >= req_level

    def can_read(self, workspace_id: str) -> bool:
        return self.has_workspace_access(workspace_id, "Viewer")

    def can_write(self, workspace_id: str) -> bool:
        return self.has_workspace_access(workspace_id, "Editor")

    def can_admin(self, workspace_id: str) -> bool:
        return self.has_workspace_access(workspace_id, "Admin")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "is_service": self.is_service,
            "authorized_workspaces": list(self.authorized_workspaces),
            "current_workspace": self.current_workspace,
            "global_role": self.global_role,
            "workspace_roles": dict(self.workspace_roles),
            "groups": list(self.groups),
            "is_anonymous": self.is_anonymous,
            "auth_method": self.auth_method,
            "api_key_id": self.api_key_id,
            "scopes": list(self.scopes),
            "extra": dict(self.extra),
        }


@dataclass
class User:
    """Internal user record stored in metadata database."""

    id: str
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    user_type: str = "local"  # "ad", "local", "service", "guest"
    password_hash: Optional[str] = None
    salt: Optional[str] = None
    is_active: bool = True
    global_role: str = "user"  # "admin", "user", "viewer", "guest"
    expires_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        dt = _parse_iso_datetime(self.expires_at)
        if dt is None:
            return False
        return datetime.now(timezone.utc) > dt


@dataclass
class Workspace:
    """Workspace record for physical and logical graph isolation."""

    id: str
    name: str
    description: Optional[str] = None
    graph_id: str = ""
    is_default: bool = False
    created_by: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Group:
    """Security group mapping AD or local ad-hoc teams."""

    id: str
    name: str
    group_type: str = "local"  # "ad", "local"
    description: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WorkspaceGrant:
    """Access control grant mapping a user or group to a workspace role."""

    id: str
    workspace_id: str
    grantee_type: str  # "user" or "group"
    grantee_id: str
    role: str = "Viewer"  # "Viewer", "Editor", "Admin"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ApiKey:
    """API Key record representing personal or service account credentials."""

    id: str
    name: str
    key_prefix: str
    key_hash: str
    salt: str
    user_id: Optional[str] = None
    is_service: bool = False
    scopes: List[str] = field(default_factory=lambda: ["*"])
    allowed_workspaces: List[str] = field(default_factory=lambda: ["*"])
    is_active: bool = True
    created_at: str = ""
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    last_used_ip: Optional[str] = None
    revoked_at: Optional[str] = None

    def is_expired(self) -> bool:
        dt = _parse_iso_datetime(self.expires_at)
        if dt is None:
            return False
        return datetime.now(timezone.utc) > dt

    def is_valid(self) -> bool:
        return self.is_active and self.revoked_at is None and not self.is_expired()
