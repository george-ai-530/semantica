# 01: Auth Store Passwords and Seed Accounts

**What to build:**
Configure unified default passwords (`1`) for local test accounts (`admin`, `user_a`, `user_b`). Automatically seed `user_a` and `user_b` with their isolated personal workspaces (`ws_user_a` and `ws_user_b`), granting initial Admin role to their respective personal workspaces.

**Blocked by:** None (can start immediately).

**Status:** closed

- [x] Default `admin` account password hash resolves to `1`.
- [x] Test user `user_a` exists with password `1`, linked to workspace `ws_user_a`.
- [x] Test user `user_b` exists with password `1`, linked to workspace `ws_user_b`.
- [ ] Existing database updates passwords on bootstrap without data corruption.
