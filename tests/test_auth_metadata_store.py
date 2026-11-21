"""
Tests for Auth Metadata Store & Gateway Ingress Pipeline (Ticket 01).

Validates:
1. SQLite schema initialization and migrations for auth_users, auth_workspaces,
   auth_groups, auth_workspace_grants, and auth_api_keys.
2. Constant-time API key verification with salted hashes and audit tracking.
3. Personal API key permission inheritance and service account scoping.
4. User password hashing and account expiration validation.
5. Unified FastAPI dependency get_current_identity and require_auth.
6. Multi-workspace context resolution and RBAC role checks.
7. Backwards compatibility with legacy SEMANTICA_API_KEY and anonymous mode.
"""

from datetime import datetime, timedelta, timezone
import pytest

from fastapi import Depends, FastAPI, HTTPException
from starlette.testclient import TestClient

from semantica.auth import (
    ApiKey,
    AuthStore,
    RequestContext,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    get_auth_store,
    get_current_identity,
    hash_password,
    require_auth,
    require_workspace_role,
    set_auth_store,
    verify_access_token,
    verify_password,
)


@pytest.fixture
def store(tmp_path):
    """Provide a fresh, isolated AuthStore instance for each test."""
    db_file = tmp_path / "test_auth.db"
    auth_store = AuthStore(db_file)
    set_auth_store(auth_store)
    yield auth_store
    auth_store.close()
    set_auth_store(None)


@pytest.fixture
def app(store):
    """Provide a test FastAPI application instrumented with auth dependencies."""
    app = FastAPI(title="Auth Gateway Test App")
    app.state.auth_store = store

    @app.get("/api/public")
    async def public_route():
        return {"status": "public_ok"}

    @app.get("/api/protected", dependencies=[Depends(require_auth)])
    async def protected_route(identity: RequestContext = Depends(get_current_identity)):
        return {
            "status": "authenticated",
            "identity": identity.to_dict(),
        }

    @app.post(
        "/api/workspaces/{workspace_id}/edit",
        dependencies=[Depends(require_workspace_role("Editor"))],
    )
    async def workspace_edit_route(
        workspace_id: str,
        identity: RequestContext = Depends(get_current_identity),
    ):
        return {
            "status": "edited",
            "workspace_id": workspace_id,
            "user_id": identity.user_id,
        }

    return app


@pytest.fixture
def client(app, monkeypatch):
    """Provide TestClient with clean environment variables."""
    monkeypatch.delenv("SEMANTICA_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. Database Schema & Migration Tests
# =============================================================================

def test_schema_initialization(store):
    """Verify that all required tables and default workspace are initialized."""
    cursor = store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "auth_schema_migrations",
        "auth_users",
        "auth_workspaces",
        "auth_groups",
        "auth_group_members",
        "auth_workspace_grants",
        "auth_api_keys",
    }
    assert expected_tables.issubset(tables)

    # Verify default workspace
    default_ws = store.get_default_workspace()
    assert default_ws is not None
    assert default_ws.id == "default"
    assert default_ws.is_default is True


# =============================================================================
# 2. User CRUD, Password Verification & Expiry Tests
# =============================================================================

def test_user_password_hashing_and_verification(store):
    """Verify password hashing with salt and constant-time verification."""
    user = store.create_user(
        username="alice",
        email="alice@corp.example",
        display_name="Alice Specialist",
        password="SecretPassword123!",
    )
    assert user.id.startswith("usr_")
    assert user.username == "alice"
    assert user.password_hash is not None
    assert user.password_hash.startswith("pbkdf2_sha256$")

    # Correct credentials
    verified = store.verify_user_password("alice", "SecretPassword123!")
    assert verified is not None
    assert verified.id == user.id

    # Wrong credentials
    assert store.verify_user_password("alice", "WrongPassword") is None
    assert store.verify_user_password("nonexistent", "SecretPassword123!") is None


def test_user_account_expiration(store):
    """Verify that expired guest accounts are rejected even with correct password."""
    past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future_date = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    expired_user = store.create_user(
        username="guest_expired",
        password="GuestPassword1!",
        user_type="guest",
        expires_at=past_date,
    )
    active_guest = store.create_user(
        username="guest_valid",
        password="GuestPassword1!",
        user_type="guest",
        expires_at=future_date,
    )

    assert expired_user.is_expired() is True
    assert active_guest.is_expired() is False

    # Password check refuses expired accounts
    assert store.verify_user_password("guest_expired", "GuestPassword1!") is None
    assert store.verify_user_password("guest_valid", "GuestPassword1!") is not None


