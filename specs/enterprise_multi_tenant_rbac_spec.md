# 需求规格说明书：企业级多租户隔离、动态授权流转与组角色纳管 (Enterprise Multi-Tenant Isolation, Dynamic Grant Lifecycle & Group-Role RBAC Spec)

## Problem Statement

在当前企业级知识图谱与 GraphRAG 系统部署中，企业用户面临多部门协同与合规隔离的核心痛点：
1. **测试成本过高**：复杂长密码（如 `Young520`、带特殊字符）在多账号切换验证、多租户交叉审查以及高频调试中造成不必要的输入负担，需要一套便捷的简化测试密码体系（统一为 `1`）。
2. **多租户数据隔离存疑**：用户无法直观验证部门间（如 `user_a` 与 `user_b`）是否具备物理级图谱隔离，担心私有知识资产被非授权人员越权窃取。
3. **动态授权与撤权时效性存疑**：在企业日常运营中，跨部门协作经常需要临时授权。用户需要确信，当管理员将 `user_b` 的空间授权给 `user_a` 后，`user_a` 能即刻查阅数据；而在撤销授权后，数据能即刻对 `user_a` 彻底隐蔽。
4. **API Key 越权与逃逸隐患**：用户严重担心个人 API 密钥在生成后变成“永久通票”——即使用户在企业 AD/组织中被降权或移出项目组，其此前签发的 API Key 依然能够访问老数据。系统必须确保 API Key 权限实时与主体身份权限强一致联动。
5. **缺少自主组织纳管工具**：企业管理员无法在前端控制台中自行按需创建自定义安全组、将成员纳管进组，以及按工作区维度赋予组/成员 `Viewer / Editor / Admin` 角色。

---

## Solution

构建一套端到端贯通的多租户隔离、动态生命周期授权与本地安全组/角色纳管体系：
1. **测试环境极简凭据策略**：将本地管理员 `admin` 及所有内置测试账号（`user_a`, `user_b`）的测试密码统一收敛为极简凭据 `1`，同时保留生产环境强哈希（PBKDF2-HMAC-SHA256）存储机制不变。
2. **多租户工作区物理级隔离**：为 `user_a` 和 `user_b` 分别预置专属隔离工作区（`ws_user_a` 和 `ws_user_b`），底层严格绑定独立物理图谱标识（`graph:ws_user_a` 与 `graph:ws_user_b`）。未被授权的访问请求（带 `X-Workspace-ID`）直接被网关依赖层拦截并返回 `HTTP 403 Forbidden`。
3. **即时动态授权与撤销机制**：Admin 可通过控制台在工作区授权矩阵中对指定用户动态增删 `Viewer / Editor / Admin` 角色，授权生效后无需重启服务或重新登录，下游读写接口（SPARQL、节点列表、拓扑分析）即时放行。
4. **API Key 零信任动态权限裁决**：每次使用 API Key 请求网关时，网关动态从元数据存储中实时计算其拥有者当前的有效权限集（`get_effective_workspaces_for_api_key`）。一旦管理员撤销用户对某空间的权限，该用户的所有活跃 API Key 在纳秒级同步失效，杜绝权限逃逸。
5. **管理控制台自定义组、成员管理与角色赋权**：
   - 管理员可自由创建本地安全组（Local Ad-hoc Groups）；
   - 在弹窗中直接输入用户名将指定用户拉入组，或一键将用户从组中移出；
   - 支持将整个组授权至特定工作区的特定角色（如 `Viewer` / `Editor` / `Admin`），组内所有成员即时继承该组的工作区角色。

---

## User Stories

1. As a QA engineer or tester, I want the test accounts to have a unified simple password `1`, so that I can switch between accounts and test multi-tenancy quickly without repetitive typing.
2. As a system administrator, I want an initialized default administrator `admin` with password `1`, so that I can immediately access the governance console after fresh installation.
3. As test user `user_a`, I want to log in with username `user_a` and password `1`, so that I can operate within my own designated workspace `ws_user_a`.
4. As test user `user_b`, I want to log in with username `user_b` and password `1`, so that I can operate within my own designated workspace `ws_user_b`.
5. As test user `user_a`, I want my requests to `ws_user_b` to be strictly rejected with HTTP 403 Forbidden before authorization, so that my colleague's private knowledge remains secure.
6. As test user `user_b`, I want my requests to `ws_user_a` to be strictly rejected with HTTP 403 Forbidden before authorization, so that my private business graphs are not leaked.
7. As a system administrator, I want to view all tenant workspaces and their current grant matrices in the Admin Console, so that I have complete visibility over cross-space permissions.
8. As a system administrator, I want to grant `user_a` the `Viewer` role on workspace `ws_user_b` via the UI or API, so that `user_a` can collaborate on `user_b`'s project.
9. As test user `user_a`, I want to switch to `ws_user_b` immediately after receiving authorization, so that I can inspect and search nodes belonging to `user_b`.
10. As a system administrator, I want to revoke `user_a`'s grant on `ws_user_b`, so that temporary collaboration access can be promptly terminated.
11. As test user `user_a`, I want my requests to `ws_user_b` to immediately fail with HTTP 403 Forbidden after revocation, so that no residual access persists.
12. As test user `user_a`, I want to generate a personal API key from the top header drawer, so that I can access Semantica programmatically from external agents or scripts.
13. As test user `user_a`, I want my personal API key to successfully query `ws_user_b` as long as my user account holds valid permissions on `ws_user_b`.
14. As a security compliance officer, I want any personal API key created by `user_a` to immediately lose access to `ws_user_b` (HTTP 403) as soon as `user_a` is revoked by an admin, so that stale tokens cannot cause unauthorized data leaks.
15. As a system administrator, I want to create a custom local security group (e.g. `team_alpha`) in the Admin Console, so that I can manage permissions at the team level instead of per-user.
16. As a system administrator, I want to search and add `user_a` and `user_b` into `team_alpha` via the Group Management modal, so that team membership is accurately tracked.
17. As a system administrator, I want to grant `team_alpha` an `Editor` role on workspace `ws_user_b`, so that all members of `team_alpha` receive edit privileges on that workspace.
18. As test user `user_a`, I want to inherit the `Editor` role on `ws_user_b` by virtue of my membership in `team_alpha`, so that I do not require individual user-level grants.
19. As a system administrator, I want to remove `user_a` from `team_alpha`, so that `user_a` instantly loses all workspace roles inherited from that group.
20. As a security auditor, I want all user creations, group member modifications, workspace role grants, and revocations to be persisted transactionally in SQLite, so that permissions survive server restarts.

