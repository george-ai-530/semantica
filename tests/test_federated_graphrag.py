"""
Tests for Ticket 04: Governed Cross-Workspace Federated GraphRAG & RRF Fusion.

Validates:
1. Reciprocal Rank Fusion (RRF) algorithm correctness.
2. Multi-workspace read grant validation — HTTP 403 on unauthorized targets.
3. Concurrent fan-out across multiple workspace sessions.
4. Provenance (origin_workspace) preservation in federated results.
5. Strictly read-only federation with zero cross-space mutations.
6. HTTP boundary integration tests via FastAPI TestClient.
"""

import asyncio
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from semantica.auth import (
    AuthStore,
    RequestContext,
    create_access_token,
    get_current_identity,
    require_auth,
    set_auth_store,
)
from semantica.context.context_graph import ContextGraph
from semantica.explorer.federated import (
    FederatedSearchResult,
    federated_get_nodes,
    federated_search,
    reciprocal_rank_fusion,
    validate_federation_grants,
)
from semantica.explorer.session import GraphSession
from semantica.explorer.workspace_registry import WorkspaceSessionRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db_file = tmp_path / "test_federated.db"
    auth_store = AuthStore(db_file)
    set_auth_store(auth_store)
    yield auth_store
    auth_store.close()
    set_auth_store(None)


@pytest.fixture
def registry():
    reg = WorkspaceSessionRegistry()
    yield reg
    if not reg.is_closed:
        reg.shutdown()


@pytest.fixture
def populated_registry(registry):
    """Registry with 3 workspaces populated with distinct data."""
    # Engineering workspace
    eng = registry.get("ws_eng")
    eng.add_node("eng_node_1", "concept", content="Machine learning pipeline")
    eng.add_node("eng_node_2", "concept", content="Distributed systems architecture")
    eng.add_node("eng_node_3", "concept", content="API gateway design")

    # Finance workspace
    fin = registry.get("ws_fin")
    fin.add_node("fin_node_1", "concept", content="Quarterly revenue report")
    fin.add_node("fin_node_2", "concept", content="Budget allocation model")

    # Compliance workspace
    comp = registry.get("ws_compliance")
    comp.add_node("comp_node_1", "policy", content="Data retention policy")
    comp.add_node("comp_node_2", "policy", content="API security guidelines")

    return registry


@pytest.fixture
def admin_identity():
    """An admin identity with full access."""
    return RequestContext(
        user_id="admin_user",
        username="admin",
        is_service=False,
        authorized_workspaces=["*"],
        current_workspace="ws_eng",
        global_role="admin",
        workspace_roles={"ws_eng": "Admin", "ws_fin": "Admin", "ws_compliance": "Admin"},
        auth_method="bearer",
    )


@pytest.fixture
def eng_viewer_identity():
    """Identity with Viewer on ws_eng only."""
    return RequestContext(
        user_id="eng_viewer",
        username="eng_viewer",
        is_service=False,
        authorized_workspaces=["ws_eng"],
        current_workspace="ws_eng",
        global_role="user",
        workspace_roles={"ws_eng": "Viewer"},
        auth_method="bearer",
    )


@pytest.fixture
def multi_viewer_identity():
    """Identity with Viewer on ws_eng and ws_compliance but NOT ws_fin."""
    return RequestContext(
        user_id="multi_viewer",
        username="multi_viewer",
        is_service=False,
        authorized_workspaces=["ws_eng", "ws_compliance"],
        current_workspace="ws_eng",
        global_role="user",
        workspace_roles={"ws_eng": "Viewer", "ws_compliance": "Viewer"},
        auth_method="bearer",
    )


def _make_app(store, registry):
    """Build a minimal test app with federated routes."""
    from semantica.explorer.routes.federated import router as federated_router

    app = FastAPI()
    app.state.auth_store = store
    app.state.workspace_registry = registry
    app.state.session = registry.get_if_exists("default") or GraphSession(
        ContextGraph(advanced_analytics=False)
    )

    app.include_router(federated_router, dependencies=[Depends(require_auth)])
    return app