def test_user_deactivation(store):
    """Verify that deactivated users are rejected."""
    user = store.create_user(
        username="charlie",
        password="ValidPassword!",
    )
    assert store.verify_user_password("charlie", "ValidPassword!") is not None

    store.update_user(user.id, is_active=False)
    assert store.verify_user_password("charlie", "ValidPassword!") is None


# =============================================================================
# 3. Workspace & Group Management Tests
# =============================================================================

def test_workspace_crud(store):
    """Verify workspace creation and restriction on deleting default workspace."""
    ws = store.create_workspace(
        name="Engineering",
        description="Core dev workspace",
    )
    assert ws.id.startswith("ws_")
    assert ws.name == "Engineering"
    assert ws.graph_id == f"graph:{ws.id}"

    # Default workspace deletion must be refused
    assert store.delete_workspace("default") is False

    # Custom workspace can be deleted
    assert store.delete_workspace(ws.id) is True
    assert store.get_workspace(ws.id) is None


def test_group_and_membership_crud(store):
    """Verify group creation and user membership management."""
    grp = store.create_group(name="CN=Finance-Team", group_type="ad")
    user = store.create_user(username="bob")

    assert store.add_user_to_group(grp.id, user.id) is True
    user_groups = store.get_user_groups(user.id)
    assert len(user_groups) == 1
    assert user_groups[0].name == "CN=Finance-Team"

    members = store.list_group_members(grp.id)
    assert len(members) == 1
    assert members[0].id == user.id

    assert store.remove_user_from_group(grp.id, user.id) is True
    assert len(store.get_user_groups(user.id)) == 0


# =============================================================================
# 4. Workspace Grants & Role Hierarchy Resolution Tests
# =============================================================================

def test_workspace_grants_and_role_inheritance(store):
    """Verify role resolution combining user grants and group grants (Admin > Editor > Viewer)."""
    ws1 = store.create_workspace(name="Finance")
    ws2 = store.create_workspace(name="Legal")
    ws3 = store.create_workspace(name="Public")

    user = store.create_user(username="dana")
    grp = store.create_group(name="Finance-Admins")
    store.add_user_to_group(grp.id, user.id)

    # User has Viewer on Legal directly
    store.create_workspace_grant(ws2.id, grantee_type="user", grantee_id=user.id, role="Viewer")

    # Group has Editor on Legal and Admin on Finance
    store.create_workspace_grant(ws2.id, grantee_type="group", grantee_id=grp.id, role="Editor")
    store.create_workspace_grant(ws1.id, grantee_type="group", grantee_id=grp.id, role="Admin")

    # Dynamically passed AD group has Viewer on Public
    store.create_workspace_grant(ws3.id, grantee_type="group", grantee_id="CN=Corporate-All", role="Viewer")

    roles = store.get_user_workspace_roles(user.id, ad_groups=["CN=Corporate-All"])
    # ws1: Admin from Finance-Admins group
    assert roles[ws1.id] == "Admin"
    # ws2: max(Viewer from user, Editor from group) == Editor
    assert roles[ws2.id] == "Editor"
    # ws3: Viewer from AD group CN=Corporate-All
    assert roles[ws3.id] == "Viewer"


# =============================================================================
# 5. API Key Verification, Audit & Permissions Tests
# =============================================================================

def test_api_key_creation_and_constant_time_verification(store):
    """Verify API key generation, salted hash storage, constant-time verification and audit tracking."""
    key_obj, raw_key = store.create_api_key(
        name="ETL Pipeline Key",
        is_service=True,
        allowed_workspaces=["default"],
    )
    assert raw_key.startswith("sem_live_")
    assert key_obj.key_prefix == raw_key[:12]
    assert key_obj.key_hash != raw_key
    assert key_obj.is_service is True
    assert key_obj.last_used_at is None

    # Verification success with client IP tracking
    verified = store.verify_api_key(raw_key, client_ip="192.168.1.100")
    assert verified is not None
    verified_key, verified_user = verified
    assert verified_key.id == key_obj.id
    assert verified_user is None
    assert verified_key.last_used_ip == "192.168.1.100"
    assert verified_key.last_used_at is not None

    # Invalid key verification fails
    assert store.verify_api_key("sem_live_invalidkey1234567890") is None


