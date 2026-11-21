# 05: Personal API Key Self-Service & Admin Management REST APIs

**What to build:**
Deliver REST endpoints for user self-service API key generation and comprehensive administrative governance: creating and disabling external guest users with expiration timestamps, configuring local ad-hoc groups, setting up workspace ACL matrices (mapping AD groups or individuals to roles), and auditing/revoking active API keys across the system.

**Blocked by:** 01: Auth Metadata Store & Gateway Ingress Pipeline, 02: Active Directory LDAP Direct Bind & JWT Login Flow, 03: Dynamic Multi-Workspace Session Routing

**Assigned Model:** Gemini 3.8 Flash

**Status:** closed

- [x] `/api/auth/keys` endpoints for personal API key generation, listing, and revocation with strict permission inheritance
- [x] `/api/admin/users/external` CRUD endpoints managing guest credentials and expiry timestamps
- [x] `/api/admin/groups` endpoints managing local ad-hoc project groups
- [x] `/api/admin/workspaces/{id}/grants` endpoints for assigning AD security groups and users to workspace roles
- [x] `/api/admin/keys` audit inventory endpoint and emergency instant key revocation endpoint
