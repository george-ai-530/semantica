"""
Comprehensive tests for Personal API Key Self-Service & Admin Management REST APIs (Ticket 05).

Covers:
1. User self-service API key generation, listing, and revocation (/api/auth/keys)
   with strict permission inheritance.
2. Route protection: Non-admins blocked with HTTP 403 from /api/admin/...
3. External guest users CRUD, password management, and account expiration (/api/admin/users/external).
4. Local ad-hoc groups CRUD and membership management (/api/admin/groups).
5. Workspace ACL matrices and role mappings (/api/admin/workspaces/{id}/grants).
6. Global API key inventory audit and emergency instant key revocation (/api/admin/keys).
"""

from datetime import datetime, timedelta, timezone
import pytest

from starlette.testclient import TestClient

from semantica.auth import (
    AuthStore,
    create_access_token,
    set_auth_store,
)
from semantica.explorer.app import create_app
from semantica.explorer.session import GraphSession
from semantica.context.context_graph import ContextGraph


@pytest.fixture
def auth_store(tmp_path):
    """Provide isolated AuthStore in temp directory."""
    db_file = tmp_path / "test_admin_auth.db"
    store = AuthStore(db_file)
    set_auth_store(store)
    yield store
    store.close()
    set_auth_store(None)


@pytest.fixture
def app(auth_store):
    """Create test Explorer FastAPI app wired with test AuthStore."""
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node("node1", node_type="concept", content="Test Concept")
    session = GraphSession(graph)
    app_instance = create_app(session=session, auth_store=auth_store)
    return app_instance


