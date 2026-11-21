# 02: Admin Group and Role Routes

**What to build:**
Enable full admin management of local groups, group members, and workspace role assignments. Admins can create local groups, add users by username or user ID, remove members, and assign workspace roles (`Admin`, `Editor`, `Viewer`) to users or groups.

**Blocked by:** 01: Auth Store Passwords and Seed Accounts

**Status:** closed

- [x] `POST /api/admin/groups` creates new local security group.
- [x] `POST /api/admin/groups/{group_id}/members` adds user by `user_id` or `username`.
- [x] `DELETE /api/admin/groups/{group_id}/members/{user_id}` removes user from group.
- [x] `POST /api/admin/workspaces/{workspace_id}/grants` assigns workspace role (`Admin`, `Editor`, `Viewer`) to user or group.
- [x] `DELETE /api/admin/workspaces/{workspace_id}/grants/{grant_id}` revokes workspace grant.
