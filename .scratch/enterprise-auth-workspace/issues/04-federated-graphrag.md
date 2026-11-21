# 04: Governed Cross-Workspace Federated GraphRAG & RRF Fusion

**What to build:**
Enable search and GraphRAG endpoints to accept optional `federated_workspaces` lists. Verify caller read permissions across all requested target workspaces, dispatch concurrent parallel queries across multiple physical FalkorDB graphs without blocking, and merge heterogeneous candidate entities and triples using Reciprocal Rank Fusion (RRF) while strictly preserving provenance.

**Blocked by:** 03: Dynamic Multi-Workspace Session Routing & FalkorDB Graph Key Isolation

**Assigned Model:** Claude Opus 4.6 (Thinking) (Complex Multi-Graph Concurrency & Ranking Algorithm)

**Status:** closed

- [x] Query interface extension supporting `federated_workspaces` parameter
- [x] Multi-workspace read grant validator ensuring zero information leakage to ungranted workspaces (HTTP 403 on invalid target)
- [x] Concurrent asynchronous fan-out across multiple FalkorDB graph sessions
- [x] Reciprocal Rank Fusion (RRF) algorithm merging vector similarity and graph centrality ranks
- [x] End-to-end integration test demonstrating cross-department knowledge retrieval without data modification