---

## Implementation Decisions

### 1. Authentication & Testing Credentials
- **Password Scheme**: All built-in accounts (`admin`, `user_a`, `user_b`) use the uniform test password `1`.
- **Password Storage**: Passwords continue to be securely hashed via PBKDF2-HMAC-SHA256 with cryptographically random 16-byte salts. The plaintext `1` is never stored in cleartext.
- **Seeding Hook**: In `semantica.auth.store.AuthStore.__init__`, if `user_a` or `user_b` do not exist, they are auto-created with `global_role='user'`, `user_type='local'`, and password hash corresponding to `1`. Existing `admin` user is updated with the password hash for `1`.

### 2. Multi-Workspace Isolation & Granular Tenancy
- **Workspace Structure**:
  - `default`: Default Global Workspace (`graph:default`)
  - `ws_user_a`: Dedicated Workspace for User A (`graph:ws_user_a`)
  - `ws_user_b`: Dedicated Workspace for User B (`graph:ws_user_b`)
  - `ws_rd`: R&D Engineering Workspace (`graph:ws_rd`)
  - `ws_biz`: Business Intelligence Workspace (`graph:ws_biz`)
- **Isolation Enforcement Seam**:
  - FastAPI Gateway Ingress Dependency `get_current_identity` strictly evaluates `target_workspace in authorized_workspaces`.
  - Non-admin callers attempting to access an unauthorized workspace without wildcards receive an immediate `HTTP 403 Forbidden`.

### 3. Real-Time Dynamic API Key RBAC Resolution
- **Zero-Trust Token Strategy**:
  - Personal API Keys do **NOT** store a static copy of permissions in their JWT or DB row.
  - On every request where an `X-API-Key` is presented, `store.get_effective_workspaces_for_api_key(api_key)` evaluates the *live, current* workspace permissions of `api_key.user_id`.
  - Group memberships and direct workspace grants are dynamically resolved via SQL join at request time.
  - Revoking a user's grant or removing them from a group causes their API keys to immediately 403 on that workspace without token re-issuance.

### 4. Admin Group Management & Role Assignments
- **API Interfaces**:
  - `POST /api/admin/groups`: Create new local security group.
  - `GET /api/admin/groups`: List groups with live member counts.
  - `GET /api/admin/groups/{id}`: List group details and member user objects.
  - `POST /api/admin/groups/{id}/members`: Accept `{ "user_id": ... }` or `{ "username": ... }` to add user into group.
  - `DELETE /api/admin/groups/{id}/members/{user_id}`: Remove user from group.
  - `POST /api/admin/workspaces/{ws_id}/grants`: Grant role (`Viewer`, `Editor`, `Admin`) to `grantee_type='group'` or `'user'`.
  - `DELETE /api/admin/workspaces/{ws_id}/grants/{grant_id}`: Revoke grant.
- **UI Frontend Updates**:
  - In `AdminWorkspace.tsx` Tab 3, the "管理成员" (Manage Members) modal allows adding users by username or ID with instant table refresh.
  - In Tab 2, workspace grants list both user grants and group grants with role badges.

---

## Testing Decisions

### What Makes a Good Test
- Tests must interact **only through external observable interfaces** (HTTP requests with Bearer tokens / API key headers, status codes 200/201/403, and JSON responses).
- Tests must **never mock** the authorization dependency or database state during integration testing; they must run against the real SQLite store and FastAPI router.
- Behavioral verification must cover state transitions:
  - Phase 1: Isolated baseline (User A cannot access Workspace B -> 403).
  - Phase 2: Direct grant (Admin grants Workspace B to User A -> 200).
  - Phase 3: API Key sync (User A API key accesses Workspace B -> 200; Admin revokes User A -> API key gets 403).
  - Phase 4: Group inheritance (Admin creates group, adds User A, grants group Workspace B -> User A gets 200; Admin removes User A from group -> User A gets 403).

### Modules to Test
- `semantica.auth.routes`: Login with password `1`, token generation, `/api/auth/me`, `/api/auth/workspaces`.
- `semantica.auth.dependencies`: `get_current_identity`, RBAC workspace boundary check (403 vs 200).
- `semantica.auth.admin_routes`: External users, groups, group members, workspace grants CRUD.
- `semantica.auth.store`: SQLite transactional persistence, group membership resolution, effective API key workspace scoping.
- `tests/test_multi_tenant_isolation_and_rbac_flow.py`: Comprehensive end-to-end integration test suite covering all 4 verification objectives.

---

## Out of Scope
- Modifying Active Directory protocol version or schema definitions in OpenLDAP itself (local store and RFC2307 mapping are already compliant).
- Multi-factor authentication (MFA/TOTP), which is deferred to v0.9.0 enterprise roadmap.
- Billing and metering per workspace.

---

## Further Notes
- All changes are backwards-compatible with existing deployments.
- The default `SEMANTICA_ADMIN_PASSWORD` defaults to `1` in this testing profile.
