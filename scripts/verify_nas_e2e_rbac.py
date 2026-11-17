#!/usr/bin/env python3
"""
NAS Live E2E Verification Script: Enterprise Multi-Tenant Isolation & RBAC Flow
Target: http://192.168.1.15:8000
"""

import sys
import time
import requests

BASE_URL = "http://192.168.1.15:8000"

def log_step(name: str):
    print(f"\n========================================================")
    print(f">> {name}")
    print(f"========================================================")

def assert_status(resp, expected_status, description):
    if isinstance(expected_status, int):
        expected = [expected_status]
    else:
        expected = expected_status
    if resp.status_code in expected:
        print(f"  [PASS] {description} -> HTTP {resp.status_code}")
    else:
        print(f"  [FAIL] {description} -> Expected {expected_status}, got HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

def run_verification():
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    # -------------------------------------------------------------------------
    # 0. Health & Frontend Verification
    # -------------------------------------------------------------------------
    log_step("0. Live System Health & Static Bundle Delivery")
    resp = session.get(f"{BASE_URL}/api/health")
    assert_status(resp, 200, "Health Check Endpoint")
    data = resp.json()
    assert data.get("status") == "ok", f"Health status not ok: {data}"
    print(f"         FalkorDB status: {data.get('falkordb')}, AuthStore: {data.get('auth_store')}")

    resp = session.get(f"{BASE_URL}/api/info")
    assert_status(resp, 200, "System Info Endpoint")

    resp = session.get(f"{BASE_URL}/")
    assert_status(resp, 200, "Frontend index.html Delivery")
    assert '<div id="root"></div>' in resp.text, "Root element missing in index.html"
    print(f"         Frontend HTML verified successfully.")

    # -------------------------------------------------------------------------
    # 1. Login Verification with Password '1'
    # -------------------------------------------------------------------------
    log_step("1. Test Credentials Verification (Password '1')")
    
    # 1.1 Admin
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "1"})
    assert_status(resp, 200, "Admin login with password '1'")
    admin_token = resp.json()["access_token"]
    admin_user = resp.json()["user"]
    assert admin_user["global_role"] == "admin", "admin must have global_role=admin"
    print(f"         Admin authenticated: user_id={admin_user['id']}, workspaces={len(admin_user['authorized_workspaces'])}")

    # 1.2 User A
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
    assert_status(resp, 200, "User A login with password '1'")
    token_a = resp.json()["access_token"]
    user_a = resp.json()["user"]
    assert user_a["global_role"] == "user", "user_a must have global_role=user"
    assert "ws_user_a" in user_a["authorized_workspaces"], "ws_user_a must be in user_a workspaces"
    assert "ws_user_b" not in user_a["authorized_workspaces"], "ws_user_b must not be in user_a baseline"
    print(f"         User A authenticated: user_id={user_a['id']}, workspaces={user_a['authorized_workspaces']}")

    # 1.3 User B
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_b", "password": "1"})
    assert_status(resp, 200, "User B login with password '1'")
    token_b = resp.json()["access_token"]
    user_b = resp.json()["user"]
    assert user_b["global_role"] == "user", "user_b must have global_role=user"
    assert "ws_user_b" in user_b["authorized_workspaces"], "ws_user_b must be in user_b workspaces"
    assert "ws_user_a" not in user_b["authorized_workspaces"], "ws_user_a must not be in user_b baseline"
    print(f"         User B authenticated: user_id={user_b['id']}, workspaces={user_b['authorized_workspaces']}")

    # -------------------------------------------------------------------------
    # Scenario 1: Cross-Tenant Data Isolation
    # -------------------------------------------------------------------------
    log_step("Scenario 1: Cross-Tenant Data Isolation Enforcement")
    
    # User A -> ws_user_a (200)
    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_a}", "X-Workspace-ID": "ws_user_a"}
    )
    assert_status(resp, 200, "User A accesses ws_user_a (Authorized)")

    # User A -> ws_user_b (403)
    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_a}", "X-Workspace-ID": "ws_user_b"}
    )
    assert_status(resp, 403, "User A accesses ws_user_b (Unauthorized -> 403 Forbidden)")

    # User B -> ws_user_b (200)
    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_b}", "X-Workspace-ID": "ws_user_b"}
    )
    assert_status(resp, 200, "User B accesses ws_user_b (Authorized)")

    # User B -> ws_user_a (403)
    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_b}", "X-Workspace-ID": "ws_user_a"}
    )
    assert_status(resp, 403, "User B accesses ws_user_a (Unauthorized -> 403 Forbidden)")

    # -------------------------------------------------------------------------
    # Scenario 2: Dynamic Grant Visibility Lifecycle
    # -------------------------------------------------------------------------
    log_step("Scenario 2: Dynamic Grant Visibility (Direct User Grant & Revoke)")
    
    # 2.1 Admin grants User A 'Viewer' on ws_user_b
    resp = session.post(
        f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"grantee_type": "user", "grantee_id": user_a["id"], "role": "Viewer"}
    )
    assert_status(resp, 201, "Admin creates grant for user_a on ws_user_b")
    grant_id = resp.json()["id"]
    print(f"         Grant ID: {grant_id}")

    # 2.2 User A logs in -> ws_user_b is now authorized -> access 200 OK
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
    token_a_granted = resp.json()["access_token"]
    assert "ws_user_b" in resp.json()["user"]["authorized_workspaces"], "ws_user_b should be in authorized workspaces"

    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_a_granted}", "X-Workspace-ID": "ws_user_b"}
    )
    assert_status(resp, 200, "User A accesses ws_user_b after grant (200 OK)")

    # 2.3 Admin revokes grant
    resp = session.delete(
        f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants/{grant_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert_status(resp, 200, "Admin revokes grant for user_a on ws_user_b")

    # 2.4 User A logs in -> ws_user_b is gone -> access 403 Forbidden
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
    token_a_revoked = resp.json()["access_token"]
    assert "ws_user_b" not in resp.json()["user"]["authorized_workspaces"], "ws_user_b should not be authorized"

    resp = session.get(
        f"{BASE_URL}/api/graph/nodes",
        headers={"Authorization": f"Bearer {token_a_revoked}", "X-Workspace-ID": "ws_user_b"}
    )
    assert_status(resp, 403, "User A accesses ws_user_b after revocation (403 Forbidden)")

    # -------------------------------------------------------------------------
    # Scenario 3: API Key Live Permission Synchronization
    # -------------------------------------------------------------------------
    log_step("Scenario 3: API Key Live Permission Synchronization")
    
    # 3.1 Provision personal API key for User A with wildcard scope
    resp = session.post(
        f"{BASE_URL}/api/admin/keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "e2e-live-sync-key",
            "user_id": user_a["id"],
            "is_service": False,
            "allowed_workspaces": ["*"]
        }
    )
    assert_status(resp, 201, "Admin provisions personal API key for user_a")
    key_data = resp.json()
    key_id = key_data["id"]
    raw_key = key_data["raw_key"]
    print(f"         API Key ID: {key_id}, Prefix: {key_data['key_prefix']}")

    try:
        # Baseline check with key: ws_user_a is 200, ws_user_b is 403
        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_user_a"}
        )
        assert_status(resp, 200, "API key accesses ws_user_a (Baseline 200 OK)")

        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_user_b"}
        )
        assert_status(resp, 403, "API key accesses ws_user_b (Baseline 403 Forbidden)")

        # 3.2 Dynamic Grant: Admin grants ws_user_b to user_a
        resp = session.post(
            f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"grantee_type": "user", "grantee_id": user_a["id"], "role": "Viewer"}
        )
        assert_status(resp, 201, "Admin grants ws_user_b to user_a")
        dyn_grant_id = resp.json()["id"]

        # 3.3 Live Sync: The exact same API key immediately gets 200 on ws_user_b (NO key regeneration)
        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_user_b"}
        )
        assert_status(resp, 200, "API key instantly accesses ws_user_b without reissue (200 OK)")

        # 3.4 Dynamic Revocation: Admin deletes grant
        resp = session.delete(
            f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants/{dyn_grant_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert_status(resp, 200, "Admin revokes ws_user_b grant")

        # 3.5 Live Sync: The same API key immediately gets 403 on ws_user_b
        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_user_b"}
        )
        assert_status(resp, 403, "API key instantly loses access to ws_user_b (403 Forbidden)")

    finally:
        # 3.6 Emergency Revocation: Admin revokes the API key
        resp = session.delete(
            f"{BASE_URL}/api/admin/keys/{key_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert_status(resp, 200, "Admin revokes API key emergency")

        # Probing with revoked key immediately returns 401
        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"X-API-Key": raw_key, "X-Workspace-ID": "ws_user_a"}
        )
        assert_status(resp, 401, "Revoked API key rejected immediately (401 Unauthorized)")

    # -------------------------------------------------------------------------
    # Scenario 4: Group-Based Role Inheritance & Membership Lifecycle
    # -------------------------------------------------------------------------
    log_step("Scenario 4: Group-Based Role Inheritance Lifecycle")
    
    # 4.1 Admin creates local group 'team_enterprise_alpha'
    resp = session.post(
        f"{BASE_URL}/api/admin/groups",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "team_enterprise_alpha", "description": "Multi-tenant verification group"}
    )
    assert_status(resp, 201, "Admin creates security group 'team_enterprise_alpha'")
    group_id = resp.json()["id"]
    print(f"         Group ID: {group_id}")

    try:
        # 4.2 Admin adds User A to group via username
        resp = session.post(
            f"{BASE_URL}/api/admin/groups/{group_id}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": "user_a"}
        )
        assert_status(resp, 200, "Admin adds user_a to group by username")

        # 4.3 Admin grants group Viewer role on ws_user_b
        resp = session.post(
            f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"grantee_type": "group", "grantee_id": group_id, "role": "Viewer"}
        )
        assert_status(resp, 201, "Admin grants group Viewer role on ws_user_b")
        grp_grant_id = resp.json()["id"]

        # 4.4 User A logs in -> inherits ws_user_b from group membership
        resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
        token_a_grp = resp.json()["access_token"]
        assert "ws_user_b" in resp.json()["user"]["authorized_workspaces"], "user_a should inherit ws_user_b from group"

        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"Authorization": f"Bearer {token_a_grp}", "X-Workspace-ID": "ws_user_b"}
        )
        assert_status(resp, 200, "User A accesses ws_user_b via group role inheritance (200 OK)")

        # 4.5 Admin removes User A from group
        resp = session.delete(
            f"{BASE_URL}/api/admin/groups/{group_id}/members/{user_a['id']}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert_status(resp, 200, "Admin removes user_a from group")

        # 4.6 User A logs in -> group membership lost -> access to ws_user_b is 403 Forbidden
        resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "user_a", "password": "1"})
        token_a_no_grp = resp.json()["access_token"]
        assert "ws_user_b" not in resp.json()["user"]["authorized_workspaces"], "user_a must not have ws_user_b after removal"

        resp = session.get(
            f"{BASE_URL}/api/graph/nodes",
            headers={"Authorization": f"Bearer {token_a_no_grp}", "X-Workspace-ID": "ws_user_b"}
        )
        assert_status(resp, 403, "User A loses access to ws_user_b after group removal (403 Forbidden)")

    finally:
        # Cleanup grant and group
        session.delete(
            f"{BASE_URL}/api/admin/workspaces/ws_user_b/grants/{grp_grant_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        session.delete(
            f"{BASE_URL}/api/admin/groups/{group_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        print("         Cleaned up temporary group and grant.")

    print("\n========================================================")
    print(">> ALL LIVE NAS SCENARIOS PASSED WITH 100% SUCCESS!")
    print("========================================================\n")

if __name__ == "__main__":
    run_verification()
