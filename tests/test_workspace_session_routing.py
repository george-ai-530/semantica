"""
Tests for Ticket 03: Dynamic Multi-Workspace Session Routing & FalkorDB Graph Key Isolation.

Validates:
1. WorkspaceSessionRegistry thread-safe lifecycle (lazy init, caching, shutdown).
2. Per-workspace physical graph isolation — data in workspace A is invisible to workspace B.
3. Gateway-level RBAC enforcement — HTTP 403 for unauthorized workspace access.
4. Session routing via RequestContext integration — correct session is returned
   based on X-Workspace-ID header / query parameter.
5. Concurrency: parallel workspace access does not corrupt session state.
6. Backwards compatibility: legacy single-session mode still works.
"""

import concurrent.futures
import threading
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.testclient import TestClient

from semantica.auth import (
    AuthStore,
    RequestContext,
    create_access_token,
    get_current_identity,
    require_auth,
    require_workspace_role,
    set_auth_store,
)
from semantica.context.context_graph import ContextGraph
from semantica.explorer.dependencies import get_session, get_workspace_session
from semantica.explorer.session import GraphSession
from semantica.explorer.workspace_registry import (
    WorkspaceSessionRegistry,
    default_graph_key,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """Provide a fresh, isolated AuthStore instance for each test."""
    db_file = tmp_path / "test_ws_routing.db"
    auth_store = AuthStore(db_file)
    set_auth_store(auth_store)
    yield auth_store
    auth_store.close()
    set_auth_store(None)


@pytest.fixture
def registry():
    """Provide a fresh WorkspaceSessionRegistry."""
    reg = WorkspaceSessionRegistry()
    yield reg
    if not reg.is_closed:
        reg.shutdown()


@pytest.fixture
def app_with_registry(store):
    """FastAPI test app wired with WorkspaceSessionRegistry and auth store."""
    app = FastAPI(title="Workspace Routing Test")

    registry = WorkspaceSessionRegistry()
    # Pre-register a default session
    default_session = GraphSession(ContextGraph(advanced_analytics=False))
    registry.register("default", default_session)

    app.state.auth_store = store
    app.state.workspace_registry = registry
    app.state.session = default_session  # legacy compat

    # --- Routes ---

    @app.get("/api/nodes", dependencies=[Depends(require_auth)])
    async def list_nodes(
        request: Request,
        identity: RequestContext = Depends(get_current_identity),
    ):
        session = get_session(request)
        nodes, total = session.get_nodes(limit=1000)
        return {"total": total, "workspace": identity.current_workspace}

    @app.post("/api/nodes", dependencies=[Depends(require_auth)])
    async def add_node(
        request: Request,
        identity: RequestContext = Depends(get_current_identity),
    ):
        body = await request.json()
        session = get_session(request)
        added = session.add_node(
            node_id=body["id"],
            node_type=body.get("type", "entity"),
            content=body.get("content", ""),
        )
        return {"added": added, "workspace": identity.current_workspace}

    @app.get(
        "/api/workspace-editor",
        dependencies=[Depends(require_workspace_role("Editor"))],
    )
    async def editor_route(
        request: Request,
        identity: RequestContext = Depends(get_current_identity),
    ):
        session = get_session(request)
        return {"status": "ok", "workspace": identity.current_workspace}

    @app.get(
        "/api/workspace-admin",
        dependencies=[Depends(require_workspace_role("Admin"))],
    )
    async def admin_route(
        request: Request,
        identity: RequestContext = Depends(get_current_identity),
    ):
        return {"status": "admin_ok", "workspace": identity.current_workspace}

    @app.get("/api/graph-key")
    async def graph_key_route(request: Request):
        ws_id = (
            request.headers.get("X-Workspace-ID")
            or request.query_params.get("workspace")
            or "default"
        )
        reg: WorkspaceSessionRegistry = request.app.state.workspace_registry
        return {"graph_key": reg.graph_key_for(ws_id), "workspace": ws_id}

    yield app, registry, store

    registry.shutdown()


def _make_client(app_fixture):
    app, registry, store = app_fixture
    return TestClient(app), registry, store


def _create_user_with_grant(store, username, workspace_id, role, is_admin=False):
    """Helper to create a user, workspace, and grant in one call."""
    user = store.create_user(username=username, password="test123", is_admin=is_admin)
    ws = store.get_workspace(workspace_id)
    if ws is None:
        ws = store.create_workspace(name=f"WS {workspace_id}", workspace_id=workspace_id)
    store.create_workspace_grant(workspace_id=workspace_id, grantee_type="user", grantee_id=user.id, role=role)
    return user


def _bearer_header(user, store, workspace_id="default"):
    """Create Authorization header with JWT token for a user."""
    workspace_roles = store.get_user_workspace_roles(user.id)
    token = create_access_token(
        payload={
            "sub": user.id,
            "username": user.username,
            "workspaces": list(workspace_roles.keys()),
            "role": user.global_role,
        },
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace_id,
    }


# ===========================================================================
# 1. WorkspaceSessionRegistry Unit Tests
# ===========================================================================


class TestWorkspaceSessionRegistryUnit:
    """Direct unit tests on the registry class."""

    def test_default_graph_key_mapping(self):
        assert default_graph_key("default") == "graph:default"
        assert default_graph_key("ws_123") == "graph:ws_ws_123"
        assert default_graph_key("engineering") == "graph:ws_engineering"

    def test_lazy_creation(self, registry):
        assert registry.session_count == 0
        session = registry.get("ws_alpha")
        assert session is not None
        assert isinstance(session, GraphSession)
        assert registry.session_count == 1

    def test_caching(self, registry):
        session1 = registry.get("ws_beta")
        session2 = registry.get("ws_beta")
        assert session1 is session2  # same object reference
        assert registry.session_count == 1

    def test_multiple_workspaces(self, registry):
        s1 = registry.get("ws_a")
        s2 = registry.get("ws_b")
        assert s1 is not s2
        assert registry.session_count == 2
        assert set(registry.active_workspaces) == {"ws_a", "ws_b"}

    def test_register_external_session(self, registry):
        custom = GraphSession(ContextGraph(advanced_analytics=False))
        registry.register("custom_ws", custom)
        assert registry.get("custom_ws") is custom

    def test_remove(self, registry):
        registry.get("ws_remove_me")
        assert registry.session_count == 1
        removed = registry.remove("ws_remove_me")
        assert removed is not None
        assert registry.session_count == 0

    def test_remove_nonexistent(self, registry):
        assert registry.remove("nonexistent") is None

    def test_get_if_exists(self, registry):
        assert registry.get_if_exists("ws_nope") is None
        registry.get("ws_yep")
        assert registry.get_if_exists("ws_yep") is not None

    def test_shutdown(self, registry):
        registry.get("ws_1")
        registry.get("ws_2")
        assert registry.session_count == 2
        registry.shutdown()
        assert registry.is_closed
        assert registry.session_count == 0

    def test_get_after_shutdown_raises(self, registry):
        registry.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            registry.get("ws_new")

    def test_shutdown_idempotent(self, registry):
        registry.shutdown()
        registry.shutdown()  # should not raise

    def test_graph_key_for(self, registry):
        key = registry.graph_key_for("engineering")
        assert key == "graph:ws_engineering"

    def test_custom_graph_key_fn(self):
        custom_fn = lambda ws_id: f"custom:{ws_id}"
        reg = WorkspaceSessionRegistry(graph_key_fn=custom_fn)
        assert reg.graph_key_for("abc") == "custom:abc"
        session = reg.get("abc")
        assert session is not None
        reg.shutdown()

    def test_custom_session_factory(self):
        created = {}

        def factory(graph_key: str) -> GraphSession:
            s = GraphSession(ContextGraph(advanced_analytics=False))
            created[graph_key] = s
            return s

        reg = WorkspaceSessionRegistry(session_factory=factory)
        session = reg.get("ws_factory")
        expected_key = default_graph_key("ws_factory")
        assert expected_key in created
        assert created[expected_key] is session
        reg.shutdown()


# ===========================================================================
# 2. Physical Graph Isolation Tests
# ===========================================================================


class TestPhysicalGraphIsolation:
    """Verify that data written to workspace A is invisible to workspace B."""

    def test_data_isolation_between_workspaces(self, registry):
        session_a = registry.get("ws_a")
        session_b = registry.get("ws_b")

        # Write data to workspace A
        session_a.add_node("node_alpha", "concept", content="Alpha content")
        session_a.add_node("node_beta", "concept", content="Beta content")

        # Write different data to workspace B
        session_b.add_node("node_gamma", "concept", content="Gamma content")

        # Verify workspace A sees only its data
        nodes_a, total_a = session_a.get_nodes(limit=1000)
        node_ids_a = {n["id"] for n in nodes_a}
        assert "node_alpha" in node_ids_a
        assert "node_beta" in node_ids_a
        assert "node_gamma" not in node_ids_a
        assert total_a == 2

        # Verify workspace B sees only its data
        nodes_b, total_b = session_b.get_nodes(limit=1000)
        node_ids_b = {n["id"] for n in nodes_b}
        assert "node_gamma" in node_ids_b
        assert "node_alpha" not in node_ids_b
        assert "node_beta" not in node_ids_b
        assert total_b == 1

    def test_edge_isolation(self, registry):
        session_a = registry.get("ws_edges_a")
        session_b = registry.get("ws_edges_b")

        session_a.add_node("src", "entity")
        session_a.add_node("tgt", "entity")
        session_a.add_edge("src", "tgt", edge_type="related_to")

        edges_a, total_a = session_a.get_edges(limit=1000)
        edges_b, total_b = session_b.get_edges(limit=1000)

        assert total_a == 1
        assert total_b == 0

    def test_search_index_isolation(self, registry):
        session_a = registry.get("ws_search_a")
        session_b = registry.get("ws_search_b")

        session_a.add_node("unique_alpha_42", "concept", content="A unique alpha concept")
        session_b.add_node("unique_beta_42", "concept", content="A unique beta concept")

        results_a = session_a.search("alpha")
        results_b = session_b.search("alpha")

        assert len(results_a) > 0
        assert len(results_b) == 0

    def test_graph_key_uniqueness(self, registry):
        """Different workspaces get different graph keys."""
        key_a = registry.graph_key_for("ws_a")
        key_b = registry.graph_key_for("ws_b")
        key_default = registry.graph_key_for("default")
        assert key_a != key_b
        assert key_a != key_default
        assert key_b != key_default

    def test_default_workspace_backwards_compat(self, registry):
        """The 'default' workspace key is 'graph:default' for migration compat."""
        assert registry.graph_key_for("default") == "graph:default"


# ===========================================================================
# 3. RBAC & Permission Enforcement Tests (HTTP Boundary)
# ===========================================================================


class TestRBACEnforcement:
    """Test that workspace access is gated by role at the HTTP boundary."""

    def test_viewer_can_read_nodes(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "viewer_user", "default", "Viewer")
        headers = _bearer_header(user, store, "default")

        resp = client.get("/api/nodes", headers=headers)
        assert resp.status_code == 200

    def test_viewer_denied_editor_route(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "viewer_only", "default", "Viewer")
        headers = _bearer_header(user, store, "default")

        resp = client.get("/api/workspace-editor", headers=headers)
        assert resp.status_code == 403

    def test_editor_can_access_editor_route(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "editor_user", "default", "Editor")
        headers = _bearer_header(user, store, "default")

        resp = client.get("/api/workspace-editor", headers=headers)
        assert resp.status_code == 200

    def test_editor_denied_admin_route(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "editor_no_admin", "default", "Editor")
        headers = _bearer_header(user, store, "default")

        resp = client.get("/api/workspace-admin", headers=headers)
        assert resp.status_code == 403

    def test_admin_can_access_all(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "admin_user", "default", "Admin", is_admin=True)
        headers = _bearer_header(user, store, "default")

        resp_editor = client.get("/api/workspace-editor", headers=headers)
        resp_admin = client.get("/api/workspace-admin", headers=headers)
        assert resp_editor.status_code == 200
        assert resp_admin.status_code == 200

    def test_no_grant_returns_403(self, app_with_registry):
        """A user with no workspace grant gets 403 on role-protected routes."""
        client, registry, store = _make_client(app_with_registry)
        user = store.create_user(username="no_grant_user", password="test123")
        store.create_workspace(name="Restricted WS", workspace_id="restricted_ws")
        # No grant for this user on 'restricted_ws'
        headers = _bearer_header(user, store, "restricted_ws")

        resp = client.get("/api/workspace-editor", headers=headers)
        assert resp.status_code == 403

    def test_cross_workspace_access_denied(self, app_with_registry):
        """User with Viewer on ws_a but no grant on ws_b is denied on ws_b."""
        client, registry, store = _make_client(app_with_registry)
        store.create_workspace(name="WS A", workspace_id="ws_a")
        store.create_workspace(name="WS B", workspace_id="ws_b")
        user = store.create_user(username="cross_user", password="test123")
        store.create_workspace_grant("ws_a", "user", user.id, "Editor")
        # No grant on ws_b

        headers = _bearer_header(user, store, "ws_b")
        resp = client.get("/api/workspace-editor", headers=headers)
        assert resp.status_code == 403


# ===========================================================================
# 4. Session Routing via HTTP Tests
# ===========================================================================


class TestSessionRouting:
    """Verify that the correct session is selected based on the workspace header."""

    def test_routing_via_header(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "router_user", "default", "Admin", is_admin=True)

        # Create a second workspace and add a grant
        store.create_workspace(name="WS Eng", workspace_id="ws_eng")
        store.create_workspace_grant("ws_eng", "user", user.id, "Admin")

        # Add a node to ws_eng
        headers = _bearer_header(user, store, "ws_eng")
        resp = client.post(
            "/api/nodes",
            headers=headers,
            json={"id": "eng_node_1", "type": "concept", "content": "Engineering concept"},
        )
        assert resp.status_code == 200
        assert resp.json()["workspace"] == "ws_eng"

        # Verify node is visible in ws_eng
        resp = client.get("/api/nodes", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Verify node is NOT visible in default workspace
        headers_default = _bearer_header(user, store, "default")
        resp = client.get("/api/nodes", headers=headers_default)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_routing_via_query_param(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)
        user = _create_user_with_grant(store, "query_router", "default", "Admin", is_admin=True)
        store.create_workspace(name="WS QP", workspace_id="ws_qp")
        store.create_workspace_grant("ws_qp", "user", user.id, "Admin")

        # workspace is resolved by get_current_identity from X-Workspace-ID or ?workspace=
        token = create_access_token(
            payload={"sub": user.id, "username": user.username, "role": "admin"},
        )
        resp = client.get(
            "/api/nodes",
            params={"workspace": "ws_qp"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["workspace"] == "ws_qp"

    def test_graph_key_endpoint(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)

        resp = client.get("/api/graph-key", headers={"X-Workspace-ID": "engineering"})
        data = resp.json()
        assert data["graph_key"] == "graph:ws_engineering"
        assert data["workspace"] == "engineering"

        resp = client.get("/api/graph-key", headers={"X-Workspace-ID": "default"})
        assert resp.json()["graph_key"] == "graph:default"


# ===========================================================================
# 5. Concurrency Tests
# ===========================================================================


class TestConcurrency:
    """Verify thread safety of the registry under concurrent access."""

    def test_concurrent_session_creation(self, registry):
        """Multiple threads requesting different workspaces simultaneously."""
        ws_ids = [f"concurrent_ws_{i}" for i in range(20)]
        results = {}

        def get_session(ws_id):
            session = registry.get(ws_id)
            results[ws_id] = id(session)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(get_session, ws) for ws in ws_ids]
            concurrent.futures.wait(futures)
            # Check no exceptions
            for f in futures:
                f.result()

        assert len(results) == 20
        # All sessions are distinct objects
        assert len(set(results.values())) == 20

    def test_concurrent_same_workspace(self, registry):
        """Multiple threads requesting the SAME workspace get the SAME session."""
        sessions = []
        lock = threading.Lock()

        def get_same():
            s = registry.get("shared_ws")
            with lock:
                sessions.append(id(s))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(get_same) for _ in range(50)]
            concurrent.futures.wait(futures)
            for f in futures:
                f.result()

        # All must be the same object
        assert len(set(sessions)) == 1

    def test_concurrent_writes_to_different_workspaces(self, registry):
        """Concurrent writes to different workspaces don't corrupt each other."""

        def write_to_ws(ws_id, node_prefix):
            session = registry.get(ws_id)
            for i in range(10):
                session.add_node(f"{node_prefix}_{i}", "entity", content=f"Content {i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(write_to_ws, f"ws_cw_{i}", f"prefix_{i}")
                for i in range(4)
            ]
            concurrent.futures.wait(futures)
            for f in futures:
                f.result()

        # Each workspace should have exactly 10 nodes
        for i in range(4):
            session = registry.get(f"ws_cw_{i}")
            nodes, total = session.get_nodes(limit=1000)
            assert total == 10
            node_ids = {n["id"] for n in nodes}
            for j in range(10):
                assert f"prefix_{i}_{j}" in node_ids


# ===========================================================================
# 6. Lifecycle & Edge Cases
# ===========================================================================


class TestLifecycle:
    """Test session lifecycle, lazy init, and shutdown behavior."""

    def test_lazy_init_no_eager_creation(self):
        """Registry starts with zero sessions (no eager workspace creation)."""
        reg = WorkspaceSessionRegistry()
        assert reg.session_count == 0
        reg.shutdown()

    def test_register_then_get(self, registry):
        custom = GraphSession(ContextGraph(advanced_analytics=False))
        custom.add_node("pre_registered", "entity")
        registry.register("pre_ws", custom)

        retrieved = registry.get("pre_ws")
        assert retrieved is custom
        node = retrieved.get_node("pre_registered")
        assert node is not None

    def test_active_workspaces_tracking(self, registry):
        registry.get("ws_x")
        registry.get("ws_y")
        registry.get("ws_z")
        assert set(registry.active_workspaces) == {"ws_x", "ws_y", "ws_z"}

    def test_shutdown_clears_all(self, registry):
        registry.get("ws_1")
        registry.get("ws_2")
        registry.shutdown()
        assert registry.session_count == 0
        assert registry.active_workspaces == []


# ===========================================================================
# 7. Backwards Compatibility (Legacy Single-Session Mode)
# ===========================================================================


class TestLegacyCompatibility:
    """Verify that the system still works without WorkspaceSessionRegistry."""

    def test_legacy_fallback_no_registry(self, store):
        """When no registry is on app.state, get_session falls back to app.state.session."""
        app = FastAPI()
        legacy_session = GraphSession(ContextGraph(advanced_analytics=False))
        legacy_session.add_node("legacy_node", "entity")
        app.state.session = legacy_session
        app.state.auth_store = store
        # No app.state.workspace_registry

        @app.get("/api/legacy-nodes", dependencies=[Depends(require_auth)])
        async def legacy_route(
            request: Request,
            identity: RequestContext = Depends(get_current_identity),
        ):
            session = get_session(request)
            nodes, total = session.get_nodes(limit=100)
            return {"total": total}

        with patch.dict("os.environ", {"SEMANTICA_ALLOW_ANONYMOUS": "true"}):
            client = TestClient(app)
            resp = client.get("/api/legacy-nodes")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

    def test_missing_session_returns_503(self, store):
        """When neither registry nor session is available, returns 503."""
        app = FastAPI()
        app.state.auth_store = store

        @app.get("/api/broken")
        async def broken(request: Request):
            return get_session(request)

        client = TestClient(app)
        resp = client.get("/api/broken")
        assert resp.status_code == 503


# ===========================================================================
# 8. Anonymous Mode Integration
# ===========================================================================


class TestAnonymousMode:
    """Verify workspace routing works in anonymous development mode."""

    def test_anonymous_routes_to_requested_workspace(self, app_with_registry):
        client, registry, store = _make_client(app_with_registry)

        with patch.dict("os.environ", {"SEMANTICA_ALLOW_ANONYMOUS": "true"}):
            # Add node to ws_anon
            resp = client.post(
                "/api/nodes",
                headers={"X-Workspace-ID": "ws_anon"},
                json={"id": "anon_node", "type": "concept"},
            )
            assert resp.status_code == 200
            assert resp.json()["workspace"] == "ws_anon"

            # Verify isolation: default has no nodes
            resp = client.get("/api/nodes", headers={"X-Workspace-ID": "default"})
            assert resp.json()["total"] == 0

            # ws_anon has the node
            resp = client.get("/api/nodes", headers={"X-Workspace-ID": "ws_anon"})
            assert resp.json()["total"] == 1
