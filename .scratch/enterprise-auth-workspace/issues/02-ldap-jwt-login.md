# 02: Active Directory LDAP (Port 389) Direct Bind & JWT Login Flow

**What to build:**
Implement the `/api/auth/login` endpoint supporting dual authentication: internal enterprise employees authenticating against corporate Active Directory via LDAP 389 (with `sAMAccountName` and `memberOf` group extraction), and external guest users authenticating against local password hashes with account expiration validation. Successful logins issue cryptographically signed, short-lived JWT tokens.

**Blocked by:** 01: Auth Metadata Store & Gateway Ingress Pipeline

**Assigned Model:** Gemini 3.8 Flash

**Status:** closed

- [x] Pluggable `LDAPClientProtocol` executing non-blocking LDAP Bind via `run_in_threadpool`
- [x] Retrieval and normalization of user `memberOf` AD security groups
- [x] Local guest password verification with Argon2/bcrypt and mandatory expiry check
- [x] JWT issuance with claims (`sub`, `type`, `groups`, `exp`) and verification logic
- [x] Deterministic in-memory Mock LDAP test suite covering success, bad credentials, and expired guests