def _bearer(user_id, store, workspace_id="default"):
    """Create Authorization + X-Workspace-ID headers for a user."""
    workspace_roles = store.get_user_workspace_roles(user_id)
    token = create_access_token(
        payload={
            "sub": user_id,
            "workspaces": list(workspace_roles.keys()),
            "role": "user",
        },
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace_id,
    }


# ===========================================================================
# 1. RRF Algorithm Unit Tests
# ===========================================================================


class TestReciprocalRankFusion:
    """Unit tests for the RRF algorithm."""

    def test_single_list_preserves_order(self):
        results = [
            FederatedSearchResult(node={"id": "a"}, score=0.9, origin_workspace="ws_a"),
            FederatedSearchResult(node={"id": "b"}, score=0.7, origin_workspace="ws_a"),
            FederatedSearchResult(node={"id": "c"}, score=0.5, origin_workspace="ws_a"),
        ]
        merged = reciprocal_rank_fusion({"ws_a": results}, k=60)
        assert [r.node["id"] for r in merged] == ["a", "b", "c"]

    def test_two_lists_boost_shared_items(self):
        list_a = [
            FederatedSearchResult(node={"id": "shared"}, score=0.9, origin_workspace="ws_a"),
            FederatedSearchResult(node={"id": "a_only"}, score=0.8, origin_workspace="ws_a"),
        ]
        list_b = [
            FederatedSearchResult(node={"id": "shared"}, score=0.85, origin_workspace="ws_a"),
            FederatedSearchResult(node={"id": "b_only"}, score=0.8, origin_workspace="ws_b"),
        ]
        merged = reciprocal_rank_fusion({"ws_a": list_a, "ws_b": list_b}, k=60)

        # "shared" should be first because it appears in both lists
        assert merged[0].node["id"] == "shared"
        # Its RRF score should be the sum of 1/(60+1) from both lists
        expected_rrf = 1.0 / 61 + 1.0 / 61
        assert abs(merged[0].rrf_score - expected_rrf) < 1e-10

    def test_empty_lists(self):
        merged = reciprocal_rank_fusion({})
        assert merged == []

    def test_provenance_preserved(self):
        results = [
            FederatedSearchResult(node={"id": "x"}, score=0.5, origin_workspace="ws_fin"),
        ]
        merged = reciprocal_rank_fusion({"ws_fin": results})
        assert merged[0].origin_workspace == "ws_fin"

    def test_different_k_values(self):
        results_k1 = [
            FederatedSearchResult(node={"id": "a"}, score=0.9, origin_workspace="ws_a"),
        ]
        results_k60 = [
            FederatedSearchResult(node={"id": "a"}, score=0.9, origin_workspace="ws_a"),
        ]
        merged_k1 = reciprocal_rank_fusion({"ws_a": results_k1}, k=1)
        merged_k60 = reciprocal_rank_fusion({"ws_a": results_k60}, k=60)
        # With k=1 the RRF score is 1/(1+1)=0.5; with k=60 it's 1/(60+1)
        assert merged_k1[0].rrf_score > merged_k60[0].rrf_score

    def test_multiple_workspaces_different_items(self):
        list_a = [
            FederatedSearchResult(node={"id": "a1"}, score=0.9, origin_workspace="ws_a"),
        ]
        list_b = [
            FederatedSearchResult(node={"id": "b1"}, score=0.8, origin_workspace="ws_b"),
        ]
        list_c = [
            FederatedSearchResult(node={"id": "c1"}, score=0.7, origin_workspace="ws_c"),
        ]
        merged = reciprocal_rank_fusion({"a": list_a, "b": list_b, "c": list_c})
        # All should be present, all with same RRF score (1/(60+1) each)
        assert len(merged) == 3
        ids = {r.node["id"] for r in merged}
        assert ids == {"a1", "b1", "c1"}

    def test_rrf_scores_sum_across_appearances(self):
        """Item appearing in 3 lists gets 3x the RRF contribution of one in 1 list."""
        item = FederatedSearchResult(node={"id": "universal"}, score=0.5, origin_workspace="ws_a")
        lone = FederatedSearchResult(node={"id": "lone"}, score=0.99, origin_workspace="ws_a")

        merged = reciprocal_rank_fusion({
            "a": [item, lone],
            "b": [item],
            "c": [item],
        }, k=60)

        universal_result = next(r for r in merged if r.node["id"] == "universal")
        lone_result = next(r for r in merged if r.node["id"] == "lone")

        # universal: 1/61 * 3 from lists a,b,c (rank 1 in all)
        # lone: 1/62 from list a only (rank 2)
        assert universal_result.rrf_score > lone_result.rrf_score


