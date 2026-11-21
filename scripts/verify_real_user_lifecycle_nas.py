#!/usr/bin/env python3
"""
NAS Real User Lifecycle & Security Boundary Live Verification Script
=====================================================================

Executes 11 end-to-end real user scenarios and boundary checks against
a live running Semantica instance (default: http://192.168.1.15:8000).

Scenarios:
  1. Real user password login (user_b / 1) -> JWT access token.
  2. Create personal API Key via POST /api/auth/keys (mimicking UI modal).
  3. API Key REST API call to dynamically import new domain data into ws_user_b.
  4. Query & search verification of dynamically imported data.
  5. Underlying persistence & export verification on ws_user_b.
  6. Boundary 1: Cross-tenant write interception (user_b API Key -> ws_user_a: 403).
  7. Boundary 2: Cross-tenant read interception (user_b API Key -> ws_user_a: 403).
  8. Boundary 3: Unauthorized admin endpoints interception (/api/admin/*: 403).
  9. Boundary 4: Instant API key revocation (DELETE key -> 401 Unauthorized).
 10. Boundary 5: Wrong password and invalid credentials defense (401 Unauthorized).
 11. Custom password new user complete lifecycle (Admin creates user with complex password -> login -> key -> dynamic write -> isolation).
"""

import io
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install via pip install requests.")
    sys.exit(1)

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://192.168.1.15:8000"

# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS_COUNT = 0
FAIL_COUNT = 0


def log_step(step_num: int, title: str):
    print(f"\n{BOLD}{YELLOW}===================================================================={RESET}")
    print(f"{BOLD}{YELLOW}>> [Step {step_num}] {title}{RESET}")
    print(f"{BOLD}{YELLOW}===================================================================={RESET}")


