"""
Integration Test Suite: Enterprise Multi-Tenant Isolation & RBAC Flow
======================================================================

Covers all 4 core verification scenarios from
specs/enterprise_multi_tenant_rbac_spec.md using the real SQLite AuthStore,
FastAPI TestClient, and no mocked auth dependencies.

Scenario 1: Cross-tenant data isolation
  user_a -> ws_user_a: 200, ws_user_b: 403
  user_b -> ws_user_b: 200, ws_user_a: 403

Scenario 2: Dynamic grant visibility
  Admin grants user_a Viewer on ws_user_b -> 200
  Admin revokes grant -> 403 (immediate)

Scenario 3: API Key live permission synchronization
  user_a creates personal API key; key reflects live grants.
  After grant: key accesses ws_user_b -> 200
  After revocation: key accesses ws_user_b -> 403 (zero-delay)

Scenario 4: Group-based role inheritance
  Admin creates group, adds user_a, grants group Viewer on ws_user_b -> user_a 200
  Admin removes user_a from group -> user_a 403 (immediate)
"""

import pytest
from starlette.testclient import TestClient

from semantica.auth import AuthStore, set_auth_store, create_access_token
from semantica.context.context_graph import ContextGraph
from semantica.explorer.app import create_app
from semantica.explorer.session import GraphSession


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def auth_store(tmp_path_factory):
    """Module-scoped isolated AuthStore seeded with default accounts."""
    db_file = tmp_path_factory.mktemp("rbac_e2e") / "rbac_test.db"
    store = AuthStore(db_file)
    set_auth_store(store)
    yield store
    store.close()
    set_auth_store(None)


@pytest.fixture(scope="module")
def app(auth_store):
    """Module-scoped Explorer app wired to the shared AuthStore."""
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node("test_node", node_type="concept", content="Test Concept")
    session = GraphSession(graph)
    return create_app(session=session, auth_store=auth_store)


