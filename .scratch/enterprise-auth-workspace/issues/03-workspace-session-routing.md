# 03: Dynamic Multi-Workspace Session Routing & FalkorDB Graph Key Isolation

**What to build:**
Refactor the single global `GraphSession` into a concurrent, thread-safe `WorkspaceSessionRegistry`. Dynamically resolve and mount independent FalkorDB graph keys (`graph:ws_<id>`) per workspace. Enforce gateway-level authorization: ensure that every graph mutation, SPARQL query, or traversal request validates the caller's role (`Viewer`, `Editor`, `Admin`) against the target workspace before routing.

**Blocked by:** 01: Auth Metadata Store & Gateway Ingress Pipeline

**Assigned Model:** Claude Opus 4.6 (Thinking) (Core Architectural Complexity & Concurrency)

**Status:** closed

- [x] `WorkspaceSessionRegistry` managing thread-safe lifecycle of per-workspace `GraphSession` instances
- [x] Per-workspace physical graph isolation in FalkorDB using distinct graph namespaces
- [x] Automatic gateway-level RBAC route guard rejecting unauthorized workspace requests with HTTP 403
- [x] Session caching, lazy initialization, and clean connection teardown
- [x] Multi-tenant isolation test verifying data written to workspace A is completely invisible to workspace B