# ===========================================================================
# 2. Grant Validation Tests
# ===========================================================================


class TestFederationGrantValidation:
    """Test multi-workspace read grant validation."""

    def test_admin_access_all(self, admin_identity):
        denied = validate_federation_grants(
            admin_identity, ["ws_eng", "ws_fin", "ws_compliance"]
        )
        assert denied == []

    def test_viewer_denied_ungranted(self, eng_viewer_identity):
        denied = validate_federation_grants(
            eng_viewer_identity, ["ws_eng", "ws_fin"]
        )
        assert "ws_fin" in denied
        assert "ws_eng" not in denied

    def test_multi_viewer_partial(self, multi_viewer_identity):
        denied = validate_federation_grants(
            multi_viewer_identity, ["ws_eng", "ws_fin", "ws_compliance"]
        )
        assert denied == ["ws_fin"]

    def test_empty_list_always_ok(self, eng_viewer_identity):
        denied = validate_federation_grants(eng_viewer_identity, [])
        assert denied == []

    def test_anonymous_access_all(self):
        anon = RequestContext(
            user_id="anon",
            is_anonymous=True,
            authorized_workspaces=["*"],
            global_role="admin",
        )
        denied = validate_federation_grants(anon, ["ws_a", "ws_b", "ws_c"])
        assert denied == []


# ===========================================================================
# 3. Federated Search (Async) Tests
# ===========================================================================


class TestFederatedSearch:
    """Test the async federated search function."""

    def test_search_across_workspaces(self, populated_registry, admin_identity):
        result = asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="API",
                primary_workspace="ws_eng",
                federated_workspaces=["ws_compliance"],
                limit=20,
            )
        )
        # Both ws_eng ("API gateway design") and ws_compliance ("API security guidelines")
        # have nodes matching "API"
        assert result.total > 0
        workspaces_in_results = {r.origin_workspace for r in result.results}
        # At least one workspace should contribute
        assert len(workspaces_in_results) >= 1
        assert set(result.workspaces_queried) == {"ws_eng", "ws_compliance"}

    def test_search_denied_raises(self, populated_registry, eng_viewer_identity):
        with pytest.raises(PermissionError, match="ws_fin"):
            asyncio.run(
                federated_search(
                    registry=populated_registry,
                    identity=eng_viewer_identity,
                    query="revenue",
                    primary_workspace="ws_eng",
                    federated_workspaces=["ws_fin"],
                )
            )

    def test_primary_always_included(self, populated_registry, admin_identity):
        result = asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="pipeline",
                primary_workspace="ws_eng",
                federated_workspaces=[],
            )
        )
        assert "ws_eng" in result.workspaces_queried

    def test_provenance_on_results(self, populated_registry, admin_identity):
        result = asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="policy",
                primary_workspace="ws_eng",
                federated_workspaces=["ws_compliance"],
            )
        )
        for r in result.results:
            assert r.origin_workspace in {"ws_eng", "ws_compliance"}

    def test_no_results_returns_empty(self, populated_registry, admin_identity):
        result = asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="xyznonexistenttermxyz",
                primary_workspace="ws_eng",
                federated_workspaces=["ws_fin"],
            )
        )
        assert result.total == 0
        assert result.results == []

    def test_fusion_method_is_rrf(self, populated_registry, admin_identity):
        result = asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="design",
                primary_workspace="ws_eng",
                federated_workspaces=[],
            )
        )
        assert result.fusion_method == "rrf"


