"""
Integration Test Suite: Real User Lifecycle & Security Boundary Verification
=============================================================================

Simulates real-world user workflows and strict boundary enforcement:
  1. Real user password login authentication (user_b / 1) -> JWT access token.
  2. Create personal API Key via POST /api/auth/keys (mimicking UI modal action).
  3. REST API call with API Key to dynamically import brand-new domain data into ws_user_b.
  4. Query & search verification of dynamically imported data (GET /api/graph/nodes & POST /api/graph/search).
  5. Underlying persistence verification directly against SQLite WAL workspace_nodes & workspace_edges tables.
  6. Boundary 1: Cross-tenant write interception (user_b API Key -> ws_user_a: 403 Forbidden).
  7. Boundary 2: Cross-tenant read interception (user_b API Key -> ws_user_a: 403 Forbidden).
  8. Boundary 3: Unauthorized admin endpoints interception (user_b API Key -> /api/admin/*: 403 Forbidden).
  9. Boundary 4: Instant API key revocation (DELETE /api/auth/keys/{id} -> immediate 401 Unauthorized).
 10. Boundary 5: Defense against wrong passwords and forged/invalid credentials (401 Unauthorized).
 11. Custom password new user complete lifecycle (Admin creates user with complex password -> login -> API key -> dynamic graph write -> isolation).
"""

import io
import json
import os
import sqlite3
import pytest
from starlette.testclient import TestClient

from semantica.auth import AuthStore, set_auth_store
from semantica.explorer.app import create_app


@pytest.fixture(scope="module")
def env_setup(tmp_path_factory):
    """Module-scoped isolated AuthStore and graph database paths."""
    tmp_dir = tmp_path_factory.mktemp("real_user_lifecycle")
    auth_db = tmp_dir / "test_auth.db"
    graph_db = tmp_dir / "test_graphs.db"

    old_env = os.environ.copy()
    os.environ["SEMANTICA_AUTH_DB_PATH"] = str(auth_db)
    os.environ["SEMANTICA_GRAPH_DB_PATH"] = str(graph_db)
    os.environ["SEMANTICA_ALLOW_ANONYMOUS"] = "false"
    os.environ["SEMANTICA_ADMIN_PASSWORD"] = "1"
    os.environ["SEMANTICA_TEST_PASSWORD"] = "1"
    os.environ.pop("SEMANTICA_API_KEY", None)
    os.environ.pop("FALKORDB_HOST", None)

    store = AuthStore(auth_db)
    set_auth_store(store)

    app = create_app(auth_store=store, graph_db_path=str(graph_db))

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {
            "client": client,
            "auth_store": store,
            "auth_db_path": auth_db,
            "graph_db_path": graph_db,
        }

    store.close()
    set_auth_store(None)
    os.environ.clear()
    os.environ.update(old_env)