def test_api_key_revocation_and_expiration(store):
    """Verify that revoked or expired API keys are immediately rejected."""
    key1, raw1 = store.create_api_key(name="Revoke Me")
    assert store.verify_api_key(raw1) is not None

    # Instant revocation
    assert store.revoke_api_key(key1.id) is True
    assert store.verify_api_key(raw1) is None

    # Expired key
    past_date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    key2, raw2 = store.create_api_key(name="Expired Key", expires_at=past_date)
    assert store.verify_api_key(raw2) is None


def test_personal_api_key_permission_inheritance(store):
    """Personal API keys must strictly inherit permissions from their user owner."""
    ws = store.create_workspace(name="DevWS")
    user = store.create_user(username="elena")
    store.create_workspace_grant(ws.id, grantee_type="user", grantee_id=user.id, role="Editor")

    # Elena creates a personal API key
    key_obj, _ = store.create_api_key(
        name="Elena Personal Token",
        user_id=user.id,
        is_service=False,
        allowed_workspaces=["*"],
    )

    workspaces, roles = store.get_effective_workspaces_for_api_key(key_obj)
    assert ws.id in workspaces
    assert roles[ws.id] == "Editor"

    # If key scopes allowed_workspaces down to something user does not have:
    restricted_key, _ = store.create_api_key(
        name="Restricted Token",
        user_id=user.id,
        is_service=False,
        allowed_workspaces=["ws_unauthorized"],
    )
    workspaces2, roles2 = store.get_effective_workspaces_for_api_key(restricted_key)
    assert len(workspaces2) == 0
    assert len(roles2) == 0


# =============================================================================
# 6. JWT Token Issuance & Verification Tests
# =============================================================================

def test_jwt_token_flow():
    """Verify RFC 7519 JWT creation and claims decoding."""
    claims = {
        "sub": "alice",
        "type": "ad",
        "groups": ["CN=Engineering", "CN=Staff"],
        "workspaces": ["ws_eng"],
        "role": "user",
    }
    token = create_access_token(claims, expires_delta_seconds=3600)
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    decoded = verify_access_token(token)
    assert decoded["sub"] == "alice"
    assert decoded["groups"] == ["CN=Engineering", "CN=Staff"]
    assert decoded["role"] == "user"


def test_jwt_token_expiration():
    """Verify expired JWT tokens raise TokenExpiredError."""
    claims = {"sub": "alice"}
    token = create_access_token(claims, expires_delta_seconds=-10)
    with pytest.raises(TokenExpiredError):
        verify_access_token(token)


def test_jwt_token_tampering():
    """Verify tampered JWT tokens raise TokenInvalidError."""
    token = create_access_token({"sub": "alice"})
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.badsignature"
    with pytest.raises(TokenInvalidError):
        verify_access_token(tampered)


# =============================================================================
# 7. Gateway Ingress Pipeline HTTP Tests via TestClient
# =============================================================================

