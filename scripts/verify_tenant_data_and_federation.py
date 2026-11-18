#!/usr/bin/env python3
"""
Verification Script: Tenant Graph Data Inspection & Federated GraphRAG Provenance
Target: http://192.168.1.15:8000
"""

import json
import sys
import requests

BASE_URL = "http://192.168.1.15:8000"

def get_token(username, password="1"):
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"username": username, "password": password})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed for {username}: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]

def main():
    print("=" * 70)
    print("TENANT DATA INSPECTION & FEDERATED SEARCH VERIFICATION")
    print("=" * 70)

    # 1. Authenticate users
    tok_a = get_token("user_a")
    tok_b = get_token("user_b")
    tok_admin = get_token("admin")
    print(">> All users (user_a, user_b, admin) authenticated with password '1'.\n")

    # -------------------------------------------------------------------------
    # Step 1: user_a Inspection & Cross-Tenant 403 Probe
    # -------------------------------------------------------------------------
    print("-" * 70)
    print("STEP 1: user_a on ws_user_a (Deep Tech & Space Exploration R&D Graph)")
    print("-" * 70)
    
    # Nodes
    r_nodes_a = requests.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {tok_a}", "X-Workspace-ID": "ws_user_a"}
    )
    assert r_nodes_a.status_code == 200, f"Failed to get ws_user_a nodes: {r_nodes_a.status_code}"
    nodes_a_data = r_nodes_a.json()
    nodes_a = nodes_a_data.get("nodes", [])
    print(f"[user_a -> ws_user_a] Total Nodes: {len(nodes_a)}")
    for n in nodes_a:
        print(f"  • [{n.get('type')}] {n.get('id')}: {n.get('content')}")

    # Edges
    r_edges_a = requests.get(
        f"{BASE_URL}/api/graph/edges",
        headers={"Authorization": f"Bearer {tok_a}", "X-Workspace-ID": "ws_user_a"}
    )
    assert r_edges_a.status_code == 200, f"Failed to get ws_user_a edges: {r_edges_a.status_code}"
    edges_a_data = r_edges_a.json()
    edges_a = edges_a_data.get("edges", [])
    print(f"\n[user_a -> ws_user_a] Total Edges: {len(edges_a)}")
    for e in edges_a:
        print(f"  → ({e.get('source')}) --[{e.get('type')}]--> ({e.get('target')})")

    # Cross-Tenant Probe: user_a -> ws_user_b (Must be 403)
    r_probe_b = requests.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {tok_a}", "X-Workspace-ID": "ws_user_b"}
    )
    print(f"\n[user_a -> ws_user_b PROBE] HTTP Status: {r_probe_b.status_code} (Expected 403)")
    assert r_probe_b.status_code == 403, f"Expected 403 on ws_user_b, got {r_probe_b.status_code}"
    print("  ✓ Cross-tenant 403 Forbidden verified for user_a on ws_user_b.")

    # -------------------------------------------------------------------------
    # Step 2: user_b Inspection & Cross-Tenant 403 Probe
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("STEP 2: user_b on ws_user_b (Global Financial & Enterprise Operations Graph)")
    print("-" * 70)
    
    # Nodes
    r_nodes_b = requests.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {tok_b}", "X-Workspace-ID": "ws_user_b"}
    )
    assert r_nodes_b.status_code == 200, f"Failed to get ws_user_b nodes: {r_nodes_b.status_code}"
    nodes_b_data = r_nodes_b.json()
    nodes_b = nodes_b_data.get("nodes", [])
    print(f"[user_b -> ws_user_b] Total Nodes: {len(nodes_b)}")
    for n in nodes_b:
        print(f"  • [{n.get('type')}] {n.get('id')}: {n.get('content')}")

    # Edges
    r_edges_b = requests.get(
        f"{BASE_URL}/api/graph/edges",
        headers={"Authorization": f"Bearer {tok_b}", "X-Workspace-ID": "ws_user_b"}
    )
    assert r_edges_b.status_code == 200, f"Failed to get ws_user_b edges: {r_edges_b.status_code}"
    edges_b_data = r_edges_b.json()
    edges_b = edges_b_data.get("edges", [])
    print(f"\n[user_b -> ws_user_b] Total Edges: {len(edges_b)}")
    for e in edges_b:
        print(f"  → ({e.get('source')}) --[{e.get('type')}]--> ({e.get('target')})")

    # Cross-Tenant Probe: user_b -> ws_user_a (Must be 403)
    r_probe_a = requests.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {tok_b}", "X-Workspace-ID": "ws_user_a"}
    )
    print(f"\n[user_b -> ws_user_a PROBE] HTTP Status: {r_probe_a.status_code} (Expected 403)")
    assert r_probe_a.status_code == 403, f"Expected 403 on ws_user_a, got {r_probe_a.status_code}"
    print("  ✓ Cross-tenant 403 Forbidden verified for user_b on ws_user_a.")

    # -------------------------------------------------------------------------
    # Step 3: Admin Cross-Workspace Federated Search & Provenance
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("STEP 3: Admin Governed Cross-Workspace Federated Search & Provenance")
    print("-" * 70)

    # 3.1 Federated Search for 'space OR flight OR mission'
    payload_space = {
        "query": "space mission probe",
        "federated_workspaces": ["ws_user_a", "ws_user_b"],
        "limit": 10
    }
    r_fed_space = requests.post(
        f"{BASE_URL}/api/graph/federated/search",
        headers={"Authorization": f"Bearer {tok_admin}", "X-Workspace-ID": "default"},
        json=payload_space
    )
    assert r_fed_space.status_code == 200, f"Federated search failed: {r_fed_space.status_code}"
    fed_space_data = r_fed_space.json()
    print(f"[Admin Federated Search: 'space mission probe']")
    print(f"  Queried Workspaces: {fed_space_data.get('workspaces_queried')}")
    print(f"  Total Results: {fed_space_data.get('total')}")
    for res in fed_space_data.get("results", []):
        node = res.get("node", {})
        print(f"  ★ Origin: [{res.get('origin_workspace')}] | Score: {res.get('score')} | ID: {node.get('id')} ({node.get('type')}) - {node.get('content')}")

    # 3.2 Federated Search for 'fund OR capital OR risk'
    payload_fin = {
        "query": "fund risk compliance",
        "federated_workspaces": ["ws_user_a", "ws_user_b"],
        "limit": 10
    }
    r_fed_fin = requests.post(
        f"{BASE_URL}/api/graph/federated/search",
        headers={"Authorization": f"Bearer {tok_admin}", "X-Workspace-ID": "default"},
        json=payload_fin
    )
    assert r_fed_fin.status_code == 200, f"Federated search failed: {r_fed_fin.status_code}"
    fed_fin_data = r_fed_fin.json()
    print(f"\n[Admin Federated Search: 'fund risk compliance']")
    print(f"  Queried Workspaces: {fed_fin_data.get('workspaces_queried')}")
    print(f"  Total Results: {fed_fin_data.get('total')}")
    for res in fed_fin_data.get("results", []):
        node = res.get("node", {})
        print(f"  ★ Origin: [{res.get('origin_workspace')}] | Score: {res.get('score')} | ID: {node.get('id')} ({node.get('type')}) - {node.get('content')}")

    # 3.3 Non-admin Unauthorized Federated Search Check
    r_fed_unauth = requests.post(
        f"{BASE_URL}/api/graph/federated/search",
        headers={"Authorization": f"Bearer {tok_a}", "X-Workspace-ID": "ws_user_a"},
        json={"query": "risk", "federated_workspaces": ["ws_user_b"]}
    )
    print(f"\n[user_a Unauthorized Federated Search on ws_user_b]")
    print(f"  HTTP Status: {r_fed_unauth.status_code} (Expected 403)")
    print(f"  Detail: {r_fed_unauth.json().get('detail')}")
    assert r_fed_unauth.status_code == 403, f"Expected 403, got {r_fed_unauth.status_code}"
    print("  ✓ Federated RBAC guard strictly blocked ungranted workspace.")

    print("\n" + "=" * 70)
    print(">> ALL TENANT DATA & FEDERATION VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
