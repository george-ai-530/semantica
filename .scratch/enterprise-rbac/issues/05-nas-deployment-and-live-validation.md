# 05: NAS Deployment and Live Service Validation

**What to build:**
Rebuild the Explorer frontend assets, synchronize the updated backend code and static bundle into the NAS Docker container (`semantica-explorer` on `192.168.1.15:8000`), restart the container, and perform live HTTP verification against `192.168.1.15:8000` for all 4 scenarios.

**Blocked by:** 04: E2E Multi-Tenant Isolation and RBAC Verification Suite

**Status:** closed

- [x] Frontend bundle built successfully (`npm run build`).
- [x] Docker container on NAS updated and restarted cleanly.
- [x] Live login with password `1` tested for `admin`, `user_a`, `user_b`.
- [x] Live API curl verification of isolation, grant visibility, and API key sync passes on NAS.
