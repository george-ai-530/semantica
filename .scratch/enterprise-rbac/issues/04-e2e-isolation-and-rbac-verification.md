# 04: E2E Multi-Tenant Isolation and RBAC Verification Suite

**What to build:**
Comprehensive automated integration test suite (`tests/test_multi_tenant_isolation_and_rbac_flow.py`) covering all 4 core scenarios:
1. Cross-tenant workspace data isolation (`user_a` vs `user_b`).
2. Post-grant data visibility (granting access dynamically enables access).
3. API key permission synchronization with user/group permissions.
4. Admin group creation, membership assignment, and workspace role inheritance.

**Blocked by:** 01: Auth Store Passwords and Seed Accounts, 02: Admin Group and Role Routes, 03: RBAC Dynamic API Key Resolution

**Status:** closed

- [x] Scenario 1: `user_a` gets 200 on `ws_user_a`, 403 on `ws_user_b`; `user_b` gets 200 on `ws_user_b`, 403 on `ws_user_a`.
- [x] Scenario 2: Admin grants `user_a` Viewer on `ws_user_b` -> `user_a` gets 200; revoking returns 403.
- [x] Scenario 3: `user_a` API key dynamically gains access when user is granted, and loses access when grant is revoked.
- [x] Scenario 4: Admin creates group, adds `user_a`, assigns role to group on `ws_user_b` -> `user_a` accesses with 200; removing from group returns 403.
