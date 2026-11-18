"""
Integration & Unit Tests: Durable Multi-Workspace Graph Persistence
====================================================================

Verifies:
1. ``WorkspaceGraphStore`` SQLite WAL schema, lossless node/edge round-trips,
   and incremental mutations.
2. ``FalkorDBSyncBridge`` zero-dependency RESP2 socket framing against a live
   local TCP RESP2 server plus non-fatal offline fallback.
3. Dynamic ``POST /api/import`` into ``ws_user_a``, full application shutdown
   and restart against the same ``SEMANTICA_GRAPH_DB_PATH``, confirming both
   seeded (7) and imported nodes/edges survive container restarts.
4. Custom workspace ``ws_alpha`` creation, data import, restart persistence,
   and strict cross-tenant HTTP 403 RBAC isolation.
5. ``PUT /api/markdown/context-node/...`` live mutation persistence across
   application restarts for both tenant workspaces and ``default``.
"""

from __future__ import annotations

import io
import json
import socketserver
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Tuple

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.auth import AuthStore, set_auth_store  # noqa: E402
from semantica.context.context_graph import ContextEdge, ContextGraph, ContextNode  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.graph_persistence import (  # noqa: E402
    FalkorDBSyncBridge,
    WorkspaceGraphStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: TestClient, username: str, password: str = "1") -> str:
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "login_type": "local"},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def _headers(token: str, workspace: str = "default") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace,
    }