class TestRealUserLifecycleAndBoundary:
    """End-to-end real user lifecycle and boundary testing suite."""

    # Shared state between lifecycle steps
    user_b_token: str = ""
    user_b_key_id: str = ""
    user_b_raw_key: str = ""
    admin_token: str = ""

    def test_01_real_user_password_login(self, env_setup):
        """用例 1: 真实用户密码登录认证 (user_b / 1) -> 获取 JWT access_token"""
        client: TestClient = env_setup["client"]

        resp = client.post(
            "/api/auth/login",
            json={"username": "user_b", "password": "1", "login_type": "local"},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()

        assert "access_token" in data
        assert data.get("token_type") == "bearer"
        assert data["user"]["username"] == "user_b"
        assert data["user"]["global_role"] == "user"
        assert "ws_user_b" in data["user"]["authorized_workspaces"]
        assert "ws_user_a" not in data["user"]["authorized_workspaces"]

        TestRealUserLifecycleAndBoundary.user_b_token = data["access_token"]

    def test_02_create_personal_api_key(self, env_setup):
        """用例 2: 创建个人 API 密钥 (模拟用户在 UI 弹窗中生成 API Key)"""
        client: TestClient = env_setup["client"]
        token = TestRealUserLifecycleAndBoundary.user_b_token
        assert token, "user_b_token must be set by test_01"

        resp = client.post(
            "/api/auth/keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "UserB_Automation_Key"},
        )
        assert resp.status_code == 201, f"Create key failed: {resp.text}"
        data = resp.json()

        assert data["name"] == "UserB_Automation_Key"
        assert "id" in data
        assert "raw_key" in data
        assert data["raw_key"].startswith("sem_")
        assert not data["is_service"]
        # Must inherit user_b's workspace
        assert "ws_user_b" in data["allowed_workspaces"]
        assert "ws_user_a" not in data["allowed_workspaces"]

        TestRealUserLifecycleAndBoundary.user_b_key_id = data["id"]
        TestRealUserLifecycleAndBoundary.user_b_raw_key = data["raw_key"]

    def test_03_api_key_import_dynamic_data(self, env_setup):
        """用例 3: 使用 API Key 调用 REST API 动态写入全新图谱数据 (非预置灌水)"""
        client: TestClient = env_setup["client"]
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key
        assert raw_key, "user_b_raw_key must be set by test_02"

        dynamic_payload = {
            "nodes": [
                {
                    "id": "fin_risk_node_101",
                    "type": "RiskModel",
                    "properties": {
                        "content": "FinRisk Basel III Capital Adequacy Model 101",
                        "regulatory_framework": "Basel-III",
                        "risk_tier": "Tier-1",
                    },
                },
                {
                    "id": "fin_risk_node_102",
                    "type": "AuditPolicy",
                    "properties": {
                        "content": "Liquidity Coverage Ratio Audit Policy 102",
                        "audit_frequency": "Daily",
                        "enforcement": "Strict",
                    },
                },
                {
                    "id": "fin_risk_node_103",
                    "type": "Counterparty",
                    "properties": {
                        "content": "Global Clearing Counterparty 103",
                        "credit_rating": "AAA",
                        "jurisdiction": "EU",
                    },
                },
            ],
            "edges": [
                {
                    "source": "fin_risk_node_101",
                    "target": "fin_risk_node_102",
                    "type": "GOVERNED_BY",
                    "weight": 1.0,
                    "properties": {"mandate": "capital_compliance"},
                },
                {
                    "source": "fin_risk_node_101",
                    "target": "fin_risk_node_103",
                    "type": "APPLIES_TO",
                    "weight": 0.95,
                    "properties": {"exposure_cap_pct": 25},
                },
            ],
        }

        file_bytes = json.dumps(dynamic_payload).encode("utf-8")
        resp = client.post(
            "/api/import",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_b",
            },
            files={
                "file": ("fin_risk_model_101.json", io.BytesIO(file_bytes), "application/json")
            },
        )
        assert resp.status_code == 200, f"Import failed: {resp.text}"
        import_data = resp.json()
        assert import_data.get("status") == "success"
        assert import_data.get("nodes_added") == 3
        assert import_data.get("edges_added") == 2

    def test_04_verify_read_and_search_dynamic_data(self, env_setup):
        """用例 4: 动态写入数据的读取与检索验证"""
        client: TestClient = env_setup["client"]
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key

        # 4.1 Read nodes with API key
        resp = client.get(
            "/api/graph/nodes?limit=100",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_b",
            },
        )
        assert resp.status_code == 200, f"Read nodes failed: {resp.text}"
        nodes_data = resp.json()
        node_ids = {n["id"] for n in nodes_data.get("nodes", [])}

        assert "fin_risk_node_101" in node_ids
        assert "fin_risk_node_102" in node_ids
        assert "fin_risk_node_103" in node_ids

        # 4.2 Search dynamic nodes
        search_resp = client.post(
            "/api/graph/search",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_b",
            },
            json={"query": "Basel III Capital Adequacy", "limit": 10},
        )
        assert search_resp.status_code == 200, f"Search failed: {search_resp.text}"
        search_data = search_resp.json()
        result_node_ids = [r["node"]["id"] for r in search_data.get("results", [])]
        assert "fin_risk_node_101" in result_node_ids

    def test_05_underlying_sqlite_persistence_verification(self, env_setup):
        """用例 5: 底层持久化核验 (检查 SQLite WAL workspace_nodes 表中的物理写入)"""
        graph_db_path = env_setup["graph_db_path"]

        conn = sqlite3.connect(str(graph_db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT node_id, node_type, properties_json
                FROM workspace_nodes
                WHERE workspace_id = 'ws_user_b' AND node_id LIKE 'fin_risk_node_%'
                ORDER BY node_id ASC
                """
            )
            rows = cursor.fetchall()
            assert len(rows) == 3, f"Expected 3 persisted dynamic nodes, found {len(rows)}"

            ids = [r[0] for r in rows]
            types = [r[1] for r in rows]
            assert ids == ["fin_risk_node_101", "fin_risk_node_102", "fin_risk_node_103"]
            assert types == ["RiskModel", "AuditPolicy", "Counterparty"]

            # Verify edges persisted
            cursor.execute(
                """
                SELECT source_id, target_id, edge_type
                FROM workspace_edges
                WHERE workspace_id = 'ws_user_b' AND source_id = 'fin_risk_node_101'
                ORDER BY target_id ASC
                """
            )
            edge_rows = cursor.fetchall()
            assert len(edge_rows) == 2
            assert edge_rows[0][0] == "fin_risk_node_101"
            assert edge_rows[0][1] == "fin_risk_node_102"
            assert edge_rows[0][2] == "GOVERNED_BY"
            assert edge_rows[1][1] == "fin_risk_node_103"
            assert edge_rows[1][2] == "APPLIES_TO"
        finally:
            conn.close()

    def test_06_boundary_cross_tenant_write_intercepted(self, env_setup):
        """用例 6: 边界测试 1 —— 跨租户写入拦截 (user_b API Key -> ws_user_a: 403 Forbidden)"""
        client: TestClient = env_setup["client"]
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key

        malicious_payload = {
            "nodes": [
                {
                    "id": "cross_tenant_exploit_node",
                    "type": "Exploit",
                    "properties": {"content": "Unauthorized injection attempt"},
                }
            ],
            "edges": [],
        }
        file_bytes = json.dumps(malicious_payload).encode("utf-8")

        resp = client.post(
            "/api/import",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_a",
            },
            files={
                "file": ("exploit.json", io.BytesIO(file_bytes), "application/json")
            },
        )
        assert resp.status_code == 403, (
            f"Expected 403 Forbidden on cross-tenant write, got {resp.status_code}: {resp.text}"
        )

    def test_07_boundary_cross_tenant_read_intercepted(self, env_setup):
        """用例 7: 边界测试 2 —— 跨租户读取拦截 (user_b API Key -> ws_user_a: 403 Forbidden)"""
        client: TestClient = env_setup["client"]
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key

        resp = client.get(
            "/api/graph/nodes",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_a",
            },
        )
        assert resp.status_code == 403, (
            f"Expected 403 Forbidden on cross-tenant read, got {resp.status_code}: {resp.text}"
        )

    def test_08_boundary_admin_endpoints_intercepted(self, env_setup):
        """用例 8: 边界测试 3 —— 越权管理接口拦截 (普通用户 API Key 访问 /api/admin/*: 403 Forbidden)"""
        client: TestClient = env_setup["client"]
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key

        resp1 = client.get(
            "/api/admin/keys",
            headers={"X-API-Key": raw_key},
        )
        assert resp1.status_code == 403, (
            f"Expected 403 on /api/admin/keys for normal user key, got {resp1.status_code}"
        )

        resp2 = client.get(
            "/api/admin/users/external",
            headers={"X-API-Key": raw_key},
        )
        assert resp2.status_code == 403, (
            f"Expected 403 on /api/admin/users/external for normal user key, got {resp2.status_code}"
        )

    def test_09_boundary_instant_key_revocation(self, env_setup):
        """用例 9: 边界测试 4 —— 密钥即时吊销失效 (DELETE /api/auth/keys/{id} -> 401 Unauthorized)"""
        client: TestClient = env_setup["client"]
        token = TestRealUserLifecycleAndBoundary.user_b_token
        key_id = TestRealUserLifecycleAndBoundary.user_b_key_id
        raw_key = TestRealUserLifecycleAndBoundary.user_b_raw_key

        # 9.1 Revoke the key
        del_resp = client.delete(
            f"/api/auth/keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert del_resp.status_code == 200, f"Revoke key failed: {del_resp.text}"

        # 9.2 Immediately re-try access with the revoked key
        call_resp = client.get(
            "/api/graph/nodes",
            headers={
                "X-API-Key": raw_key,
                "X-Workspace-ID": "ws_user_b",
            },
        )
        assert call_resp.status_code == 401, (
            f"Expected 401 Unauthorized on revoked key, got {call_resp.status_code}: {call_resp.text}"
        )

    def test_10_boundary_invalid_credentials_defense(self, env_setup):
        """用例 10: 边界测试 5 —— 错误密码与无效凭证防御 (401 Unauthorized)"""
        client: TestClient = env_setup["client"]

        # 10.1 Wrong password login
        wrong_login = client.post(
            "/api/auth/login",
            json={"username": "user_b", "password": "wrong_pass_123", "login_type": "local"},
        )
        assert wrong_login.status_code == 401, (
            f"Expected 401 on wrong password, got {wrong_login.status_code}"
        )

        # 10.2 Forged / non-existent API Key
        forged_key_resp = client.get(
            "/api/graph/nodes",
            headers={
                "X-API-Key": "sk-fake-invalid-token-12345678",
                "X-Workspace-ID": "ws_user_b",
            },
        )
        assert forged_key_resp.status_code == 401, (
            f"Expected 401 on forged key, got {forged_key_resp.status_code}"
        )

        # 10.3 Unauthenticated call to write endpoint
        dummy_payload = {"nodes": [], "edges": []}
        unauth_resp = client.post(
            "/api/import",
            headers={"X-Workspace-ID": "ws_user_b"},
            files={
                "file": (
                    "test.json",
                    io.BytesIO(json.dumps(dummy_payload).encode("utf-8")),
                    "application/json",
                )
            },
        )
        assert unauth_resp.status_code == 401, (
            f"Expected 401 on unauthenticated call, got {unauth_resp.status_code}"
        )

    def test_11_custom_password_user_full_lifecycle(self, env_setup):
        """用例 11: 自定义密码新用户完整闭环 (创建用户 -> 复杂密码登录 -> API Key -> 动态写图 -> 隔离验证)"""
        client: TestClient = env_setup["client"]

        # 11.1 Admin login
        admin_login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "1", "login_type": "local"},
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 11.2 Admin creates new user with complex password
        create_user_resp = client.post(
            "/api/admin/users/external",
            headers=admin_headers,
            json={
                "username": "custom_user",
                "password": "CustomPass@2026!",
                "display_name": "自定义企业用户",
                "email": "custom_user@example.com",
                "global_role": "user",
            },
        )
        assert create_user_resp.status_code == 201, f"Create user failed: {create_user_resp.text}"

        # 11.3 Admin creates dedicated workspace ws_custom
        create_ws_resp = client.post(
            "/api/admin/workspaces",
            headers=admin_headers,
            json={
                "name": "自定义企业空间",
                "workspace_id": "ws_custom",
                "description": "Dedicated Workspace for Custom User",
            },
        )
        assert create_ws_resp.status_code == 201, f"Create workspace failed: {create_ws_resp.text}"

        # 11.4 Admin grants custom_user Admin role on ws_custom
        grant_resp = client.post(
            "/api/admin/workspaces/ws_custom/grants",
            headers=admin_headers,
            json={
                "grantee_type": "user",
                "grantee_id": "custom_user",
                "role": "Admin",
            },
        )
        assert grant_resp.status_code == 201, f"Grant failed: {grant_resp.text}"

        # 11.5 custom_user logs in with custom password
        custom_login = client.post(
            "/api/auth/login",
            json={
                "username": "custom_user",
                "password": "CustomPass@2026!",
                "login_type": "local",
            },
        )
        assert custom_login.status_code == 200, f"Custom user login failed: {custom_login.text}"
        custom_data = custom_login.json()
        custom_token = custom_data["access_token"]
        assert "ws_custom" in custom_data["user"]["authorized_workspaces"]
        custom_headers = {"Authorization": f"Bearer {custom_token}"}

        # 11.6 custom_user creates personal API Key
        create_key_resp = client.post(
            "/api/auth/keys",
            headers=custom_headers,
            json={"name": "CustomUser_Automation_Key"},
        )
        assert create_key_resp.status_code == 201, f"Create custom key failed: {create_key_resp.text}"
        custom_key_data = create_key_resp.json()
        custom_raw_key = custom_key_data["raw_key"]
        assert "ws_custom" in custom_key_data["allowed_workspaces"]

        # 11.7 custom_user writes dynamic graph data via API Key
        custom_graph_payload = {
            "nodes": [
                {
                    "id": "custom_asset_001",
                    "type": "EnterpriseAsset",
                    "properties": {
                        "content": "Enterprise Cloud Sovereign Gateway 001",
                        "zone": "ap-southeast-1",
                    },
                },
                {
                    "id": "custom_asset_002",
                    "type": "SecurityPolicy",
                    "properties": {
                        "content": "Zero-Trust Microsegmentation Policy 002",
                        "status": "active",
                    },
                },
            ],
            "edges": [
                {
                    "source": "custom_asset_001",
                    "target": "custom_asset_002",
                    "type": "SECURED_BY",
                    "weight": 1.0,
                }
            ],
        }
        file_bytes = json.dumps(custom_graph_payload).encode("utf-8")
        import_custom_resp = client.post(
            "/api/import",
            headers={
                "X-API-Key": custom_raw_key,
                "X-Workspace-ID": "ws_custom",
            },
            files={
                "file": ("custom_asset.json", io.BytesIO(file_bytes), "application/json")
            },
        )
        assert import_custom_resp.status_code == 200, (
            f"Import custom data failed: {import_custom_resp.text}"
        )
        assert import_custom_resp.json()["nodes_added"] == 2

        # 11.8 custom_user reads own nodes
        read_custom = client.get(
            "/api/graph/nodes",
            headers={
                "X-API-Key": custom_raw_key,
                "X-Workspace-ID": "ws_custom",
            },
        )
        assert read_custom.status_code == 200
        c_node_ids = {n["id"] for n in read_custom.json().get("nodes", [])}
        assert "custom_asset_001" in c_node_ids
        assert "custom_asset_002" in c_node_ids

        # 11.9 custom_user attempts cross-tenant read of ws_user_a -> 403 Forbidden
        custom_cross_a = client.get(
            "/api/graph/nodes",
            headers={
                "X-API-Key": custom_raw_key,
                "X-Workspace-ID": "ws_user_a",
            },
        )
        assert custom_cross_a.status_code == 403, (
            f"Expected 403 for custom_user accessing ws_user_a, got {custom_cross_a.status_code}"
        )

        # 11.10 user_b attempts cross-tenant read of ws_custom -> 403 Forbidden
        user_b_relogin = client.post(
            "/api/auth/login",
            json={"username": "user_b", "password": "1", "login_type": "local"},
        )
        user_b_tok = user_b_relogin.json()["access_token"]
        user_b_cross_custom = client.get(
            "/api/graph/nodes",
            headers={
                "Authorization": f"Bearer {user_b_tok}",
                "X-Workspace-ID": "ws_custom",
            },
        )
        assert user_b_cross_custom.status_code == 403, (
            f"Expected 403 for user_b accessing ws_custom, got {user_b_cross_custom.status_code}"
        )