# ===========================================================================
# 4. Federated Node Retrieval Tests
# ===========================================================================


class TestFederatedGetNodes:
    def test_nodes_from_multiple_workspaces(self, populated_registry, admin_identity):
        nodes, total, queried = federated_get_nodes(
            registry=populated_registry,
            identity=admin_identity,
            primary_workspace="ws_eng",
            federated_workspaces=["ws_fin"],
        )
        # ws_eng has 3 nodes, ws_fin has 2
        assert total == 5
        origins = {n["origin_workspace"] for n in nodes}
        assert origins == {"ws_eng", "ws_fin"}

    def test_nodes_denied_raises(self, populated_registry, eng_viewer_identity):
        with pytest.raises(PermissionError, match="ws_fin"):
            federated_get_nodes(
                registry=populated_registry,
                identity=eng_viewer_identity,
                primary_workspace="ws_eng",
                federated_workspaces=["ws_fin"],
            )

    def test_provenance_per_node(self, populated_registry, admin_identity):
        nodes, _, _ = federated_get_nodes(
            registry=populated_registry,
            identity=admin_identity,
            primary_workspace="ws_eng",
            federated_workspaces=["ws_compliance"],
        )
        for node in nodes:
            assert "origin_workspace" in node
            assert node["origin_workspace"] in {"ws_eng", "ws_compliance"}


# ===========================================================================
# 5. Read-Only Enforcement
# ===========================================================================


class TestReadOnlyFederation:
    """Verify that federated access is strictly read-only."""

    def test_federation_does_not_mutate_target(self, populated_registry, admin_identity):
        """After federated search, target workspace data is unchanged."""
        # Snapshot before
        fin_before, total_before = populated_registry.get("ws_fin").get_nodes(limit=1000)
        ids_before = {n["id"] for n in fin_before}

        # Execute federated search
        asyncio.run(
            federated_search(
                registry=populated_registry,
                identity=admin_identity,
                query="revenue",
                primary_workspace="ws_eng",
                federated_workspaces=["ws_fin"],
            )
        )

        # Snapshot after
        fin_after, total_after = populated_registry.get("ws_fin").get_nodes(limit=1000)
        ids_after = {n["id"] for n in fin_after}

        assert total_before == total_after
        assert ids_before == ids_after

    def test_federated_get_nodes_does_not_mutate(self, populated_registry, admin_identity):
        comp_before, total_before = populated_registry.get("ws_compliance").get_nodes(limit=1000)

        federated_get_nodes(
            registry=populated_registry,
            identity=admin_identity,
            primary_workspace="ws_eng",
            federated_workspaces=["ws_compliance"],
        )

        comp_after, total_after = populated_registry.get("ws_compliance").get_nodes(limit=1000)
        assert total_before == total_after


# ===========================================================================
# 6. HTTP Boundary Integration Tests
# ===========================================================================