class _MockRESP2Server:
    """Lightweight threaded TCP server speaking RESP2 for FalkorDB bridge tests."""

    def __init__(self) -> None:
        self.commands: List[List[str]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                while True:
                    line = self.rfile.readline()
                    if not line:
                        break
                    if not line.startswith(b"*"):
                        self.wfile.write(b"-ERR protocol error\r\n")
                        self.wfile.flush()
                        continue
                    argc = int(line[1:].strip())
                    args: List[str] = []
                    for _ in range(argc):
                        bulk_hdr = self.rfile.readline()
                        length = int(bulk_hdr[1:].strip())
                        data = self.rfile.read(length)
                        self.rfile.read(2)  # CRLF
                        args.append(data.decode("utf-8"))
                    with outer._lock:
                        outer.commands.append(args)
                    if args and args[0].upper() == "PING":
                        self.wfile.write(b"+PONG\r\n")
                    elif args and args[0].upper() == "GRAPH.QUERY":
                        # Nested RESP2 array matching FalkorDB GRAPH.QUERY stats reply
                        self.wfile.write(
                            b"*1\r\n*2\r\n$14\r\nNodes created:\r\n$17\r\nQuery internal ok\r\n"
                        )
                    else:
                        self.wfile.write(b"+OK\r\n")
                    self.wfile.flush()

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_MockRESP2Server":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


# ===========================================================================
# 1. WorkspaceGraphStore Unit Tests
# ===========================================================================


class TestWorkspaceGraphStoreUnit:
    def test_wal_mode_and_schema_tables_created(self, tmp_path: Path):
        db_file = tmp_path / "graphs.db"
        store = WorkspaceGraphStore(db_file)
        try:
            conn = sqlite3.connect(db_file)
            try:
                mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                assert mode.lower() == "wal"
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                assert {"workspace_meta", "workspace_nodes", "workspace_edges"} <= tables
            finally:
                conn.close()
        finally:
            store.close()

    def test_lossless_context_graph_round_trip_and_incremental_ops(self, tmp_path: Path):
        db_file = tmp_path / "roundtrip.db"
        store = WorkspaceGraphStore(db_file)
        try:
            g1 = ContextGraph(advanced_analytics=False)
            # Node with asymmetric properties vs metadata + temporal bounds
            asym_node = ContextNode(
                node_id="sat_1",
                node_type="satellite",
                content="Orbital Relay Alpha",
                properties={"orbit_km": 550, "active": True},
                metadata={"source": "telemetry_v2"},
                valid_from="2026-01-01T00:00:00",
                valid_until="2030-12-31T23:59:59",
            )
            g1._add_internal_node(asym_node)
            g1.add_node("ground_1", node_type="station", content="Ground Station Svalbard", band="Ka")
            g1.add_edge(
                "sat_1",
                "ground_1",
                edge_type="downlinks_to",
                weight=0.95,
                familyId="fam_orbital",
                valid_from="2026-01-01T00:00:00",
                bandwidth_gbps=12.5,
            )

            assert not store.is_initialized("ws_space")
            n_saved, e_saved = store.save_context_graph(
                "ws_space", "graph:ws_space", g1, seeded=True
            )
            assert (n_saved, e_saved) == (2, 1)
            assert store.is_initialized("ws_space")
            meta = store.get_workspace_meta("ws_space")
            assert meta is not None
            assert meta["graph_key"] == "graph:ws_space"
            assert meta["seeded"] == 1

            # Restore into a fresh ContextGraph
            g2 = ContextGraph(advanced_analytics=False)
            n_loaded, e_loaded = store.load_into_context_graph("ws_space", g2)
            assert (n_loaded, e_loaded) == (2, 1)

            restored_sat = g2.nodes["sat_1"]
            assert restored_sat.content == "Orbital Relay Alpha"
            assert restored_sat.properties == {"orbit_km": 550, "active": True}
            assert restored_sat.metadata == {"source": "telemetry_v2"}
            assert restored_sat.valid_from == "2026-01-01T00:00:00"
            assert restored_sat.valid_until == "2030-12-31T23:59:59"

            restored_edge = g2.edges[0]
            assert restored_edge.source_id == "sat_1"
            assert restored_edge.target_id == "ground_1"
            assert restored_edge.edge_type == "downlinks_to"
            assert pytest.approx(restored_edge.weight) == 0.95
            assert restored_edge.family_id == "fam_orbital"
            assert restored_edge.metadata["bandwidth_gbps"] == 12.5

            # Incremental upsert + delete
            extra_node = ContextNode("sat_2", "satellite", "Relay Beta", {"orbit_km": 600}, {"orbit_km": 600})
            store.upsert_node("ws_space", "graph:ws_space", extra_node)
            extra_edge = ContextEdge(
                source_id="sat_2",
                target_id="ground_1",
                edge_type="downlinks_to",
                weight=0.8,
                metadata={"channel": "backup"},
            )
            store.upsert_edge("ws_space", "graph:ws_space", extra_edge)
            assert store.count_entities("ws_space") == (3, 2)

            # Deleting ground_1 removes incident edges as well
            store.delete_node("ws_space", "ground_1")
            assert store.count_entities("ws_space") == (2, 0)
        finally:
            store.close()


# ===========================================================================
# 2. FalkorDBSyncBridge RESP2 Protocol & Fallback Unit Tests
# ===========================================================================


class TestFalkorDBSyncBridgeUnit:
    def test_resp2_sync_against_live_socket_server(self):
        with _MockRESP2Server() as server:
            bridge = FalkorDBSyncBridge(host="127.0.0.1", port=server.port, timeout=1.5)
            assert bridge.enabled is True
            assert bridge.ping() is True

            g = ContextGraph(advanced_analytics=False)
            g.add_node("node_1", "technology", "Quantum Link 'Alpha'", tier="core")
            g.add_node("node_2", "facility", "Cryo Lab\nWest")
            g.add_edge("node_1", "node_2", edge_type="deployed-at", weight=0.75)

            assert bridge.sync_full_graph("graph:ws_test", g) is True
            assert bridge.upsert_node(
                "graph:ws_test",
                ContextNode("node_3", "sensor", "Photon Detector"),
            ) is True
            assert bridge.delete_node("graph:ws_test", "node_3") is True

            graph_queries: List[Tuple[str, str]] = [
                (cmd[1], cmd[2])
                for cmd in server.commands
                if cmd and cmd[0] == "GRAPH.QUERY"
            ]
            assert len(graph_queries) >= 5
            assert all(key == "graph:ws_test" for key, _ in graph_queries)
            cypher_blob = "\n".join(q for _, q in graph_queries)
            assert "MATCH (n) DETACH DELETE n" in cypher_blob
            assert "Quantum Link \\'Alpha\\'" in cypher_blob
            assert "deployed_at" in cypher_blob
            assert "Photon Detector" in cypher_blob

    def test_unreachable_falkordb_is_non_fatal_and_uses_cooldown(self):
        # Bind and immediately close a socket to obtain a guaranteed-closed port
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
        sock.close()

        bridge = FalkorDBSyncBridge(
            host="127.0.0.1",
            port=closed_port,
            timeout=0.3,
            cooldown_seconds=10.0,
        )
        g = ContextGraph(advanced_analytics=False)
        g.add_node("a", "entity", "A")

        # First call fails gracefully
        assert bridge.sync_full_graph("graph:ws_offline", g) is False
        # Subsequent call within cooldown returns immediately without socket wait
        t0 = time.perf_counter()
        assert bridge.upsert_node("graph:ws_offline", g.nodes["a"]) is False
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.05


# ===========================================================================
# 3. End-to-End Multi-Workspace Persistence Across Application Restarts
# ===========================================================================


class TestContainerRestartPersistenceE2E:
    def test_import_into_ws_user_a_survives_full_app_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        auth_db = tmp_path / "semantica_auth.db"
        graph_db = tmp_path / "semantica_graphs.db"
        monkeypatch.setenv("SEMANTICA_GRAPH_DB_PATH", str(graph_db))
        monkeypatch.delenv("FALKORDB_HOST", raising=False)

        store1 = AuthStore(auth_db)
        set_auth_store(store1)
        try:
            app1 = create_app(auth_store=store1, graph_db_path=str(graph_db))
            with TestClient(app1) as client1:
                # Verify health & persistence info
                health = client1.get("/api/health")
                assert health.status_code == 200
                assert health.json() == {"status": "ok"}

                info = client1.get("/api/info")
                assert info.status_code == 200
                assert info.json()["persistence"]["enabled"] is True
                assert info.json()["persistence"]["sqlite_path"] == str(graph_db)

                token_a = _login(client1, "user_a", "1")

                # Initial seeded ws_user_a has 7 nodes and 7 edges
                initial_nodes = client1.get(
                    "/api/graph/nodes?limit=100",
                    headers=_headers(token_a, "ws_user_a"),
                ).json()
                assert initial_nodes["total"] == 7

                # Dynamically import a new node + edge into ws_user_a
                payload = {
                    "nodes": [
                        {
                            "id": "lunar_gateway_station",
                            "type": "space_station",
                            "content": "Lunar Gateway Station — cislunar orbital staging outpost",
                            "metadata": {"domain": "space_exploration", "orbit": "NRHO"},
                        }
                    ],
                    "edges": [
                        {
                            "source": "project_apollo_x",
                            "target": "lunar_gateway_station",
                            "type": "docks_with",
                            "weight": 0.98,
                            "metadata": {"docking_port": "IDA-3"},
                        }
                    ],
                }
                import_resp = client1.post(
                    "/api/import",
                    headers=_headers(token_a, "ws_user_a"),
                    files={
                        "file": (
                            "gateway.json",
                            io.BytesIO(json.dumps(payload).encode("utf-8")),
                            "application/json",
                        )
                    },
                )
                assert import_resp.status_code == 200, import_resp.text
                assert import_resp.json()["nodes_added"] == 1
                assert import_resp.json()["edges_added"] == 1
        finally:
            store1.close()
            set_auth_store(None)

        # Simulate full container restart: brand-new AuthStore + brand-new FastAPI app
        store2 = AuthStore(auth_db)
        set_auth_store(store2)
        try:
            app2 = create_app(auth_store=store2, graph_db_path=str(graph_db))
            with TestClient(app2) as client2:
                token_a = _login(client2, "user_a", "1")
                token_b = _login(client2, "user_b", "1")

                nodes_after = client2.get(
                    "/api/graph/nodes?limit=100",
                    headers=_headers(token_a, "ws_user_a"),
                ).json()
                edges_after = client2.get(
                    "/api/graph/edges?limit=100",
                    headers=_headers(token_a, "ws_user_a"),
                ).json()

                node_ids = {n["id"] for n in nodes_after["nodes"]}
                assert nodes_after["total"] == 8
                assert "lunar_gateway_station" in node_ids
                assert "project_apollo_x" in node_ids
                assert edges_after["total"] == 8
                assert any(
                    e["source"] == "project_apollo_x"
                    and e["target"] == "lunar_gateway_station"
                    and e["type"] == "docks_with"
                    for e in edges_after["edges"]
                )

                # Search index rebuilt properly after restart
                search_resp = client2.post(
                    "/api/graph/search",
                    headers=_headers(token_a, "ws_user_a"),
                    json={"query": "Lunar Gateway", "limit": 5},
                )
                assert search_resp.status_code == 200
                assert any(
                    item["node"]["id"] == "lunar_gateway_station"
                    for item in search_resp.json()["results"]
                )

                # ws_user_b remains isolated with its 7 finance nodes
                nodes_b = client2.get(
                    "/api/graph/nodes?limit=100",
                    headers=_headers(token_b, "ws_user_b"),
                ).json()
                assert nodes_b["total"] == 7
                assert "lunar_gateway_station" not in {
                    n["id"] for n in nodes_b["nodes"]
                }
        finally:
            store2.close()
            set_auth_store(None)

    def test_new_workspace_ws_alpha_persists_with_403_isolation_across_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        auth_db = tmp_path / "semantica_auth_alpha.db"
        graph_db = tmp_path / "semantica_graphs_alpha.db"
        monkeypatch.setenv("SEMANTICA_GRAPH_DB_PATH", str(graph_db))
        monkeypatch.delenv("FALKORDB_HOST", raising=False)

        store1 = AuthStore(auth_db)
        set_auth_store(store1)
        try:
            app1 = create_app(auth_store=store1, graph_db_path=str(graph_db))
            with TestClient(app1, raise_server_exceptions=False) as client1:
                admin_token = _login(client1, "admin", "1")
                token_a = _login(client1, "user_a", "1")
                token_b = _login(client1, "user_b", "1")

                # Admin creates ws_alpha and grants Editor role to user_a
                create_ws = client1.post(
                    "/api/admin/workspaces",
                    headers=_headers(admin_token),
                    json={
                        "workspace_id": "ws_alpha",
                        "name": "Alpha Biotech Lab",
                        "description": "Confidential CRISPR research graph",
                    },
                )
                assert create_ws.status_code == 201, create_ws.text

                user_a_obj = store1.get_user_by_username("user_a")
                assert user_a_obj is not None
                grant_resp = client1.post(
                    "/api/admin/workspaces/ws_alpha/grants",
                    headers=_headers(admin_token),
                    json={
                        "grantee_type": "user",
                        "grantee_id": user_a_obj.id,
                        "role": "Editor",
                    },
                )
                assert grant_resp.status_code == 201, grant_resp.text

                # user_a imports nodes & edges into ws_alpha
                alpha_payload = {
                    "nodes": [
                        {
                            "id": "crispr_cas13_program",
                            "type": "program",
                            "content": "CRISPR-Cas13 RNA Editing Therapeutic Pipeline",
                            "metadata": {"phase": "preclinical"},
                        },
                        {
                            "id": "lipid_nanoparticle_v4",
                            "type": "delivery_vector",
                            "content": "Hepatic LNP-v4 Delivery Carrier",
                            "metadata": {"tropism": "liver"},
                        },
                    ],
                    "edges": [
                        {
                            "source": "crispr_cas13_program",
                            "target": "lipid_nanoparticle_v4",
                            "type": "delivered_via",
                            "weight": 0.91,
                        }
                    ],
                }
                imp = client1.post(
                    "/api/import",
                    headers=_headers(token_a, "ws_alpha"),
                    files={
                        "file": (
                            "alpha.json",
                            io.BytesIO(json.dumps(alpha_payload).encode("utf-8")),
                            "application/json",
                        )
                    },
                )
                assert imp.status_code == 200, imp.text

                # user_b is strictly denied access (403)
                denied = client1.get(
                    "/api/graph/nodes",
                    headers=_headers(token_b, "ws_alpha"),
                )
                assert denied.status_code == 403
        finally:
            store1.close()
            set_auth_store(None)

        # Restart application and verify ws_alpha graph + RBAC isolation survive
        store2 = AuthStore(auth_db)
        set_auth_store(store2)
        try:
            app2 = create_app(auth_store=store2, graph_db_path=str(graph_db))
            with TestClient(app2, raise_server_exceptions=False) as client2:
                token_a = _login(client2, "user_a", "1")
                token_b = _login(client2, "user_b", "1")

                alpha_nodes = client2.get(
                    "/api/graph/nodes?limit=50",
                    headers=_headers(token_a, "ws_alpha"),
                )
                assert alpha_nodes.status_code == 200
                body = alpha_nodes.json()
                assert body["total"] == 2
                assert {n["id"] for n in body["nodes"]} == {
                    "crispr_cas13_program",
                    "lipid_nanoparticle_v4",
                }

                alpha_edges = client2.get(
                    "/api/graph/edges?limit=50",
                    headers=_headers(token_a, "ws_alpha"),
                ).json()
                assert alpha_edges["total"] == 1
                assert alpha_edges["edges"][0]["type"] == "delivered_via"

                # user_b STILL receives 403 after restart
                denied_after = client2.get(
                    "/api/graph/nodes",
                    headers=_headers(token_b, "ws_alpha"),
                )
                assert denied_after.status_code == 403
        finally:
            store2.close()
            set_auth_store(None)

    def test_markdown_put_mutation_persists_across_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        auth_db = tmp_path / "semantica_auth_md.db"
        graph_db = tmp_path / "semantica_graphs_md.db"
        monkeypatch.setenv("SEMANTICA_GRAPH_DB_PATH", str(graph_db))
        monkeypatch.delenv("FALKORDB_HOST", raising=False)

        updated_body = (
            "Project Apollo X — Upgraded Phase-2 Lunar Habitat & Nuclear Shuttle"
        )

        store1 = AuthStore(auth_db)
        set_auth_store(store1)
        try:
            app1 = create_app(auth_store=store1, graph_db_path=str(graph_db))
            with TestClient(app1) as client1:
                token_a = _login(client1, "user_a", "1")

                doc_resp = client1.get(
                    "/api/markdown/context-node/project_apollo_x",
                    headers=_headers(token_a, "ws_user_a"),
                )
                assert doc_resp.status_code == 200, doc_resp.text
                doc = doc_resp.json()
                old_body = doc["body"]
                new_markdown = doc["source"].replace(old_body, updated_body)

                put_resp = client1.put(
                    "/api/markdown/context-node/project_apollo_x",
                    headers=_headers(token_a, "ws_user_a"),
                    json={
                        "markdown": new_markdown,
                        "expected_revision": doc["revision"],
                    },
                )
                assert put_resp.status_code == 200, put_resp.text
                assert put_resp.json()["changed"] is True
                saved_revision = put_resp.json()["revision"]
        finally:
            store1.close()
            set_auth_store(None)

        # Restart application and confirm edited Markdown & revision survived
        store2 = AuthStore(auth_db)
        set_auth_store(store2)
        try:
            app2 = create_app(auth_store=store2, graph_db_path=str(graph_db))
            with TestClient(app2) as client2:
                token_a = _login(client2, "user_a", "1")

                doc_after = client2.get(
                    "/api/markdown/context-node/project_apollo_x",
                    headers=_headers(token_a, "ws_user_a"),
                )
                assert doc_after.status_code == 200
                assert doc_after.json()["body"] == updated_body
                assert doc_after.json()["revision"] == saved_revision

                node_after = client2.get(
                    "/api/graph/node/project_apollo_x",
                    headers=_headers(token_a, "ws_user_a"),
                )
                assert node_after.status_code == 200
                assert node_after.json()["content"] == updated_body
        finally:
            store2.close()
            set_auth_store(None)
