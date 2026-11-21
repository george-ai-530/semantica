#!/usr/bin/env python3
"""
NAS E2E Live Verification: Persistence Indicator & Workspace Export Functionality
Target: http://192.168.1.15:8000
"""

import sys
import json
import requests

BASE_URL = "http://192.168.1.15:8000"

def log_step(name: str):
    print(f"\n========================================================")
    print(f">> {name}")
    print(f"========================================================")

def assert_status(resp, expected_status, description):
    expected = [expected_status] if isinstance(expected_status, int) else expected_status
    if resp.status_code in expected:
        print(f"  [PASS] {description} -> HTTP {resp.status_code}")
    else:
        print(f"  [FAIL] {description} -> Expected {expected_status}, got HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

def run_suite():
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    # 1. Info & Persistence Metadata
    log_step("1. Info Endpoint & Persistence Diagnostic Indicator Metadata")
    resp = session.get(f"{BASE_URL}/api/info")
    assert_status(resp, 200, "GET /api/info")
    info = resp.json()
    persistence = info.get("persistence", {})
    print(f"  Info status: {info.get('status')}")
    print(f"  Persistence Backend: {persistence.get('backend')}")
    print(f"  SQLite WAL Path: {persistence.get('sqlite_path')}")
    print(f"  FalkorDB Enabled: {persistence.get('falkordb_enabled')} ({persistence.get('falkordb_host')}:{persistence.get('falkordb_port')})")
    print(f"  Persisted Workspaces: {persistence.get('persisted_workspaces')}")

    assert persistence.get("enabled") is True, "Persistence not enabled"
    assert persistence.get("backend") == "sqlite+falkordb", f"Unexpected backend: {persistence.get('backend')}"
    assert persistence.get("falkordb_enabled") is True, "FalkorDB not enabled"
    assert set(["default", "ws_user_a", "ws_user_b"]).issubset(set(persistence.get("persisted_workspaces", []))), "Missing persisted workspaces"

    # 2. Frontend HTML & Bundle Assets
    log_step("2. Frontend Static Delivery & UI Bundle Assets")
    resp = session.get(f"{BASE_URL}/")
    assert_status(resp, 200, "GET / (index.html)")
    assert "COWIN 知识图谱" in resp.text, "Page title mismatch"
    assert "assets/index-" in resp.text, "Index JS missing in index.html"
    print("  ✓ index.html delivered with expected title and asset references.")

    # 3. Authentication
    log_step("3. User Authentication")
    # Admin
    resp_admin = session.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "1"})
    assert_status(resp_admin, 200, "Admin login")
    admin_token = resp_admin.json()["access_token"]

    # User A
    resp_user_a = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
    assert_status(resp_user_a, 200, "User A login")
    user_a_token = resp_user_a.json()["access_token"]

    # User B
    resp_user_b = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_b", "password": "1"})
    assert_status(resp_user_b, 200, "User B login")
    user_b_token = resp_user_b.json()["access_token"]

    # 4. Multi-format Export for user_a on ws_user_a
    log_step("4. Multi-Format Workspace Export on ws_user_a (User A)")
    headers_user_a = {
        "Authorization": f"Bearer {user_a_token}",
        "X-Workspace-ID": "ws_user_a",
        "Content-Type": "application/json",
    }

    # Format 1: JSON
    resp_json = session.post(f"{BASE_URL}/api/export", json={"format": "json"}, headers=headers_user_a)
    assert_status(resp_json, 200, "Export ws_user_a as JSON")
    assert resp_json.headers.get("Content-Type", "").startswith("application/json")
    json_data = resp_json.json()
    assert "entities" in json_data and "relationships" in json_data
    node_count_a = len(json_data["entities"])
    edge_count_a = len(json_data["relationships"])
    print(f"  ✓ JSON Export successful: {node_count_a} entities, {edge_count_a} relationships")
    assert node_count_a >= 7, f"Expected at least 7 nodes, got {node_count_a}"

    # Format 2: CSV
    resp_csv = session.post(f"{BASE_URL}/api/export", json={"format": "csv"}, headers=headers_user_a)
    assert_status(resp_csv, 200, "Export ws_user_a as CSV")
    assert "text/csv" in resp_csv.headers.get("Content-Type", "")
    csv_lines = resp_csv.text.strip().splitlines()
    assert len(csv_lines) > 1
    assert csv_lines[0] == "kind,id,familyId,type,content,source,target,weight"
    print(f"  ✓ CSV Export successful: {len(csv_lines)} rows (including header)")

    # Format 3: GraphML
    resp_graphml = session.post(f"{BASE_URL}/api/export", json={"format": "graphml"}, headers=headers_user_a)
    assert_status(resp_graphml, 200, "Export ws_user_a as GraphML")
    assert "<graphml" in resp_graphml.text
    print(f"  ✓ GraphML Export successful: XML payload size = {len(resp_graphml.text)} bytes")

    # Format 4: Turtle (TTL)
    resp_ttl = session.post(f"{BASE_URL}/api/export", json={"format": "turtle"}, headers=headers_user_a)
    assert_status(resp_ttl, 200, "Export ws_user_a as Turtle (RDF TTL)")
    assert "text/turtle" in resp_ttl.headers.get("Content-Type", "") or "ttl" in resp_ttl.headers.get("Content-Disposition", "")
    print(f"  ✓ Turtle Export successful: TTL payload size = {len(resp_ttl.text)} bytes")

    # 5. Multi-format Export for user_b on ws_user_b
    log_step("5. Multi-Format Workspace Export on ws_user_b (User B)")
    headers_user_b = {
        "Authorization": f"Bearer {user_b_token}",
        "X-Workspace-ID": "ws_user_b",
        "Content-Type": "application/json",
    }
    for fmt in ["json", "csv", "graphml", "turtle"]:
        resp_fmt = session.post(f"{BASE_URL}/api/export", json={"format": fmt}, headers=headers_user_b)
        assert_status(resp_fmt, 200, f"Export ws_user_b as {fmt}")
    print("  ✓ All 4 formats exported successfully for ws_user_b")

    # 6. Unauthorized Export RBAC Guard
    log_step("6. Unauthorized Cross-Workspace Export Guard")
    # user_a attempts to export ws_user_b
    headers_attack = {
        "Authorization": f"Bearer {user_a_token}",
        "X-Workspace-ID": "ws_user_b",
        "Content-Type": "application/json",
    }
    resp_attack = session.post(f"{BASE_URL}/api/export", json={"format": "json"}, headers=headers_attack)
    assert_status(resp_attack, 403, "user_a unauthorized export ws_user_b -> 403 Forbidden")
    print("  ✓ Cross-tenant export strictly rejected with 403 Forbidden.")

    log_step("ALL PERSISTENCE INDICATOR & WORKSPACE EXPORT CHECKS PASSED!")

if __name__ == "__main__":
    run_suite()
