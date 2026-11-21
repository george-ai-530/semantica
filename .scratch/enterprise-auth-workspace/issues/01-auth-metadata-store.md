# 01: Auth Metadata Store & Gateway Ingress Pipeline

**What to build:**
Deliver the embedded SQLite authorization metadata database (`semantica_auth.db`) with schemas for users, workspaces, groups, workspace grants, and API keys. Implement the primary FastAPI authentication dependency (`get_current_identity`) that extracts either `Authorization: Bearer <jwt>` or `X-API-Key: <key>`, resolves the caller's identity context, and falls back gracefully to legacy `SEMANTICA_API_KEY` when unconfigured.

**Blocked by:** None (can start immediately)

**Assigned Model:** Gemini 3.8 Flash

**Status:** closed

- [x] SQLite metadata store initialized with migrations for `auth_users`, `auth_workspaces`, `auth_groups`, `auth_workspace_grants`, and `auth_api_keys`
- [x] Unified FastAPI dependency `get_current_identity` resolving to `RequestContext`
- [x] Constant-time API Key verification against salted hashes in SQLite
- [x] Backwards-compatibility fallback when running in standalone legacy mode
- [x] Comprehensive HTTP test coverage via FastAPI `TestClient`
