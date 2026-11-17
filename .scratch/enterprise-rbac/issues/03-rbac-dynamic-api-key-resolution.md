# 03: RBAC Dynamic API Key Resolution

**What to build:**
Ensure personal API keys dynamically inherit the live permissions of their owner user (and associated AD/local groups) without caching static grants. When an admin grants or revokes access to a workspace for a user or user group, personal API keys immediately reflect the change with zero delay.

**Blocked by:** 01: Auth Store Passwords and Seed Accounts, 02: Admin Group and Role Routes

**Status:** closed

- [x] `get_effective_workspaces_for_api_key` evaluates live user/group grants on request.
- [x] Personal key cannot access workspaces not granted to the owning user.
- [x] Granting access to user immediately allows API key access without reissuing the key.
- [x] Revoking user grant or disabling user immediately returns 403 on API key requests.
