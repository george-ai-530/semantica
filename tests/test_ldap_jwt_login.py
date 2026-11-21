"""
Tests for Active Directory LDAP (Port 389) Direct Bind & JWT Login Flow (Ticket 02).

Validates:
1. Pluggable LDAPClientProtocol and MockLDAPClient execution.
2. Retrieval, parsing, and normalization of user memberOf AD security groups.
3. Dual-track authentication at /api/auth/login:
   - Corporate domain employees authenticating against AD over Port 389.
   - Automatic caching and syncing of user identity and group memberships into AuthStore.
   - External guest users authenticating against local password hashes in AuthStore.
4. Strict enforcement of guest account expiration (past expires_at rejected).
5. Cryptographically signed HMAC-SHA256 JWT issuance with claims (sub, type, groups, exp).
6. End-to-end authorization: using issued JWT bearer token to access protected Explorer routes.
"""

from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient

from semantica.auth import (
    ActiveDirectoryClient,
    AuthStore,
    LDAPClientProtocol,
    LDAPUser,
    MockLDAPClient,
    create_access_token,
    extract_group_names,
    get_auth_store,
    get_ldap_client,
    set_auth_store,
    set_ldap_client,
    verify_access_token,
)
from semantica.explorer.app import create_app


@pytest.fixture
def store(tmp_path):
    """Provide an isolated SQLite AuthStore for each test."""
    db_file = tmp_path / "test_auth_ldap.db"
    auth_store = AuthStore(db_file)
    set_auth_store(auth_store)
    yield auth_store
    auth_store.close()
    set_auth_store(None)


@pytest.fixture
def mock_ldap():
    """Provide a deterministic in-memory mock LDAP directory."""
    client = MockLDAPClient()
    # Pre-populate sample enterprise domain users
    client.add_user(
        username="jdoe",
        password="AD_Password_123!",
        display_name="John Doe",
        email="jdoe@corp.example.com",
        groups=[
            "CN=Finance-Team,OU=Security Groups,DC=corp,DC=example,DC=com",
            "CN=Domain Users,CN=Users,DC=corp,DC=example,DC=com",
        ],
        dn="CN=John Doe,OU=Employees,DC=corp,DC=example,DC=com",
    )
    client.add_user(
        username="alice_eng",
        password="AliceSecurePass456!",
        display_name="Alice Engineer",
        email="alice@corp.example.com",
        groups=[
            "CN=Engineering-Team,OU=Groups,DC=corp,DC=example,DC=com",
            "CN=Admins,OU=Groups,DC=corp,DC=example,DC=com",
        ],
        dn="CN=Alice Engineer,OU=Engineering,DC=corp,DC=example,DC=com",
    )
    set_ldap_client(client)
    yield client
    set_ldap_client(None)


@pytest.fixture
def app(store, mock_ldap):
    """Provide a configured Explorer FastAPI application with mock LDAP and auth store."""
    return create_app(auth_store=store, ldap_client=mock_ldap)


