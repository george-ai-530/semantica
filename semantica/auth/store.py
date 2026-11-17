"""
SQLite metadata store managing identity, workspaces, groups, grants, and API keys.
"""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .crypto import (
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_api_key_hash,
    verify_password,
)
from .models import ApiKey, Group, User, Workspace, WorkspaceGrant


def utc_now_iso() -> str:
    """Return current UTC time formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class AuthStore:
    """Embedded SQLite metadata database for authorization and multi-workspace tenancy."""

    def __init__(self, db_path: Union[str, Path] = ":memory:"):
        self.db_path = str(db_path)
        self._lock = threading.RLock()

        if self.db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            if self.db_path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self._init_schema()

    def close(self) -> None:
        """Close SQLite database connection."""
        with self._lock:
            self.conn.close()

    # -------------------------------------------------------------------------
    # Schema Initializations & Migrations
    # -------------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create tables, indexes, and initial default workspace."""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                display_name TEXT,
                user_type TEXT NOT NULL DEFAULT 'local',
                password_hash TEXT,
                salt TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                global_role TEXT NOT NULL DEFAULT 'user',
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                extra_metadata TEXT NOT NULL DEFAULT '{}'
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_workspaces (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                graph_id TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_groups (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                group_type TEXT NOT NULL DEFAULT 'local',
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_group_members (
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES auth_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_workspace_grants (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                grantee_type TEXT NOT NULL,
                grantee_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Viewer',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (workspace_id, grantee_type, grantee_id),
                FOREIGN KEY (workspace_id) REFERENCES auth_workspaces(id) ON DELETE CASCADE
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                user_id TEXT,
                is_service INTEGER NOT NULL DEFAULT 0,
                scopes TEXT NOT NULL DEFAULT '["*"]',
                allowed_workspaces TEXT NOT NULL DEFAULT '["*"]',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                last_used_at TEXT,
                last_used_ip TEXT,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE SET NULL
            );
            """
        )

        # Indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON auth_users(username);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON auth_api_keys(key_prefix, is_active);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_grants ON auth_workspace_grants(workspace_id, grantee_type, grantee_id);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_group_members_user ON auth_group_members(user_id);"
        )

        # Record migration version 1
        cursor.execute(
            "INSERT OR IGNORE INTO auth_schema_migrations (version, applied_at) VALUES (1, ?);",
            (utc_now_iso(),),
        )

        # Ensure default workspace exists
        now = utc_now_iso()
        cursor.execute(
            """
            INSERT OR IGNORE INTO auth_workspaces (
                id, name, description, graph_id, is_default, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, NULL, ?, ?);
            """,
            ("default", "Default Workspace", "Default global workspace", "graph:default", now, now),
        )

        self.conn.commit()

    # -------------------------------------------------------------------------
    # User Management
    # -------------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        user_type: str = "local",
        password: Optional[str] = None,
        is_admin: bool = False,
        global_role: Optional[str] = None,
        expires_at: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> User:
        """Create a new user with optional password and expiration."""
        uid = user_id or f"usr_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        role = global_role or ("admin" if is_admin else "user")
        meta_json = json.dumps(extra_metadata or {})
        pwd_hash = hash_password(password) if password else None

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO auth_users (
                    id, username, email, display_name, user_type, password_hash,
                    salt, is_active, global_role, expires_at, created_at, updated_at, extra_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?, ?, ?, ?, ?);
                """,
                (
                    uid,
                    username,
                    email,
                    display_name,
                    user_type,
                    pwd_hash,
                    role,
                    expires_at,
                    now,
                    now,
                    meta_json,
                ),
            )
            self.conn.commit()

        return self.get_user(uid)  # type: ignore

    def get_user(self, user_id: str) -> Optional[User]:
        """Fetch user by primary key ID."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_users WHERE id = ?;", (user_id,))
            row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Fetch user by unique username."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_users WHERE username = ?;", (username,))
            row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_id_or_username(self, identifier: str) -> Optional[User]:
        """Fetch user by ID or unique username."""
        return self.get_user(identifier) or self.get_user_by_username(identifier)

    def list_users(self) -> List[User]:
        """List all users."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_users ORDER BY username ASC;")
            rows = cursor.fetchall()
        return [self._row_to_user(r) for r in rows]

    def verify_user_password(self, username: str, password: str) -> Optional[User]:
        """Verify user credentials, checking active state and account expiration."""
        user = self.get_user_by_username(username)
        if not user or not user.is_active or user.is_expired():
            return None
        if not user.password_hash:
            return None
        if verify_password(password, user.password_hash):
            return user
        return None

    def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        global_role: Optional[str] = None,
        expires_at: Optional[str] = None,
        password: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[User]:
        """Update user properties."""
        user = self.get_user(user_id)
        if not user:
            return None

        updates = []
        params = []
        now = utc_now_iso()

        if email is not None:
            updates.append("email = ?")
            params.append(email)
        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        if global_role is not None:
            updates.append("global_role = ?")
            params.append(global_role)
        if expires_at is not None:
            updates.append("expires_at = ?")
            params.append(expires_at)
        if password is not None:
            updates.append("password_hash = ?")
            params.append(hash_password(password))
        if extra_metadata is not None:
            updates.append("extra_metadata = ?")
            params.append(json.dumps(extra_metadata))

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(user_id)
            sql = f"UPDATE auth_users SET {', '.join(updates)} WHERE id = ?;"
            with self._lock:
                self.conn.execute(sql, params)
                self.conn.commit()

        return self.get_user(user_id)

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        with self._lock:
            cursor = self.conn.execute("DELETE FROM auth_users WHERE id = ?;", (user_id,))
            self.conn.commit()
            return cursor.rowcount > 0

    def _row_to_user(self, row: sqlite3.Row) -> User:
        meta = {}
        if row["extra_metadata"]:
            try:
                meta = json.loads(row["extra_metadata"])
            except Exception:
                meta = {}
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            display_name=row["display_name"],
            user_type=row["user_type"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            is_active=bool(row["is_active"]),
            global_role=row["global_role"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            extra_metadata=meta,
        )

    # -------------------------------------------------------------------------
    # Workspace Management
    # -------------------------------------------------------------------------

    def create_workspace(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        description: Optional[str] = None,
        graph_id: Optional[str] = None,
        is_default: bool = False,
        created_by: Optional[str] = None,
    ) -> Workspace:
        """Create a new workspace."""
        wid = workspace_id or f"ws_{uuid.uuid4().hex[:12]}"
        gid = graph_id or f"graph:{wid}"
        now = utc_now_iso()

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO auth_workspaces (
                    id, name, description, graph_id, is_default, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (wid, name, description, gid, 1 if is_default else 0, created_by, now, now),
            )
            self.conn.commit()

        return self.get_workspace(wid)  # type: ignore

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """Fetch workspace by ID."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_workspaces WHERE id = ?;", (workspace_id,))
            row = cursor.fetchone()
        return self._row_to_workspace(row) if row else None

    def get_default_workspace(self) -> Optional[Workspace]:
        """Fetch the default workspace."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_workspaces WHERE is_default = 1 LIMIT 1;")
            row = cursor.fetchone()
        return self._row_to_workspace(row) if row else None

    def list_workspaces(self) -> List[Workspace]:
        """List all workspaces."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_workspaces ORDER BY name ASC;")
            rows = cursor.fetchall()
        return [self._row_to_workspace(r) for r in rows]

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace (cannot delete default workspace)."""
        ws = self.get_workspace(workspace_id)
        if not ws or ws.is_default:
            return False
        with self._lock:
            cursor = self.conn.execute("DELETE FROM auth_workspaces WHERE id = ?;", (workspace_id,))
            self.conn.commit()
            return cursor.rowcount > 0

    def _row_to_workspace(self, row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            graph_id=row["graph_id"],
            is_default=bool(row["is_default"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # Group Management
    # -------------------------------------------------------------------------

    def create_group(
        self,
        name: str,
        group_type: str = "local",
        description: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Group:
        """Create a local or AD group record."""
        gid = group_id or f"grp_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO auth_groups (
                    id, name, group_type, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (gid, name, group_type, description, now, now),
            )
            self.conn.commit()

        return self.get_group(gid)  # type: ignore

    def get_group(self, group_id: str) -> Optional[Group]:
        """Fetch group by ID."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_groups WHERE id = ?;", (group_id,))
            row = cursor.fetchone()
        return self._row_to_group(row) if row else None

    def get_group_by_name(self, name: str) -> Optional[Group]:
        """Fetch group by name."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_groups WHERE name = ?;", (name,))
            row = cursor.fetchone()
        return self._row_to_group(row) if row else None

    def list_groups(self) -> List[Group]:
        """List all groups."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_groups ORDER BY name ASC;")
            rows = cursor.fetchall()
        return [self._row_to_group(r) for r in rows]

    def add_user_to_group(self, group_id: str, user_id: str) -> bool:
        """Add user to a group."""
        now = utc_now_iso()
        with self._lock:
            try:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO auth_group_members (group_id, user_id, created_at)
                    VALUES (?, ?, ?);
                    """,
                    (group_id, user_id, now),
                )
                self.conn.commit()
                return True
            except Exception:
                return False

    def remove_user_from_group(self, group_id: str, user_id: str) -> bool:
        """Remove user from a group."""
        with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM auth_group_members WHERE group_id = ? AND user_id = ?;",
                (group_id, user_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def delete_group(self, group_id: str) -> bool:
        """Delete a group and cascade group memberships."""
        grp = self.get_group(group_id) or self.get_group_by_name(group_id)
        if not grp:
            return False
        with self._lock:
            cursor = self.conn.execute("DELETE FROM auth_groups WHERE id = ?;", (grp.id,))
            self.conn.commit()
            return cursor.rowcount > 0

    def get_user_groups(self, user_id: str) -> List[Group]:
        """List all groups the user belongs to."""
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT g.* FROM auth_groups g
                JOIN auth_group_members m ON g.id = m.group_id
                WHERE m.user_id = ?
                ORDER BY g.name ASC;
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
        return [self._row_to_group(r) for r in rows]

    def list_group_members(self, group_id: str) -> List[User]:
        """List all members of a group."""
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT u.* FROM auth_users u
                JOIN auth_group_members m ON u.id = m.user_id
                WHERE m.group_id = ?
                ORDER BY u.username ASC;
                """,
                (group_id,),
            )
            rows = cursor.fetchall()
        return [self._row_to_user(r) for r in rows]

    def _row_to_group(self, row: sqlite3.Row) -> Group:
        return Group(
            id=row["id"],
            name=row["name"],
            group_type=row["group_type"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # Workspace Grants Management
    # -------------------------------------------------------------------------

    def create_workspace_grant(
        self,
        workspace_id: str,
        grantee_type: str,
        grantee_id: str,
        role: str = "Viewer",
        grant_id: Optional[str] = None,
    ) -> WorkspaceGrant:
        """Assign a workspace role to a user or group."""
        gid = grant_id or f"grt_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO auth_workspace_grants (
                    id, workspace_id, grantee_type, grantee_id, role, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, grantee_type, grantee_id) DO UPDATE SET
                    role = excluded.role,
                    updated_at = excluded.updated_at;
                """,
                (gid, workspace_id, grantee_type, grantee_id, role, now, now),
            )
            self.conn.commit()

        # Query back the grant (either new gid or existing upserted id)
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT * FROM auth_workspace_grants
                WHERE workspace_id = ? AND grantee_type = ? AND grantee_id = ?;
                """,
                (workspace_id, grantee_type, grantee_id),
            )
            row = cursor.fetchone()
        return self._row_to_grant(row)  # type: ignore

    def list_workspace_grants(self, workspace_id: Optional[str] = None) -> List[WorkspaceGrant]:
        """List grants, optionally filtered by workspace."""
        with self._lock:
            if workspace_id:
                cursor = self.conn.execute(
                    "SELECT * FROM auth_workspace_grants WHERE workspace_id = ?;", (workspace_id,)
                )
            else:
                cursor = self.conn.execute("SELECT * FROM auth_workspace_grants;")
            rows = cursor.fetchall()
        return [self._row_to_grant(r) for r in rows]

    def delete_workspace_grant(self, grant_id: str) -> bool:
        """Delete a workspace grant by ID."""
        with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM auth_workspace_grants WHERE id = ?;", (grant_id,)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def get_user_workspace_roles(
        self,
        user_id: str,
        ad_groups: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Calculate effective workspace roles for a user based on user grants and group grants.

        Role hierarchy: Admin > Editor > Viewer.
        """
        role_hierarchy = {"Viewer": 1, "Editor": 2, "Admin": 3}
        reverse_hierarchy = {1: "Viewer", 2: "Editor", 3: "Admin"}

        user = self.get_user(user_id) or self.get_user_by_username(user_id)
        if user and user.global_role == "admin":
            # Global admin has Admin role on all workspaces
            workspaces = self.list_workspaces()
            return {ws.id: "Admin" for ws in workspaces}

        user_identifiers = [user_id]
        if user:
            if user.id not in user_identifiers:
                user_identifiers.append(user.id)
            if user.username not in user_identifiers:
                user_identifiers.append(user.username)

        # Collect all group identifiers for user
        local_groups = self.get_user_groups(user.id if user else user_id)
        group_identifiers = {g.id for g in local_groups} | {g.name for g in local_groups}
        if ad_groups:
            group_identifiers.update(ad_groups)

        effective_roles: Dict[str, int] = {}

        with self._lock:
            # 1. Direct user grants
            placeholders = ",".join("?" for _ in user_identifiers)
            cursor = self.conn.execute(
                f"""
                SELECT workspace_id, role FROM auth_workspace_grants
                WHERE grantee_type = 'user' AND grantee_id IN ({placeholders});
                """,
                tuple(user_identifiers),
            )
            for row in cursor.fetchall():
                ws_id = row["workspace_id"]
                level = role_hierarchy.get(row["role"], 1)
                effective_roles[ws_id] = max(effective_roles.get(ws_id, 0), level)

            # 2. Group grants
            if group_identifiers:
                placeholders = ",".join("?" for _ in group_identifiers)
                cursor = self.conn.execute(
                    f"""
                    SELECT workspace_id, role FROM auth_workspace_grants
                    WHERE grantee_type = 'group' AND grantee_id IN ({placeholders});
                    """,
                    list(group_identifiers),
                )
                for row in cursor.fetchall():
                    ws_id = row["workspace_id"]
                    level = role_hierarchy.get(row["role"], 1)
                    effective_roles[ws_id] = max(effective_roles.get(ws_id, 0), level)

        res = {ws_id: reverse_hierarchy.get(lvl, "Viewer") for ws_id, lvl in effective_roles.items()}
        if "default" not in res:
            res["default"] = "Viewer"
        return res

    def _row_to_grant(self, row: sqlite3.Row) -> WorkspaceGrant:
        return WorkspaceGrant(
            id=row["id"],
            workspace_id=row["workspace_id"],
            grantee_type=row["grantee_type"],
            grantee_id=row["grantee_id"],
            role=row["role"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # API Key Management
    # -------------------------------------------------------------------------

    def create_api_key(
        self,
        name: str,
        user_id: Optional[str] = None,
        is_service: bool = False,
        scopes: Optional[List[str]] = None,
        allowed_workspaces: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> Tuple[ApiKey, str]:
        """Generate and store an API key.

        Returns:
            Tuple of (ApiKey record, raw_secret_key). The raw secret key is only
            returned upon creation and is never stored in plaintext.
        """
        raw_key, key_prefix = generate_api_key()
        key_hash, salt = hash_api_key(raw_key)
        kid = key_id or f"key_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        scopes_json = json.dumps(scopes or ["*"])
        workspaces_json = json.dumps(allowed_workspaces or ["*"])

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO auth_api_keys (
                    id, name, key_prefix, key_hash, salt, user_id, is_service,
                    scopes, allowed_workspaces, is_active, created_at, expires_at,
                    last_used_at, last_used_ip, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, NULL);
                """,
                (
                    kid,
                    name,
                    key_prefix,
                    key_hash,
                    salt,
                    user_id,
                    1 if is_service else 0,
                    scopes_json,
                    workspaces_json,
                    now,
                    expires_at,
                ),
            )
            self.conn.commit()

        api_key = self.get_api_key(kid)
        return api_key, raw_key  # type: ignore

    def get_api_key(self, key_id: str) -> Optional[ApiKey]:
        """Fetch API key metadata by ID."""
        with self._lock:
            cursor = self.conn.execute("SELECT * FROM auth_api_keys WHERE id = ?;", (key_id,))
            row = cursor.fetchone()
        return self._row_to_api_key(row) if row else None

    def list_api_keys(self, user_id: Optional[str] = None) -> List[ApiKey]:
        """List all active or registered API keys, optionally scoped to a user."""
        with self._lock:
            if user_id is not None:
                cursor = self.conn.execute(
                    "SELECT * FROM auth_api_keys WHERE user_id = ? ORDER BY created_at DESC;",
                    (user_id,),
                )
            else:
                cursor = self.conn.execute("SELECT * FROM auth_api_keys ORDER BY created_at DESC;")
            rows = cursor.fetchall()
        return [self._row_to_api_key(r) for r in rows]

    def revoke_api_key(self, key_id: str) -> bool:
        """Immediately revoke an API key."""
        now = utc_now_iso()
        with self._lock:
            cursor = self.conn.execute(
                """
                UPDATE auth_api_keys
                SET is_active = 0, revoked_at = ?
                WHERE id = ?;
                """,
                (now, key_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def verify_api_key(
        self,
        raw_key: str,
        client_ip: Optional[str] = None,
    ) -> Optional[Tuple[ApiKey, Optional[User]]]:
        """Verify raw API key using constant-time hash comparison and update audit trail.

        Returns:
            Tuple of (ApiKey, Optional[User]) if key is valid and active; None otherwise.
        """
        if not raw_key or len(raw_key) < 12:
            return None

        prefix = raw_key[:12]
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT * FROM auth_api_keys
                WHERE key_prefix = ? AND is_active = 1 AND revoked_at IS NULL;
                """,
                (prefix,),
            )
            rows = cursor.fetchall()

        for row in rows:
            if verify_api_key_hash(raw_key, row["key_hash"], row["salt"]):
                key_obj = self._row_to_api_key(row)
                if not key_obj.is_valid():
                    return None

                user = None
                if key_obj.user_id:
                    user = self.get_user(key_obj.user_id)
                    if not user or not user.is_active or user.is_expired():
                        return None

                # Update audit log fields
                now = utc_now_iso()
                with self._lock:
                    self.conn.execute(
                        """
                        UPDATE auth_api_keys
                        SET last_used_at = ?, last_used_ip = ?
                        WHERE id = ?;
                        """,
                        (now, client_ip, key_obj.id),
                    )
                    self.conn.commit()

                key_obj.last_used_at = now
                key_obj.last_used_ip = client_ip
                return key_obj, user

        return None

    def get_effective_workspaces_for_api_key(
        self,
        api_key: ApiKey,
    ) -> Tuple[List[str], Dict[str, str]]:
        """Resolve permitted workspaces and role mapping for an API key.

        Personal keys strictly inherit permissions from their user owner.
        Service account keys use their explicitly granted workspace scope.
        """
        if api_key.is_service:
            if "*" in api_key.allowed_workspaces:
                all_ws = [ws.id for ws in self.list_workspaces()]
                return all_ws, {ws: "Admin" for ws in all_ws}
            return (
                list(api_key.allowed_workspaces),
                {ws: "Editor" for ws in api_key.allowed_workspaces},
            )

        # Personal API key: strictly inherit user permissions
        if not api_key.user_id:
            return [], {}

        user = self.get_user(api_key.user_id) or self.get_user_by_username(api_key.user_id)
        if not user or not user.is_active or user.is_expired():
            return [], {}

        user_roles = self.get_user_workspace_roles(user.id)
        if not user_roles:
            user_roles = {"default": "Viewer"}

        if "*" in api_key.allowed_workspaces:
            return list(user_roles.keys()), user_roles

        allowed_set = set(api_key.allowed_workspaces)
        scoped_roles = {ws: role for ws, role in user_roles.items() if ws in allowed_set}
        if not scoped_roles and "default" in allowed_set:
            scoped_roles = {"default": "Viewer"}
        return list(scoped_roles.keys()), scoped_roles

    def _row_to_api_key(self, row: sqlite3.Row) -> ApiKey:
        try:
            scopes = json.loads(row["scopes"])
        except Exception:
            scopes = ["*"]
        try:
            workspaces = json.loads(row["allowed_workspaces"])
        except Exception:
            workspaces = ["*"]

        return ApiKey(
            id=row["id"],
            name=row["name"],
            key_prefix=row["key_prefix"],
            key_hash=row["key_hash"],
            salt=row["salt"],
            user_id=row["user_id"],
            is_service=bool(row["is_service"]),
            scopes=scopes,
            allowed_workspaces=workspaces,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            last_used_at=row["last_used_at"],
            last_used_ip=row["last_used_ip"],
            revoked_at=row["revoked_at"],
        )


_global_auth_store: Optional[AuthStore] = None
_store_lock = threading.Lock()


def get_default_auth_store_path() -> Optional[str]:
    """Retrieve default database file path from environment or storage root."""
    return (
        os.environ.get("SEMANTICA_AUTH_DB")
        or os.environ.get("SEMANTICA_AUTH_STORAGE_PATH")
        or os.environ.get("SEMANTICA_AUTH_DB_PATH")
        or "semantica_auth.db"
    )


def get_auth_store(db_path: Optional[str] = None) -> Optional[AuthStore]:
    """Get or create singleton AuthStore instance."""
    global _global_auth_store
    target_path = db_path or get_default_auth_store_path()
    if target_path is None:
        return _global_auth_store

    with _store_lock:
        if _global_auth_store is None or _global_auth_store.db_path != target_path:
            _global_auth_store = AuthStore(target_path)
        return _global_auth_store


def set_auth_store(store: Optional[AuthStore]) -> None:
    """Set or override global AuthStore instance (useful for testing)."""
    global _global_auth_store
    with _store_lock:
        _global_auth_store = store