class TestHTTPFederatedRoutes:
    """End-to-end tests via FastAPI TestClient."""

    def test_federated_search_authorized(self, store, populated_registry):
        app = _make_app(store, populated_registry)

        # Create admin user with grants on all workspaces
        user = store.create_user(username="fed_admin", password="test123", is_admin=True)
        for ws_id in ["ws_eng", "ws_fin", "ws_compliance"]:
            ws = store.get_workspace(ws_id)
            if ws is None:
                store.create_workspace(name=ws_id, workspace_id=ws_id)
            store.create_workspace_grant(ws_id, "user", user.id, "Admin")

        headers = _bearer(user.id, store, "ws_eng")
        with TestClient(app) as client:
            resp = client.post(
                "/api/graph/federated/search",
                headers=headers,
                json={
                    "query": "API",
                    "federated_workspaces": ["ws_compliance"],
                    "limit": 20,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "workspaces_queried" in data
        assert set(data["workspaces_queried"]) == {"ws_eng", "ws_compliance"}
        assert data["fusion_method"] == "rrf"

    def test_federated_search_403_on_denied(self, store, populated_registry):
        app = _make_app(store, populated_registry)

        # User with Viewer on ws_eng only
        user = store.create_user(username="eng_only", password="test123")
        store.create_workspace(name="WS Eng", workspace_id="ws_eng")
        store.create_workspace_grant("ws_eng", "user", user.id, "Viewer")
        store.create_workspace(name="WS Fin", workspace_id="ws_fin")
        # No grant on ws_fin

        headers = _bearer(user.id, store, "ws_eng")
        with TestClient(app) as client:
            resp = client.post(
                "/api/graph/federated/search",
                headers=headers,
                json={
                    "query": "revenue",
                    "federated_workspaces": ["ws_fin"],
                },
            )
        assert resp.status_code == 403
        assert "ws_fin" in resp.json()["detail"]

    def test_federated_nodes_with_provenance(self, store, populated_registry):
        app = _make_app(store, populated_registry)

        user = store.create_user(username="fed_node_user", password="test123", is_admin=True)
        for ws_id in ["ws_eng", "ws_compliance"]:
            ws = store.get_workspace(ws_id)
            if ws is None:
                store.create_workspace(name=ws_id, workspace_id=ws_id)
            store.create_workspace_grant(ws_id, "user", user.id, "Admin")

        headers = _bearer(user.id, store, "ws_eng")
        with TestClient(app) as client:
            resp = client.post(
                "/api/graph/federated/nodes",
                headers=headers,
                json={
                    "federated_workspaces": ["ws_compliance"],
                    "limit": 100,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5  # ws_eng: 3 + ws_compliance: 2
        origins = {n["origin_workspace"] for n in data["nodes"]}
        assert origins == {"ws_eng", "ws_compliance"}

    def test_federated_search_no_federation_still_works(self, store, populated_registry):
        app = _make_app(store, populated_registry)

        user = store.create_user(username="solo_user", password="test123", is_admin=True)
        store.create_workspace(name="WS Eng", workspace_id="ws_eng")
        store.create_workspace_grant("ws_eng", "user", user.id, "Admin")

        headers = _bearer(user.id, store, "ws_eng")
        with TestClient(app) as client:
            resp = client.post(
                "/api/graph/federated/search",
                headers=headers,
                json={"query": "pipeline", "federated_workspaces": []},
            )
        assert resp.status_code == 200
        assert "ws_eng" in resp.json()["workspaces_queried"]

    def test_federated_search_provenance_in_results(self, store, populated_registry):
        app = _make_app(store, populated_registry)

        user = store.create_user(username="prov_user", password="test123", is_admin=True)
        for ws_id in ["ws_eng", "ws_fin"]:
            ws = store.get_workspace(ws_id)
            if ws is None:
                store.create_workspace(name=ws_id, workspace_id=ws_id)
            store.create_workspace_grant(ws_id, "user", user.id, "Admin")

        headers = _bearer(user.id, store, "ws_eng")
        with TestClient(app) as client:
            resp = client.post(
                "/api/graph/federated/search",
                headers=headers,
                json={
                    "query": "model",
                    "federated_workspaces": ["ws_fin"],
                },
            )
        assert resp.status_code == 200
        for item in resp.json()["results"]:
            assert "origin_workspace" in item
            assert item["origin_workspace"] in {"ws_eng", "ws_fin"}
            assert "rrf_score" in item

    def test_anonymous_federation(self, store, populated_registry):
        """In anonymous mode, federation to any workspace is allowed."""
        app = _make_app(store, populated_registry)

        with patch.dict("os.environ", {"SEMANTICA_ALLOW_ANONYMOUS": "true"}):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/graph/federated/search",
                    headers={"X-Workspace-ID": "ws_eng"},
                    json={
                        "query": "policy",
                        "federated_workspaces": ["ws_compliance"],
                    },
                )
            assert resp.status_code == 200
            assert set(resp.json()["workspaces_queried"]) == {"ws_eng", "ws_compliance"}