@pytest.fixture
def client(app, monkeypatch):
    """Provide TestClient with clean environment variables."""
    monkeypatch.delenv("SEMANTICA_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    with TestClient(app) as test_client:
        yield test_client


# =============================================================================
# 1. LDAP Client Protocol & Group Extraction Unit Tests
# =============================================================================

def test_extract_group_names_normalization():
    """Verify AD memberOf DN normalization into short name, CN prefix, and full DN."""
    raw_dns = [
        "CN=Finance-Team,OU=Security Groups,DC=corp,DC=example,DC=com",
        "CN=HR Department,OU=Groups,DC=corp,DC=example,DC=com",
    ]
    normalized = extract_group_names(raw_dns)

    # Should contain CN names
    assert "Finance-Team" in normalized
    assert "HR Department" in normalized

    # Should contain CN= prefix
    assert "CN=Finance-Team" in normalized
    assert "CN=HR Department" in normalized

    # Should contain full DN
    assert "CN=Finance-Team,OU=Security Groups,DC=corp,DC=example,DC=com" in normalized
    assert "CN=HR Department,OU=Groups,DC=corp,DC=example,DC=com" in normalized


def test_extract_group_names_plain_and_edge_cases():
    """Verify group normalization with plain strings and empty values."""
    assert extract_group_names([]) == []
    assert extract_group_names(None) == []

    # Single string / plain name
    result = extract_group_names(["DevOps"])
    assert "DevOps" in result
    assert "CN=DevOps" in result

    # Already has CN prefix without full DN
    result2 = extract_group_names(["CN=Analytics"])
    assert "Analytics" in result2
    assert "CN=Analytics" in result2


@pytest.mark.asyncio
async def test_mock_ldap_client_authenticate(mock_ldap):
    """Verify MockLDAPClient authentication and group extraction."""
    # Valid credentials
    user = await mock_ldap.authenticate("jdoe", "AD_Password_123!")
    assert user is not None
    assert isinstance(user, LDAPUser)
    assert user.username == "jdoe"
    assert user.display_name == "John Doe"
    assert user.email == "jdoe@corp.example.com"
    assert "Finance-Team" in user.groups
    assert "CN=Finance-Team" in user.groups

    # Bad password
    bad_pass = await mock_ldap.authenticate("jdoe", "WrongPass")
    assert bad_pass is None

    # Unknown user
    unknown = await mock_ldap.authenticate("nonexistent", "SomePass")
    assert unknown is None


def test_active_directory_client_unreachable_fail_safe():
    """Verify ActiveDirectoryClient handles unreachable servers safely without crashing."""
    client = ActiveDirectoryClient(
        server="127.0.0.1",
        port=65530,  # Unused port
        connect_timeout=1,
    )
    result = client.authenticate_sync("anyuser", "anypass")
    assert result is None


# =============================================================================
# 2. AD Employee Login Flow Tests (/api/auth/login)
# =============================================================================

def test_ad_login_success(client, store, mock_ldap):
    """Verify successful AD login issues a JWT with claims and syncs user to AuthStore."""
    payload = {
        "username": "jdoe",
        "password": "AD_Password_123!",
    }
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 7200
    assert data["user"]["username"] == "jdoe"
    assert data["user"]["type"] == "ad"
    assert "Finance-Team" in data["user"]["groups"]

    # Verify JWT cryptographic signature and claims
    claims = verify_access_token(data["access_token"])
    assert claims["sub"] == "jdoe"
    assert claims["type"] == "ad"
    assert "Finance-Team" in claims["groups"]
    assert "CN=Finance-Team" in claims["groups"]
    assert "exp" in claims
    assert claims["exp"] > datetime.now(timezone.utc).timestamp()

    # Verify user record was synced into AuthStore
    synced_user = store.get_user_by_username("jdoe")
    assert synced_user is not None
    assert synced_user.user_type == "ad"
    assert synced_user.email == "jdoe@corp.example.com"
    assert synced_user.display_name == "John Doe"

    # Verify group membership was synced into AuthStore
    user_groups = [g.name for g in store.get_user_groups(synced_user.id)]
    assert "Finance-Team" in user_groups or "CN=Finance-Team" in user_groups


def test_ad_login_group_membership_refresh(client, store, mock_ldap):
    """Verify user AD group memberships are refreshed on interactive login (User Story 3)."""
    # 1. Initial login with Finance-Team
    resp1 = client.post("/api/auth/login", json={"username": "jdoe", "password": "AD_Password_123!"})
    assert resp1.status_code == 200
    user_id = resp1.json()["user"]["id"]

    # Verify initial group in store
    groups1 = [g.name for g in store.get_user_groups(user_id)]
    assert any("Finance-Team" in g for g in groups1)

    # 2. Corporate IT department transfer: update groups in LDAP
    mock_ldap.set_user_groups(
        "jdoe",
        ["CN=Legal-Team,OU=Security Groups,DC=corp,DC=example,DC=com"],
    )

    # 3. Next interactive login
    resp2 = client.post("/api/auth/login", json={"username": "jdoe", "password": "AD_Password_123!"})
    assert resp2.status_code == 200
    assert "Legal-Team" in resp2.json()["user"]["groups"]

    # 4. Verify AuthStore has updated groups (old Finance-Team removed, Legal-Team added)
    groups2 = [g.name for g in store.get_user_groups(user_id)]
    assert any("Legal-Team" in g for g in groups2)
    assert not any("Finance-Team" in g for g in groups2)


def test_ad_login_bad_credentials(client):
    """Verify invalid AD password returns HTTP 401 without leaking internal errors."""
    payload = {
        "username": "jdoe",
        "password": "IncorrectPassword!",
    }
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


def test_ad_login_unknown_user(client):
    """Verify non-existent user returns HTTP 401."""
    payload = {
        "username": "unknown_employee",
        "password": "SomePassword123!",
    }
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


# =============================================================================
# 3. External Guest User Login Flow Tests
# =============================================================================

def test_guest_login_success(client, store):
    """Verify external guest user authenticates against local hash and receives JWT."""
    # Provision external guest account valid for 14 days
    future_expiry = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    store.create_user(
        username="consultant_bob",
        password="BobGuestPassword123!",
        user_type="guest",
        email="bob@external-consulting.com",
        display_name="Bob Consultant",
        expires_at=future_expiry,
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "consultant_bob", "password": "BobGuestPassword123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["type"] == "local"
    assert data["user"]["username"] == "consultant_bob"

    # Verify JWT claims
    claims = verify_access_token(data["access_token"])
    assert claims["sub"] == "consultant_bob"
    assert claims["type"] == "local"
    assert "exp" in claims


def test_guest_login_expired_rejection(client, store):
    """Verify expired guest account is rejected even with correct password (User Story 5)."""
    # Provision expired guest account (expired yesterday)
    past_expiry = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store.create_user(
        username="expired_contractor",
        password="ContractorPass123!",
        user_type="guest",
        email="contractor@vendor.com",
        expires_at=past_expiry,
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "expired_contractor", "password": "ContractorPass123!"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_guest_login_deactivated_rejection(client, store):
    """Verify deactivated guest account is rejected."""
    future_expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    user = store.create_user(
        username="deactivated_guest",
        password="GuestPassword123!",
        user_type="guest",
        expires_at=future_expiry,
    )
    store.update_user(user.id, is_active=False)

    response = client.post(
        "/api/auth/login",
        json={"username": "deactivated_guest", "password": "GuestPassword123!"},
    )
    assert response.status_code == 401
    assert "deactivated" in response.json()["detail"].lower()


def test_guest_login_bad_password(client, store):
    """Verify local user with incorrect password returns 401."""
    store.create_user(
        username="guest_charlie",
        password="CorrectPassword123!",
        user_type="guest",
    )
    response = client.post(
        "/api/auth/login",
        json={"username": "guest_charlie", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


# =============================================================================
# 4. End-to-End JWT Access on Protected Routes
# =============================================================================

def test_jwt_access_to_protected_me_endpoint(client):
    """Verify that JWT issued by /api/auth/login allows access to /api/auth/me."""
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "alice_eng", "password": "AliceSecurePass456!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Request /api/auth/me with Bearer token
    me_resp = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    identity = me_resp.json()
    assert identity["username"] == "alice_eng"
    assert identity["auth_method"] == "bearer"
    assert "Engineering-Team" in identity["groups"]


def test_jwt_workspace_rbac_integration(client, store):
    """Verify AD group mapping grants workspace role accessed via JWT token (User Story 19)."""
    # 1. Create a workspace
    ws = store.create_workspace("Engineering Projects", workspace_id="ws_engineering")

    # 2. Map AD group 'CN=Engineering-Team' to 'Editor' role on workspace
    store.create_workspace_grant(
        workspace_id=ws.id,
        grantee_type="group",
        grantee_id="Engineering-Team",
        role="Editor",
    )

    # 3. Log in as Alice (member of Engineering-Team)
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "alice_eng", "password": "AliceSecurePass456!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # 4. Call /api/auth/me with Bearer token and check workspace permissions
    me_resp = client.get(
        "/api/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-ID": "ws_engineering",
        },
    )
    assert me_resp.status_code == 200
    identity = me_resp.json()
    assert identity["workspace_roles"].get("ws_engineering") == "Editor"
    assert "ws_engineering" in identity["authorized_workspaces"]


def test_expired_guest_token_blocked_at_gateway(client, store):
    """Verify that if a guest account expires after token issuance, gateway rejects access."""
    # 1. Create guest expiring in 1 minute
    future_expiry = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    guest = store.create_user(
        username="temp_consultant",
        password="Pass123456!",
        user_type="guest",
        expires_at=future_expiry,
    )

    # 2. Log in and get token
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "temp_consultant", "password": "Pass123456!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Verify initial access works
    resp1 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200

    # 3. Fast-forward expiration in store
    past_expiry = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    store.update_user(guest.id, expires_at=past_expiry)

    # 4. Attempt to access protected endpoint with the existing token
    resp2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 401
    assert "expired" in resp2.json()["detail"].lower()


# =============================================================================
# 5. Input Validation & Provider Routing
# =============================================================================

def test_login_missing_credentials(client):
    """Verify empty or missing username/password returns 400 or 422."""
    resp1 = client.post("/api/auth/login", json={"username": "", "password": ""})
    assert resp1.status_code in (400, 422)

    resp2 = client.post("/api/auth/login", json={"username": "someone"})
    assert resp2.status_code == 422


def test_explicit_login_type_routing(client, store, mock_ldap):
    """Verify login_type='ad' forces AD and login_type='local' forces local store."""
    # Create local user
    store.create_user(username="local_only", password="LocalPassword1!", user_type="local")

    # Trying login_type='ad' with local credentials fails
    resp_ad = client.post(
        "/api/auth/login",
        json={"username": "local_only", "password": "LocalPassword1!", "login_type": "ad"},
    )
    assert resp_ad.status_code == 401

    # Trying login_type='local' with AD credentials fails
    resp_local = client.post(
        "/api/auth/login",
        json={"username": "jdoe", "password": "AD_Password_123!", "login_type": "local"},
    )
    assert resp_local.status_code == 401