@pytest.fixture(scope="module")
def client(app):
    """Module-scoped TestClient (no anonymous access, no legacy key)."""
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _login(client: TestClient, username: str, password: str = "1") -> str:
    """Login and return Bearer token string."""
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "login_type": "local"},
    )
    assert resp.status_code == 200, (
        f"Login failed for {username!r}: {resp.status_code} {resp.text}"
    )
    return resp.json()["access_token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _apikey(raw_key: str) -> dict:
    return {"X-API-Key": raw_key}


def _ws_header(workspace_id: str) -> dict:
    return {"X-Workspace-ID": workspace_id}


def _probe(client: TestClient, headers: dict, workspace_id: str) -> int:
    """
    Probe access to a workspace by calling /api/graph/nodes.
    Returns the HTTP status code (200 or 403).
    """
    combined = {**headers, **_ws_header(workspace_id)}
    resp = client.get("/api/graph/nodes", headers=combined)
    return resp.status_code


# ---------------------------------------------------------------------------
# Scenario 1: Cross-tenant data isolation
# ---------------------------------------------------------------------------


class TestScenario1CrossTenantIsolation:
    """
    user_a owns ws_user_a (Admin grant seeded in store.__init__).
    user_b owns ws_user_b.
    Neither user has any grant on the other's workspace at baseline.
    """

    def test_user_a_can_access_own_workspace(self, client, auth_store):
        token = _login(client, "user_a")
        status = _probe(client, _bearer(token), "ws_user_a")
        assert status == 200, (
            f"user_a should have 200 on ws_user_a but got {status}"
        )

    def test_user_a_cannot_access_user_b_workspace(self, client, auth_store):
        token = _login(client, "user_a")
        status = _probe(client, _bearer(token), "ws_user_b")
        assert status == 403, (
            f"user_a should get 403 on ws_user_b but got {status}"
        )

    def test_user_b_can_access_own_workspace(self, client, auth_store):
        token = _login(client, "user_b")
        status = _probe(client, _bearer(token), "ws_user_b")
        assert status == 200, (
            f"user_b should have 200 on ws_user_b but got {status}"
        )

    def test_user_b_cannot_access_user_a_workspace(self, client, auth_store):
        token = _login(client, "user_b")
        status = _probe(client, _bearer(token), "ws_user_a")
        assert status == 403, (
            f"user_b should get 403 on ws_user_a but got {status}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: Dynamic grant visibility (Bearer token path)
# ---------------------------------------------------------------------------


class TestScenario2DynamicGrantVisibility:
    """
    Admin grants user_a Viewer on ws_user_b -> user_a gets 200.
    Admin revokes -> user_a gets 403 immediately (no caching).
    """

    def test_baseline_user_a_cannot_access_ws_user_b(self, client):
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 403

    def test_after_grant_user_a_can_access_ws_user_b(self, client, auth_store):
        # Admin grants user_a Viewer on ws_user_b
        user_a = auth_store.get_user_by_username("user_a")
        assert user_a is not None
        grant = auth_store.create_workspace_grant(
            workspace_id="ws_user_b",
            grantee_type="user",
            grantee_id=user_a.id,
            role="Viewer",
        )
        assert grant is not None
        self.__class__._grant_id = grant.id  # stash for revocation test

        # New login re-computes workspace_roles from live store
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 200, (
            "user_a should have 200 on ws_user_b after grant"
        )

    def test_after_revocation_user_a_cannot_access_ws_user_b(self, client, auth_store):
        # Revoke the grant created above
        grant_id = getattr(self.__class__, "_grant_id", None)
        assert grant_id is not None, "Grant must exist from previous step"
        deleted = auth_store.delete_workspace_grant(grant_id)
        assert deleted, "Grant deletion should succeed"

        # New login re-computes roles — grant is now gone
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 403, (
            "user_a should get 403 on ws_user_b after revocation"
        )


# ---------------------------------------------------------------------------
# Scenario 3: API Key live permission synchronization
# ---------------------------------------------------------------------------


class TestScenario3ApiKeyLiveSync:
    """
    user_a generates a personal API key.
    Key inherits live user/group grants with zero static caching.
    Grant ws_user_b -> key gets 200; revoke -> key gets 403 immediately.
    """

    @pytest.fixture(autouse=True)
    def setup_api_key(self, client, auth_store):
        """Create a personal API key for user_a before each test in this class."""
        user_a = auth_store.get_user_by_username("user_a")
        assert user_a is not None

        # Create personal key owned by user_a
        key_obj, raw_key = auth_store.create_api_key(
            name="user_a-test-key",
            user_id=user_a.id,
            is_service=False,
            allowed_workspaces=["*"],
        )
        self.raw_key = raw_key
        self.key_id = key_obj.id
        self.user_a = user_a

        yield

        # Cleanup: revoke key after test
        auth_store.revoke_api_key(self.key_id)

    def test_api_key_cannot_access_ungranted_workspace(self, client, auth_store):
        """API key should respect user's current grants (no ws_user_b at baseline)."""
        # Ensure no stray grant exists
        for grant in auth_store.list_workspace_grants("ws_user_b"):
            if grant.grantee_type == "user" and grant.grantee_id == self.user_a.id:
                auth_store.delete_workspace_grant(grant.id)

        status = _probe(client, _apikey(self.raw_key), "ws_user_b")
        assert status == 403, (
            f"API key should get 403 on ws_user_b without grant, got {status}"
        )

    def test_api_key_gains_access_after_user_grant(self, client, auth_store):
        """After granting user, the same API key immediately gets 200."""
        # Grant user_a Viewer on ws_user_b
        grant = auth_store.create_workspace_grant(
            workspace_id="ws_user_b",
            grantee_type="user",
            grantee_id=self.user_a.id,
            role="Viewer",
        )
        self.__class__._dynamic_grant_id = grant.id

        # API key lookup calls get_effective_workspaces_for_api_key live
        status = _probe(client, _apikey(self.raw_key), "ws_user_b")
        assert status == 200, (
            f"API key should get 200 on ws_user_b after user grant, got {status}"
        )

    def test_api_key_loses_access_after_grant_revocation(self, client, auth_store):
        """After revoking user's grant, same API key immediately gets 403."""
        # First grant, then immediately revoke
        grant = auth_store.create_workspace_grant(
            workspace_id="ws_user_b",
            grantee_type="user",
            grantee_id=self.user_a.id,
            role="Viewer",
        )
        # Confirm access
        assert _probe(client, _apikey(self.raw_key), "ws_user_b") == 200

        # Revoke
        auth_store.delete_workspace_grant(grant.id)

        # Key now 403 without token reissue
        status = _probe(client, _apikey(self.raw_key), "ws_user_b")
        assert status == 403, (
            f"API key should get 403 on ws_user_b after revocation, got {status}"
        )

    def test_api_key_loses_access_when_user_disabled(self, client, auth_store):
        """Disabling the user causes all their API keys to immediately 403."""
        # Grant access first
        grant = auth_store.create_workspace_grant(
            workspace_id="ws_user_b",
            grantee_type="user",
            grantee_id=self.user_a.id,
            role="Viewer",
        )
        assert _probe(client, _apikey(self.raw_key), "ws_user_b") == 200

        # Disable user
        auth_store.update_user(self.user_a.id, is_active=False)
        try:
            status = _probe(client, _apikey(self.raw_key), "ws_user_b")
            assert status in (401, 403), (
                f"Disabled user's API key should be rejected, got {status}"
            )
        finally:
            # Restore user and clean grant for subsequent tests
            auth_store.update_user(self.user_a.id, is_active=True)
            auth_store.delete_workspace_grant(grant.id)


# ---------------------------------------------------------------------------
# Scenario 4: Group-based role inheritance
# ---------------------------------------------------------------------------


class TestScenario4GroupRoleInheritance:
    """
    Admin creates group 'team_alpha', adds user_a, grants group Viewer on ws_user_b.
    user_a inherits 200; removing user_a from group -> 403 immediately.
    """

    def test_admin_creates_group(self, client, auth_store):
        """Admin can create a local security group."""
        # Clean up if group already exists from previous run
        existing = auth_store.get_group_by_name("team_alpha")
        if existing:
            auth_store.delete_group(existing.id)

        group = auth_store.create_group(
            name="team_alpha",
            group_type="local",
            description="Integration test group",
        )
        assert group is not None
        assert group.name == "team_alpha"

    def test_admin_adds_user_a_to_group(self, client, auth_store):
        """Admin adds user_a to team_alpha."""
        group = auth_store.get_group_by_name("team_alpha")
        assert group is not None, "team_alpha group must exist"

        user_a = auth_store.get_user_by_username("user_a")
        assert user_a is not None

        success = auth_store.add_user_to_group(group.id, user_a.id)
        assert success

        members = auth_store.list_group_members(group.id)
        member_ids = [m.id for m in members]
        assert user_a.id in member_ids

    def test_user_a_still_no_access_before_group_grant(self, client, auth_store):
        """Group membership alone doesn't grant workspace access."""
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 403, (
            "user_a should not access ws_user_b before group grant"
        )

    def test_group_grant_gives_user_a_access(self, client, auth_store):
        """Granting group Viewer on ws_user_b -> user_a gets 200."""
        group = auth_store.get_group_by_name("team_alpha")
        assert group is not None

        grant = auth_store.create_workspace_grant(
            workspace_id="ws_user_b",
            grantee_type="group",
            grantee_id=group.id,
            role="Viewer",
        )
        assert grant is not None
        self.__class__._group_grant_id = grant.id

        # New login re-reads group memberships and group grants
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 200, (
            "user_a should get 200 on ws_user_b via group grant"
        )

    def test_removing_user_a_from_group_revokes_access(self, client, auth_store):
        """After removing user_a from team_alpha, access to ws_user_b is immediately 403."""
        group = auth_store.get_group_by_name("team_alpha")
        assert group is not None

        user_a = auth_store.get_user_by_username("user_a")
        assert user_a is not None

        # Remove from group
        removed = auth_store.remove_user_from_group(group.id, user_a.id)
        assert removed

        # Login recomputes workspace_roles — group membership no longer includes user_a
        token = _login(client, "user_a")
        assert _probe(client, _bearer(token), "ws_user_b") == 403, (
            "user_a should get 403 on ws_user_b after removal from team_alpha"
        )

    def test_api_key_also_loses_group_inherited_access(self, client, auth_store):
        """API key also immediately 403s when user_a is removed from group."""
        group = auth_store.get_group_by_name("team_alpha")
        assert group is not None

        user_a = auth_store.get_user_by_username("user_a")
        assert user_a is not None

        # Ensure group grant exists
        group_grant_id = getattr(self.__class__, "_group_grant_id", None)
        if not group_grant_id:
            grant = auth_store.create_workspace_grant(
                workspace_id="ws_user_b",
                grantee_type="group",
                grantee_id=group.id,
                role="Viewer",
            )
            group_grant_id = grant.id

        # Add user_a back to group
        auth_store.add_user_to_group(group.id, user_a.id)

        # Create personal API key
        key_obj, raw_key = auth_store.create_api_key(
            name="user_a-group-key",
            user_id=user_a.id,
            is_service=False,
            allowed_workspaces=["*"],
        )

        try:
            # Confirm key gets 200 via group inheritance
            status_before = _probe(client, _apikey(raw_key), "ws_user_b")
            assert status_before == 200, (
                f"API key should get 200 via group, got {status_before}"
            )

            # Remove user_a from group
            auth_store.remove_user_from_group(group.id, user_a.id)

            # API key should immediately 403
            status_after = _probe(client, _apikey(raw_key), "ws_user_b")
            assert status_after == 403, (
                f"API key should get 403 after group removal, got {status_after}"
            )
        finally:
            auth_store.revoke_api_key(key_obj.id)


# ---------------------------------------------------------------------------
# Scenario via HTTP Admin Routes (REST API surface)
# ---------------------------------------------------------------------------


class TestAdminRoutesE2E:
    """
    Validate the same RBAC flows through the HTTP admin REST API surface
    (POST /api/admin/groups, POST /api/admin/groups/{id}/members, etc.).
    """

    def _admin_token(self, client: TestClient) -> str:
        return _login(client, "admin")

    def test_admin_can_create_group_via_api(self, client):
        token = self._admin_token(client)
        # Clean previous
        resp = client.get("/api/admin/groups", headers=_bearer(token))
        assert resp.status_code == 200
        for grp in resp.json():
            if grp["name"] == "api_test_group":
                client.delete(f"/api/admin/groups/{grp['id']}", headers=_bearer(token))

        resp = client.post(
            "/api/admin/groups",
            headers=_bearer(token),
            json={"name": "api_test_group", "description": "Test via API"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "api_test_group"
        self.__class__._api_group_id = data["id"]

    def test_admin_adds_user_a_via_api(self, client):
        token = self._admin_token(client)
        group_id = getattr(self.__class__, "_api_group_id", None)
        assert group_id, "Group must exist from previous test"

        resp = client.post(
            f"/api/admin/groups/{group_id}/members",
            headers=_bearer(token),
            json={"username": "user_a"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "added"

    def test_admin_grants_group_role_via_api(self, client):
        token = self._admin_token(client)
        group_id = getattr(self.__class__, "_api_group_id", None)
        assert group_id

        resp = client.post(
            "/api/admin/workspaces/ws_user_b/grants",
            headers=_bearer(token),
            json={
                "grantee_type": "group",
                "grantee_id": group_id,
                "role": "Viewer",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "Viewer"
        self.__class__._api_grant_id = data["id"]

        # user_a should now have access via group
        token_a = _login(client, "user_a")
        assert _probe(client, _bearer(token_a), "ws_user_b") == 200

    def test_admin_removes_user_a_from_group_via_api(self, client, auth_store):
        token = self._admin_token(client)
        group_id = getattr(self.__class__, "_api_group_id", None)
        assert group_id

        user_a = auth_store.get_user_by_username("user_a")
        assert user_a

        resp = client.delete(
            f"/api/admin/groups/{group_id}/members/{user_a.id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

        # user_a immediately 403
        token_a = _login(client, "user_a")
        assert _probe(client, _bearer(token_a), "ws_user_b") == 403

    def test_admin_revokes_grant_via_api(self, client):
        token = self._admin_token(client)
        grant_id = getattr(self.__class__, "_api_grant_id", None)
        if not grant_id:
            pytest.skip("No grant to revoke")

        resp = client.delete(
            f"/api/admin/workspaces/ws_user_b/grants/{grant_id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
