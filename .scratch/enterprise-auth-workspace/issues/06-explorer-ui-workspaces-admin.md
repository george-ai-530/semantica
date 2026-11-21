# 06: Explorer Frontend Workspace Switcher, Key Settings & Admin Console

**What to build:**
Deliver the end-to-end user-facing UI in the React 19 Explorer: a persistent Workspace Switcher in the top navigation bar, a Personal Settings drawer for generating/copying personal API keys, and an Admin Console (`/admin`) for administrators to manage external guests, workspace grants, local groups, and view/revoke global API keys.

**Blocked by:** 02: Active Directory LDAP Direct Bind & JWT Login Flow, 05: Personal API Key Self-Service & Admin Management REST APIs

**Assigned Model:** Gemini 3.8 Flash

**Status:** closed

- [x] Top navigation bar Workspace Switcher dropdown reflecting active workspace and user grants
- [x] User Settings modal with one-time API key display and revocation list
- [x] Admin Console workspace route (`/admin`) with tabs: External Guests, Workspaces & Grants, Local Groups, API Keys
- [x] Form for provisioning external guests with datepicker for expiration dates
- [x] Full end-to-end browser walkthrough verifying UI state across roles