@pytest.fixture
def client(app, monkeypatch):
    """Provide TestClient with clean environment."""
    monkeypatch.delenv("SEMANTICA_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_credentials(auth_store):
    """Create a global admin user and return token and user object."""
    admin_user = auth_store.create_user(
        username="admin_boss",
        password="AdminSecretPassword123!",
        is_admin=True,
        global_role="admin",
    )
    token = create_access_token({
        "sub": admin_user.id,
        "username": admin_user.username,
        "role": "admin",
        "workspaces": ["*"],
    })
    return {"user": admin_user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def standard_user(auth_store):
    """Create a regular employee with access only to ws_engineering."""
    ws = auth_store.create_workspace(name="Engineering", workspace_id="ws_eng")
    user = auth_store.create_user(
        username="dev_alice",
        password="AlicePassword123!",
        global_role="user",
    )
    auth_store.create_workspace_grant(ws.id, grantee_type="user", grantee_id=user.id, role="Editor")
    token = create_access_token({
        "sub": user.id,
        "username": user.username,
        "role": "user",
        "workspaces": ["ws_eng"],
    })
    return {
        "user": user,
        "workspace": ws,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# =============================================================================
# 1. Personal API Key Self-Service (/api/auth/keys)
# =============================================================================


def test_user_can_generate_personal_api_key_with_strict_inheritance(client, standard_user):
    """Regular user can generate personal API key inheriting permitted workspaces."""
    headers = standard_user["headers"]

    # 1. Generate key requesting permitted workspace
    resp = client.post(
        "/api/auth/keys",
        headers=headers,
        json={
            "name": "Alice Cursor Key",
            "allowed_workspaces": ["ws_eng"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alice Cursor Key"
    assert data["allowed_workspaces"] == ["ws_eng"]
    assert data["is_service"] is False
    assert "raw_key" in data
    assert data["raw_key"].startswith("sem_live_")
    raw_key = data["raw_key"]

    # 2. Test authenticating with the new personal key
    auth_resp = client.get("/api/auth/me", headers={"X-API-Key": raw_key})
    assert auth_resp.status_code == 200
    me_data = auth_resp.json()
    assert me_data["user_id"] == standard_user["user"].id
    assert "ws_eng" in me_data["authorized_workspaces"]


def test_personal_key_cannot_exceed_user_permissions(client, standard_user):
    """User cannot create personal API key granting workspaces they do not possess."""
    headers = standard_user["headers"]

    # User attempts to grant access to unauthorized workspace 'ws_finance'
    resp = client.post(
        "/api/auth/keys",
        headers=headers,
        json={
            "name": "Escalation Key",
            "allowed_workspaces": ["ws_eng", "ws_finance"],
        },
    )
    assert resp.status_code == 403
    assert "ws_finance" in resp.json()["detail"]


def test_personal_key_listing_and_revocation(client, standard_user, auth_store):
    """User can list their own keys and revoke them; cannot revoke other's keys."""
    headers = standard_user["headers"]

    # Create key 1
    resp1 = client.post(
        "/api/auth/keys",
        headers=headers,
        json={"name": "Key One"},
    )
    key1 = resp1.json()

    # Create key 2 for another user
    other_user = auth_store.create_user(username="other_bob")
    other_key_obj, _ = auth_store.create_api_key(name="Bob Key", user_id=other_user.id)

    # List keys - should only see Alice's keys
    list_resp = client.get("/api/auth/keys", headers=headers)
    assert list_resp.status_code == 200
    keys = list_resp.json()
    key_ids = [k["id"] for k in keys]
    assert key1["id"] in key_ids
    assert other_key_obj.id not in key_ids
    assert "raw_key" not in keys[0]

    # Attempt to revoke Bob's key -> 403 Forbidden
    del_other = client.delete(f"/api/auth/keys/{other_key_obj.id}", headers=headers)
    assert del_other.status_code == 403

    # Revoke Key One -> 200 OK
    del_resp = client.delete(f"/api/auth/keys/{key1['id']}", headers=headers)
    assert del_resp.status_code == 200

    # Test that revoked key is now rejected
    test_auth = client.get("/api/auth/me", headers={"X-API-Key": key1["raw_key"]})
    assert test_auth.status_code == 401


# =============================================================================
# 2. Admin Route Protection & RBAC Guard
# =============================================================================


def test_admin_routes_reject_non_admin_users(client, standard_user):
    """Non-admin users receive HTTP 403 Forbidden on all /api/admin endpoints."""
    headers = standard_user["headers"]

    endpoints = [
        ("GET", "/api/admin/users/external"),
        ("POST", "/api/admin/users/external"),
        ("GET", "/api/admin/groups"),
        ("POST", "/api/admin/groups"),
        ("GET", "/api/admin/keys"),
        ("POST", "/api/admin/keys"),
    ]

    for method, path in endpoints:
        if method == "GET":
            resp = client.get(path, headers=headers)
        else:
            resp = client.post(path, headers=headers, json={"name": "test"})
        assert resp.status_code == 403, f"{method} {path} should return 403 for regular user"
        assert "admin" in resp.json()["detail"].lower()


# =============================================================================
# 3. External Guest Users CRUD (/api/admin/users/external)
# =============================================================================


def test_external_guest_user_lifecycle(client, admin_credentials):
    """Admin can create, list, inspect, update, and delete guest users."""
    headers = admin_credentials["headers"]
    future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    # 1. Create external guest user
    create_resp = client.post(
        "/api/admin/users/external",
        headers=headers,
        json={
            "username": "contractor_claire",
            "password": "ClairePassword123!",
            "display_name": "Claire Consultant",
            "email": "claire@consulting.example",
            "expires_at": future_date,
            "global_role": "guest",
        },
    )
    assert create_resp.status_code == 201
    user_data = create_resp.json()
    assert user_data["username"] == "contractor_claire"
    assert user_data["user_type"] == "guest"
    assert user_data["is_expired"] is False
    user_id = user_data["id"]

    # 2. Reject duplicate username
    dup_resp = client.post(
        "/api/admin/users/external",
        headers=headers,
        json={
            "username": "contractor_claire",
            "password": "AnotherPassword!",
        },
    )
    assert dup_resp.status_code == 409

    # 3. Retrieve user by ID
    get_resp = client.get(f"/api/admin/users/external/{user_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["display_name"] == "Claire Consultant"

    # 4. Update user (update expiry and display name)
    past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    update_resp = client.put(
        f"/api/admin/users/external/{user_id}",
        headers=headers,
        json={
            "display_name": "Claire Senior Consultant",
            "expires_at": past_date,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["display_name"] == "Claire Senior Consultant"
    assert update_resp.json()["is_expired"] is True

    # 5. Login check: expired guest cannot log in
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "contractor_claire", "password": "ClairePassword123!"},
    )
    assert login_resp.status_code == 401
    assert "expired" in login_resp.json()["detail"].lower()

    # 6. Delete user
    del_resp = client.delete(f"/api/admin/users/external/{user_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 7. Fetch after delete -> 404
    get_after = client.get(f"/api/admin/users/external/{user_id}", headers=headers)
    assert get_after.status_code == 404


# =============================================================================
# 4. Local Ad-Hoc Groups (/api/admin/groups)
# =============================================================================


def test_admin_group_and_membership_management(client, admin_credentials, auth_store):
    """Admin can create groups, add/remove members, and delete groups."""
    headers = admin_credentials["headers"]
    member_user = auth_store.create_user(username="member_dave")

    # 1. Create group
    create_grp = client.post(
        "/api/admin/groups",
        headers=headers,
        json={
            "name": "Audit-Taskforce",
            "description": "Ad-hoc taskforce for 2026 security audit",
            "group_type": "local",
        },
    )
    assert create_grp.status_code == 201
    grp = create_grp.json()
    assert grp["name"] == "Audit-Taskforce"
    group_id = grp["id"]

    # 2. Add member
    add_mem = client.post(
        f"/api/admin/groups/{group_id}/members",
        headers=headers,
        json={"user_id": member_user.id},
    )
    assert add_mem.status_code == 200
    assert add_mem.json()["status"] == "added"

    # 3. Get group with members
    get_grp = client.get(f"/api/admin/groups/{group_id}", headers=headers)
    assert get_grp.status_code == 200
    data = get_grp.json()
    assert len(data["members"]) == 1
    assert data["members"][0]["username"] == "member_dave"

    # 4. Remove member
    rem_mem = client.delete(f"/api/admin/groups/{group_id}/members/{member_user.id}", headers=headers)
    assert rem_mem.status_code == 200
    assert rem_mem.json()["status"] == "removed"

    # 5. Delete group
    del_grp = client.delete(f"/api/admin/groups/{group_id}", headers=headers)
    assert del_grp.status_code == 200
    assert del_grp.json()["status"] == "deleted"


# =============================================================================
# 5. Workspace ACL Grants (/api/admin/workspaces/{id}/grants)
# =============================================================================


def test_workspace_grant_role_assignment(client, admin_credentials, auth_store):
    """Admin can assign users and AD groups to workspace roles and list/delete them."""
    headers = admin_credentials["headers"]
    ws = auth_store.create_workspace(name="Compliance", workspace_id="ws_comp")
    target_user = auth_store.create_user(username="compliance_officer")

    # 1. Create grant for user
    user_grant_resp = client.post(
        f"/api/admin/workspaces/{ws.id}/grants",
        headers=headers,
        json={
            "grantee_type": "user",
            "grantee_id": target_user.id,
            "role": "Admin",
        },
    )
    assert user_grant_resp.status_code == 201
    user_grant = user_grant_resp.json()
    assert user_grant["role"] == "Admin"
    assert user_grant["workspace_id"] == "ws_comp"

    # 2. Create grant for AD security group
    group_grant_resp = client.post(
        f"/api/admin/workspaces/{ws.id}/grants",
        headers=headers,
        json={
            "grantee_type": "group",
            "grantee_id": "CN=Compliance-Auditors",
            "role": "Viewer",
        },
    )
    assert group_grant_resp.status_code == 201
    group_grant = group_grant_resp.json()
    assert group_grant["grantee_id"] == "CN=Compliance-Auditors"
    assert group_grant["role"] == "Viewer"

    # 3. List grants for workspace
    list_grants = client.get(f"/api/admin/workspaces/{ws.id}/grants", headers=headers)
    assert list_grants.status_code == 200
    grants = list_grants.json()
    assert len(grants) == 2

    # 4. Delete grant
    del_grant = client.delete(
        f"/api/admin/workspaces/{ws.id}/grants/{user_grant['id']}",
        headers=headers,
    )
    assert del_grant.status_code == 200
    assert del_grant.json()["status"] == "deleted"

    # List again -> 1 left
    list_after = client.get(f"/api/admin/workspaces/{ws.id}/grants", headers=headers)
    assert len(list_after.json()) == 1


# =============================================================================
# 6. Global API Key Inventory & Emergency Revocation (/api/admin/keys)
# =============================================================================


def test_global_api_key_inventory_and_emergency_revocation(client, admin_credentials, auth_store):
    """Admin can list all keys with audit details, provision service keys, and revoke any key."""
    headers = admin_credentials["headers"]

    # 1. Provision a service account API key
    create_resp = client.post(
        "/api/admin/keys",
        headers=headers,
        json={
            "name": "ETL Service Account",
            "is_service": True,
            "allowed_workspaces": ["default", "ws_data"],
            "scopes": ["*"],
        },
    )
    assert create_resp.status_code == 201
    svc_data = create_resp.json()
    assert svc_data["is_service"] is True
    assert "raw_key" in svc_data
    svc_raw_key = svc_data["raw_key"]
    svc_key_id = svc_data["id"]

    # 2. Use the service account key to generate audit traffic
    call_resp = client.get("/api/auth/me", headers={"X-API-Key": svc_raw_key})
    assert call_resp.status_code == 200

    # 3. Inspect global inventory
    inv_resp = client.get("/api/admin/keys", headers=headers)
    assert inv_resp.status_code == 200
    keys = inv_resp.json()
    svc_found = next((k for k in keys if k["id"] == svc_key_id), None)
    assert svc_found is not None
    assert svc_found["is_service"] is True
    assert svc_found["last_used_at"] is not None

    # 4. Instant emergency revocation
    revoke_resp = client.delete(f"/api/admin/keys/{svc_key_id}", headers=headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"

    # 5. Immediate rejection on subsequent requests
    blocked_resp = client.get("/api/auth/me", headers={"X-API-Key": svc_raw_key})
    assert blocked_resp.status_code == 401