def assert_status(resp: requests.Response, expected_status: Any, description: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    expected = [expected_status] if isinstance(expected_status, int) else expected_status
    if resp.status_code in expected:
        PASS_COUNT += 1
        print(f"  {GREEN}[PASS]{RESET} {description} -> HTTP {resp.status_code}")
    else:
        FAIL_COUNT += 1
        print(f"  {RED}[FAIL]{RESET} {description} -> Expected {expected}, got HTTP {resp.status_code}")
        try:
            err_detail = resp.json()
            print(f"         Detail: {err_detail}")
        except Exception:
            print(f"         Body: {resp.text[:300]}")
        sys.exit(1)


def assert_true(condition: bool, description: str, error_msg: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  {GREEN}[PASS]{RESET} {description}")
    else:
        FAIL_COUNT += 1
        print(f"  {RED}[FAIL]{RESET} {description}: {error_msg}")
        sys.exit(1)


def run_live_verification():
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    print(f"\n{BOLD}{CYAN}Target Live Endpoint: {BASE_URL}{RESET}\n")

    # -------------------------------------------------------------------------
    # Scenario 1: Real User Password Login Authentication (user_b / 1)
    # -------------------------------------------------------------------------
    log_step(1, "Real User Password Login Authentication (user_b / 1)")
    login_resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "user_b", "password": "1", "login_type": "local"},
    )
    assert_status(login_resp, 200, "POST /api/auth/login (user_b / 1)")
    user_b_data = login_resp.json()
    user_b_token = user_b_data.get("access_token")
    assert_true(bool(user_b_token), "Received valid JWT access_token")
    assert_true(user_b_data.get("user", {}).get("username") == "user_b", "Username is user_b")
    assert_true(user_b_data.get("user", {}).get("global_role") == "user", "Global role is user")
    assert_true("ws_user_b" in user_b_data.get("user", {}).get("authorized_workspaces", []), "ws_user_b in authorized_workspaces")
    assert_true("ws_user_a" not in user_b_data.get("user", {}).get("authorized_workspaces", []), "ws_user_a NOT in user_b workspaces")
    print(f"         User B ID: {user_b_data.get('user', {}).get('id')}")

    user_b_headers = {"Authorization": f"Bearer {user_b_token}"}

    # -------------------------------------------------------------------------
    # Scenario 2: Create Personal API Key (Mimicking UI Modal Action)
    # -------------------------------------------------------------------------
    log_step(2, "Create Personal API Key via POST /api/auth/keys")
    key_name = f"UserB_Live_Key_{int(time.time())}"
    create_key_resp = session.post(
        f"{BASE_URL}/api/auth/keys",
        headers=user_b_headers,
        json={"name": key_name},
    )
    assert_status(create_key_resp, 201, f"POST /api/auth/keys (name='{key_name}')")
    key_data = create_key_resp.json()
    user_b_key_id = key_data.get("id")
    user_b_raw_key = key_data.get("raw_key")
    assert_true(bool(user_b_key_id), "API Key ID generated")
    assert_true(bool(user_b_raw_key) and user_b_raw_key.startswith("sem_"), "Plaintext raw_key returned starting with 'sem_'")
    assert_true("ws_user_b" in key_data.get("allowed_workspaces", []), "Key strictly inherited ws_user_b")
    assert_true("ws_user_a" not in key_data.get("allowed_workspaces", []), "Key strictly excluded ws_user_a")
    print(f"         Key ID: {user_b_key_id}, Prefix: {key_data.get('key_prefix')}")

    # -------------------------------------------------------------------------
    # Scenario 3: API Key REST API Call to Dynamically Import Graph Data
    # -------------------------------------------------------------------------
    log_step(3, "API Key REST API Call: Dynamic Domain Data Import into ws_user_b")
    timestamp = int(time.time())
    node_1_id = f"fin_risk_live_{timestamp}_101"
    node_2_id = f"fin_risk_live_{timestamp}_102"
    node_3_id = f"fin_risk_live_{timestamp}_103"

    dynamic_payload = {
        "nodes": [
            {
                "id": node_1_id,
                "type": "RiskModel",
                "properties": {
                    "content": f"Live Basel III Capital Adequacy Model {timestamp}",
                    "framework": "Basel-III",
                    "risk_tier": "Tier-1",
                },
            },
            {
                "id": node_2_id,
                "type": "AuditPolicy",
                "properties": {
                    "content": f"Live Liquidity Coverage Ratio Policy {timestamp}",
                    "frequency": "Daily",
                },
            },
            {
                "id": node_3_id,
                "type": "Counterparty",
                "properties": {
                    "content": f"Live Global Clearing Counterparty {timestamp}",
                    "credit_rating": "AAA",
                },
            },
        ],
        "edges": [
            {
                "source": node_1_id,
                "target": node_2_id,
                "type": "GOVERNED_BY",
                "weight": 1.0,
            },
            {
                "source": node_1_id,
                "target": node_3_id,
                "type": "APPLIES_TO",
                "weight": 0.95,
            },
        ],
    }

    file_bytes = json.dumps(dynamic_payload).encode("utf-8")
    import_resp = session.post(
        f"{BASE_URL}/api/import",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_b",
        },
        files={
            "file": ("live_fin_risk.json", io.BytesIO(file_bytes), "application/json")
        },
    )
    assert_status(import_resp, 200, "POST /api/import with X-API-Key to ws_user_b")
    import_result = import_resp.json()
    assert_true(import_result.get("status") == "success", "Import status is success")
    assert_true(import_result.get("nodes_added") == 3, f"Added 3 dynamic nodes (got {import_result.get('nodes_added')})")
    assert_true(import_result.get("edges_added") == 2, f"Added 2 dynamic edges (got {import_result.get('edges_added')})")

    # -------------------------------------------------------------------------
    # Scenario 4: Query & Search Verification of Dynamically Imported Data
    # -------------------------------------------------------------------------
    log_step(4, "Query & Full-Text Search Verification of Dynamically Imported Data")
    nodes_resp = session.get(
        f"{BASE_URL}/api/graph/nodes?limit=100",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_b",
        },
    )
    assert_status(nodes_resp, 200, "GET /api/graph/nodes with X-API-Key on ws_user_b")
    nodes_list = nodes_resp.json().get("nodes", [])
    returned_ids = {n["id"] for n in nodes_list}
    assert_true(node_1_id in returned_ids, f"Dynamic node {node_1_id} present in nodes list")
    assert_true(node_2_id in returned_ids, f"Dynamic node {node_2_id} present in nodes list")
    assert_true(node_3_id in returned_ids, f"Dynamic node {node_3_id} present in nodes list")

    search_resp = session.post(
        f"{BASE_URL}/api/graph/search",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_b",
        },
        json={"query": f"Basel III Capital Adequacy Model {timestamp}", "limit": 10},
    )
    assert_status(search_resp, 200, "POST /api/graph/search with X-API-Key on ws_user_b")
    search_results = search_resp.json().get("results", [])
    hit_ids = [r["node"]["id"] for r in search_results]
    assert_true(node_1_id in hit_ids, f"Full-text search hit dynamically imported node {node_1_id}")

    # -------------------------------------------------------------------------
    # Scenario 5: Underlying Persistence & Export Verification on ws_user_b
    # -------------------------------------------------------------------------
    log_step(5, "Underlying Persistence & Export Verification on ws_user_b")
    info_resp = session.get(f"{BASE_URL}/api/info")
    assert_status(info_resp, 200, "GET /api/info (persistence diagnostic)")
    persistence_info = info_resp.json().get("persistence", {})
    assert_true(persistence_info.get("enabled") is True, "Persistence engine enabled")
    assert_true("ws_user_b" in persistence_info.get("persisted_workspaces", []), "ws_user_b in persisted_workspaces")
    print(f"         Storage backend: {persistence_info.get('backend')}, SQLite path: {persistence_info.get('sqlite_path')}")

    export_resp = session.post(
        f"{BASE_URL}/api/export",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_b",
            "Content-Type": "application/json",
        },
        json={"format": "json"},
    )
    assert_status(export_resp, 200, "POST /api/export ws_user_b as JSON snapshot")
    export_data = export_resp.json()
    exported_node_ids = {e["id"] for e in export_data.get("entities", [])}
    assert_true(node_1_id in exported_node_ids, "Dynamic node persisted into export snapshot")
    assert_true(node_2_id in exported_node_ids, "Dynamic node persisted into export snapshot")
    assert_true(node_3_id in exported_node_ids, "Dynamic node persisted into export snapshot")

    # -------------------------------------------------------------------------
    # Scenario 6: Boundary 1 —— Cross-Tenant Write Interception (403 Forbidden)
    # -------------------------------------------------------------------------
    log_step(6, "Boundary 1: Cross-Tenant Write Interception (user_b -> ws_user_a: 403 Forbidden)")
    exploit_payload = {
        "nodes": [{"id": f"unauthorized_injection_{timestamp}", "type": "Exploit", "properties": {}}],
        "edges": [],
    }
    exploit_bytes = json.dumps(exploit_payload).encode("utf-8")
    cross_write_resp = session.post(
        f"{BASE_URL}/api/import",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_a",
        },
        files={"file": ("exploit.json", io.BytesIO(exploit_bytes), "application/json")},
    )
    assert_status(cross_write_resp, 403, "User B API Key write into ws_user_a intercepted with 403 Forbidden")

    # -------------------------------------------------------------------------
    # Scenario 7: Boundary 2 —— Cross-Tenant Read Interception (403 Forbidden)
    # -------------------------------------------------------------------------
    log_step(7, "Boundary 2: Cross-Tenant Read Interception (user_b -> ws_user_a: 403 Forbidden)")
    cross_read_resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_a",
        },
    )
    assert_status(cross_read_resp, 403, "User B API Key read from ws_user_a intercepted with 403 Forbidden")

    # -------------------------------------------------------------------------
    # Scenario 8: Boundary 3 —— Unauthorized Admin Endpoints Interception (403 Forbidden)
    # -------------------------------------------------------------------------
    log_step(8, "Boundary 3: Unauthorized Admin Endpoints Interception (/api/admin/*: 403 Forbidden)")
    admin_keys_resp = session.get(
        f"{BASE_URL}/api/admin/keys",
        headers={"X-API-Key": user_b_raw_key},
    )
    assert_status(admin_keys_resp, 403, "User B API Key access to GET /api/admin/keys intercepted with 403 Forbidden")

    admin_users_resp = session.get(
        f"{BASE_URL}/api/admin/users/external",
        headers={"X-API-Key": user_b_raw_key},
    )
    assert_status(admin_users_resp, 403, "User B API Key access to GET /api/admin/users/external intercepted with 403 Forbidden")

    # -------------------------------------------------------------------------
    # Scenario 9: Boundary 4 —— Instant Key Revocation (401 Unauthorized)
    # -------------------------------------------------------------------------
    log_step(9, "Boundary 4: Instant API Key Revocation (DELETE key -> 401 Unauthorized)")
    revoke_resp = session.delete(
        f"{BASE_URL}/api/auth/keys/{user_b_key_id}",
        headers=user_b_headers,
    )
    assert_status(revoke_resp, 200, f"DELETE /api/auth/keys/{user_b_key_id}")
    assert_true(revoke_resp.json().get("status") == "revoked", "Revocation confirmation received")

    # Immediately attempt API call with revoked key
    revoked_call_resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={
            "X-API-Key": user_b_raw_key,
            "X-Workspace-ID": "ws_user_b",
        },
    )
    assert_status(revoked_call_resp, 401, "Revoked API key access immediately rejected with 401 Unauthorized")

    # -------------------------------------------------------------------------
    # Scenario 10: Boundary 5 —— Defense Against Wrong Password & Invalid Credentials
    # -------------------------------------------------------------------------
    log_step(10, "Boundary 5: Defense Against Wrong Password & Invalid Credentials")
    wrong_login = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "user_b", "password": "wrong_password_999", "login_type": "local"},
    )
    assert_status(wrong_login, 401, "Login with wrong password rejected with 401 Unauthorized")

    forged_key_resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"X-API-Key": "sk-fake-invalid-key-999999", "X-Workspace-ID": "ws_user_b"},
    )
    assert_status(forged_key_resp, 401, "Forged API key rejected with 401 Unauthorized")

    unauth_resp = session.post(
        f"{BASE_URL}/api/import",
        headers={"X-Workspace-ID": "ws_user_b"},
        files={"file": ("dummy.json", io.BytesIO(b"{}"), "application/json")},
    )
    assert_status(unauth_resp, 401, "Unauthenticated API call rejected with 401 Unauthorized")

    # -------------------------------------------------------------------------
    # Scenario 11: Custom Password New User Complete Lifecycle
    # -------------------------------------------------------------------------
    log_step(11, "Custom Password New User Complete Lifecycle (Admin Provision -> Complex Pass -> API Key -> Write -> Isolation)")

    # 11.1 Admin login
    admin_login = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "1", "login_type": "local"},
    )
    assert_status(admin_login, 200, "Admin login with password '1'")
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    custom_username = f"custom_user_{timestamp}"
    custom_password = f"ComplexPass@{timestamp}!"
    custom_ws_id = f"ws_custom_{timestamp}"

    # 11.2 Admin creates external user
    create_custom_user = session.post(
        f"{BASE_URL}/api/admin/users/external",
        headers=admin_headers,
        json={
            "username": custom_username,
            "password": custom_password,
            "display_name": "Custom Enterprise User",
            "email": f"{custom_username}@example.com",
            "global_role": "user",
        },
    )
    assert_status(create_custom_user, 201, f"Admin created user '{custom_username}' with custom password")

    # 11.3 Admin creates dedicated workspace
    create_custom_ws = session.post(
        f"{BASE_URL}/api/admin/workspaces",
        headers=admin_headers,
        json={
            "name": f"Workspace {custom_username}",
            "workspace_id": custom_ws_id,
            "description": "Custom enterprise dedicated workspace",
        },
    )
    assert_status(create_custom_ws, 201, f"Admin created workspace '{custom_ws_id}'")

    # 11.4 Admin grants Admin role to custom_user on ws_custom
    grant_custom = session.post(
        f"{BASE_URL}/api/admin/workspaces/{custom_ws_id}/grants",
        headers=admin_headers,
        json={
            "grantee_type": "user",
            "grantee_id": custom_username,
            "role": "Admin",
        },
    )
    assert_status(grant_custom, 201, f"Admin granted '{custom_username}' Admin role on '{custom_ws_id}'")

    # 11.5 Custom user logs in with custom password
    custom_login_resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": custom_username, "password": custom_password, "login_type": "local"},
    )
    assert_status(custom_login_resp, 200, f"User '{custom_username}' logged in with custom password '{custom_password}'")
    custom_token = custom_login_resp.json()["access_token"]
    custom_headers = {"Authorization": f"Bearer {custom_token}"}

    # 11.6 Custom user creates personal API Key
    custom_key_resp = session.post(
        f"{BASE_URL}/api/auth/keys",
        headers=custom_headers,
        json={"name": f"Key_{custom_username}"},
    )
    assert_status(custom_key_resp, 201, f"User '{custom_username}' created personal API key")
    custom_raw_key = custom_key_resp.json()["raw_key"]

    # 11.7 Custom user writes dynamic data into ws_custom
    custom_asset_id = f"asset_{custom_username}_01"
    custom_payload = {
        "nodes": [
            {
                "id": custom_asset_id,
                "type": "CustomAsset",
                "properties": {"title": "Critical Enterprise Server", "datacenter": "DC-West"},
            }
        ],
        "edges": [],
    }
    c_bytes = json.dumps(custom_payload).encode("utf-8")
    import_c_resp = session.post(
        f"{BASE_URL}/api/import",
        headers={"X-API-Key": custom_raw_key, "X-Workspace-ID": custom_ws_id},
        files={"file": ("custom_asset.json", io.BytesIO(c_bytes), "application/json")},
    )
    assert_status(import_c_resp, 200, f"User '{custom_username}' dynamically imported data into '{custom_ws_id}'")
    assert_true(import_c_resp.json().get("nodes_added") == 1, "Added 1 dynamic custom node")

    # 11.8 Custom user reads own nodes
    read_c_resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"X-API-Key": custom_raw_key, "X-Workspace-ID": custom_ws_id},
    )
    assert_status(read_c_resp, 200, f"User '{custom_username}' read nodes from '{custom_ws_id}'")
    c_node_ids = {n["id"] for n in read_c_resp.json().get("nodes", [])}
    assert_true(custom_asset_id in c_node_ids, f"Node {custom_asset_id} successfully retrieved")

    # 11.9 Custom user cross-tenant read on ws_user_a -> 403 Forbidden
    cross_c_resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"X-API-Key": custom_raw_key, "X-Workspace-ID": "ws_user_a"},
    )
    assert_status(cross_c_resp, 403, f"User '{custom_username}' read on ws_user_a intercepted with 403 Forbidden")

    # 11.10 User B attempts to read ws_custom -> 403 Forbidden
    user_b_relogin = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "user_b", "password": "1", "login_type": "local"},
    )
    u_b_tok = user_b_relogin.json()["access_token"]
    user_b_cross_c = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {u_b_tok}", "X-Workspace-ID": custom_ws_id},
    )
    assert_status(user_b_cross_c, 403, f"User B read on '{custom_ws_id}' intercepted with 403 Forbidden")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    total = PASS_COUNT + FAIL_COUNT
    pass_pct = (PASS_COUNT / total * 100) if total > 0 else 0
    print(f"\n{BOLD}{GREEN}===================================================================={RESET}")
    print(f"{BOLD}{GREEN}>> ALL 11 REAL USER LIFECYCLE & BOUNDARY SCENARIOS PASSED!{RESET}")
    print(f"{BOLD}{GREEN}>> Total Assertions: {total} | Passed: {PASS_COUNT} | Failed: {FAIL_COUNT} ({pass_pct:.1f}% SUCCESS){RESET}")
    print(f"{BOLD}{GREEN}===================================================================={RESET}\n")


if __name__ == "__main__":
    run_live_verification()