def test_http_fail_closed_when_auth_unconfigured(client, monkeypatch):
    """When no auth backend and no legacy key is set, requests fail closed with 503."""
    monkeypatch.delenv("SEMANTICA_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    client.app.state.auth_store = None
    set_auth_store(None)

    resp = client.get("/api/protected")
    assert resp.status_code == 503


def test_http_public_routes_accessible_without_auth(client, monkeypatch):
    """Public health/info routes remain accessible without credentials."""
    client.app.state.auth_store = None
    set_auth_store(None)

    resp = client.get("/api/public")
    assert resp.status_code == 200
    assert resp.json() == {"status": "public_ok"}


def test_http_api_key_authentication_success(client, store):
    """Valid X-API-Key authenticates and populates standardized RequestContext."""
    key_obj, raw_key = store.create_api_key(name="Test Machine Key", is_service=True)

    resp = client.get(
        "/api/protected",
        headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_marketing"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "authenticated"
    identity = data["identity"]
    assert identity["is_service"] is True
    assert identity["auth_method"] == "api_key"
    assert identity["api_key_id"] == key_obj.id
    assert identity["current_workspace"] == "ws_marketing"

    # Audit trail verification
    refreshed_key = store.get_api_key(key_obj.id)
    assert refreshed_key.last_used_at is not None


def test_http_api_key_query_param_accepted(client, store):
    """API key passed via query parameter (e.g. for WebSocket clients) is accepted."""
    _, raw_key = store.create_api_key(name="Query Param Key", is_service=True)

    resp = client.get(f"/api/protected?api_key={raw_key}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "authenticated"


def test_http_invalid_or_revoked_api_key_rejected(client, store):
    """Invalid or revoked API key returns HTTP 401."""
    key_obj, raw_key = store.create_api_key(name="Revoke HTTP")
    store.revoke_api_key(key_obj.id)

    # Revoked key
    resp1 = client.get("/api/protected", headers={"X-API-Key": raw_key})
    assert resp1.status_code == 401

    # Completely wrong key
    resp2 = client.get("/api/protected", headers={"X-API-Key": "sem_live_bogus_key"})
    assert resp2.status_code == 401


def test_http_bearer_token_authentication(client, store):
    """Valid JWT bearer token authenticates and maps workspace roles."""
    ws = store.create_workspace(name="Engineering")
    user = store.create_user(username="frank")
    store.create_workspace_grant(ws.id, grantee_type="user", grantee_id=user.id, role="Editor")

    token = create_access_token({
        "sub": user.id,
        "username": user.username,
        "type": "ad",
        "role": "user",
    })

    resp = client.get(
        "/api/protected",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-ID": ws.id,
        },
    )
    assert resp.status_code == 200
    identity = resp.json()["identity"]
    assert identity["user_id"] == user.id
    assert identity["username"] == "frank"
    assert identity["auth_method"] == "bearer"
    assert identity["workspace_roles"][ws.id] == "Editor"


def test_http_expired_bearer_token_rejected(client):
    """Expired JWT token returns HTTP 401."""
    expired_token = create_access_token({"sub": "frank"}, expires_delta_seconds=-60)
    resp = client.get(
        "/api/protected",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_http_legacy_mode_fallback(client, monkeypatch):
    """Standalone fallback to legacy SEMANTICA_API_KEY when key is not in store."""
    monkeypatch.setenv("SEMANTICA_API_KEY", "legacy-master-key")

    resp = client.get(
        "/api/protected",
        headers={"X-API-Key": "legacy-master-key"},
    )
    assert resp.status_code == 200
    identity = resp.json()["identity"]
    assert identity["auth_method"] == "legacy"
    assert identity["global_role"] == "admin"
    assert "*" in identity["authorized_workspaces"]


def test_http_anonymous_mode_fallback(client, monkeypatch):
    """Development fallback to SEMANTICA_ALLOW_ANONYMOUS=true."""
    monkeypatch.setenv("SEMANTICA_ALLOW_ANONYMOUS", "true")

    resp = client.get("/api/protected")
    assert resp.status_code == 200
    identity = resp.json()["identity"]
    assert identity["is_anonymous"] is True
    assert identity["auth_method"] == "anonymous"
    assert identity["global_role"] == "admin"


def test_http_workspace_rbac_enforcement(client, store):
    """Test require_workspace_role dependency guard: Editor role required."""
    ws = store.create_workspace(name="Secured Workspace")
    editor_user = store.create_user(username="editor_user")
    viewer_user = store.create_user(username="viewer_user")

    store.create_workspace_grant(ws.id, grantee_type="user", grantee_id=editor_user.id, role="Editor")
    store.create_workspace_grant(ws.id, grantee_type="user", grantee_id=viewer_user.id, role="Viewer")

    editor_token = create_access_token({"sub": editor_user.id})
    viewer_token = create_access_token({"sub": viewer_user.id})

    # Editor succeeds (HTTP 200)
    resp_editor = client.post(
        f"/api/workspaces/{ws.id}/edit",
        headers={
            "Authorization": f"Bearer {editor_token}",
            "X-Workspace-ID": ws.id,
        },
    )
    assert resp_editor.status_code == 200
    assert resp_editor.json()["status"] == "edited"

    # Viewer is denied (HTTP 403 Forbidden)
    resp_viewer = client.post(
        f"/api/workspaces/{ws.id}/edit",
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-Workspace-ID": ws.id,
        },
    )
    assert resp_viewer.status_code == 403
    assert "access denied" in resp_viewer.json()["detail"].lower()
