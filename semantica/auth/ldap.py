"""
Active Directory LDAP (Port 389) Client and Mock Provider.

Implements LDAP direct bind and search-and-bind authentication against corporate
Active Directory domains with non-blocking execution using FastAPI's run_in_threadpool.
Extracts user identity (sAMAccountName), display name, email, and normalized memberOf security groups.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable

from fastapi import Request
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def extract_group_names(member_of: Union[List[str], str, None]) -> List[str]:
    """Extract and normalize group names from LDAP memberOf attributes.

    Active Directory returns group memberships as a list of Distinguished Names (DNs):
    e.g. 'CN=Finance-Team,OU=Security Groups,DC=corp,DC=example,DC=com'.

    This function normalizes entries into:
      1. Friendly short common name (e.g. 'Finance-Team')
      2. 'CN=...' prefixed name (e.g. 'CN=Finance-Team')
      3. Full DN string (e.g. 'CN=Finance-Team,OU=Security Groups,DC=corp,DC=example,DC=com')

    This ensures workspace grant lookups match regardless of whether an admin
    specified the group by CN, by CN= prefix, or by full DN.
    """
    if not member_of:
        return []

    if isinstance(member_of, str):
        raw_list = [member_of]
    else:
        raw_list = list(member_of)

    groups = set()
    for entry in raw_list:
        if not entry:
            continue
        entry_str = str(entry).strip()
        if not entry_str:
            continue
        groups.add(entry_str)

        # Parse components separated by comma
        parts = [p.strip() for p in entry_str.split(",") if p.strip()]
        has_cn = False
        for part in parts:
            if part.upper().startswith("CN="):
                has_cn = True
                cn_full = part
                cn_name = part[3:].strip()
                groups.add(cn_full)
                if cn_name:
                    groups.add(cn_name)
                break

        if not has_cn and not entry_str.upper().startswith("CN="):
            groups.add(f"CN={entry_str}")

    return sorted(groups)


@dataclass
class LDAPUser:
    """Authenticated user profile extracted from Active Directory."""

    username: str  # sAMAccountName
    display_name: Optional[str] = None
    email: Optional[str] = None
    groups: List[str] = field(default_factory=list)  # normalized memberOf groups
    dn: Optional[str] = None
    extra_attributes: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LDAPClientProtocol(Protocol):
    """Protocol for LDAP authentication clients."""

    async def authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """Authenticate user against LDAP directory and retrieve profile with groups.

        Returns:
            LDAPUser if credentials are valid, None otherwise.
        """
        ...


class ActiveDirectoryClient:
    """Active Directory LDAP (Port 389) authentication and group query client.

    Supports direct user bind flow and service account bind-and-search flow.
    Socket I/O is dispatched through run_in_threadpool to keep the FastAPI
    async event loop non-blocking.
    """

    def __init__(
        self,
        server: Optional[str] = None,
        port: Optional[int] = None,
        use_ssl: Optional[bool] = None,
        base_dn: Optional[str] = None,
        domain: Optional[str] = None,
        bind_dn: Optional[str] = None,
        bind_password: Optional[str] = None,
        user_dn_template: Optional[str] = None,
        connect_timeout: int = 5,
    ):
        self.server = (
            server
            or os.environ.get("SEMANTICA_LDAP_SERVER")
            or os.environ.get("SEMANTICA_LDAP_HOST")
            or "127.0.0.1"
        )
        self.port = (
            port
            if port is not None
            else int(os.environ.get("SEMANTICA_LDAP_PORT", "389"))
        )
        self.use_ssl = (
            use_ssl
            if use_ssl is not None
            else (os.environ.get("SEMANTICA_LDAP_USE_SSL", "").strip().lower() in ("true", "1"))
        )
        self.base_dn = (
            base_dn
            or os.environ.get("SEMANTICA_LDAP_BASE_DN", "dc=corp,dc=example,dc=com")
        )
        self.domain = domain or os.environ.get("SEMANTICA_LDAP_DOMAIN", "")
        self.bind_dn = bind_dn or os.environ.get("SEMANTICA_LDAP_BIND_DN")
        self.bind_password = bind_password or os.environ.get("SEMANTICA_LDAP_BIND_PASSWORD")
        self.user_dn_template = user_dn_template or os.environ.get("SEMANTICA_LDAP_USER_DN_TEMPLATE")
        self.connect_timeout = connect_timeout

    @classmethod
    def from_env(cls) -> "ActiveDirectoryClient":
        """Instantiate client using SEMANTICA_LDAP_* environment variables."""
        return cls()

    def _get_reachable_server(self) -> str:
        """Resolve LDAP server hostname, attempting fallback IPs/hosts if DNS lookup fails."""
        import socket
        candidates = [self.server]
        env_fallback = os.environ.get("SEMANTICA_LDAP_FALLBACK_SERVER")
        if env_fallback:
            candidates.append(env_fallback)
        candidates.extend(["openldap", "192.168.1.15", "host.docker.internal", "172.17.0.1", "127.0.0.1"])

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.8)
                res = sock.connect_ex((candidate, self.port))
                sock.close()
                if res == 0:
                    return candidate
            except Exception:
                continue
        return self.server

    def authenticate_sync(self, username: str, password: str) -> Optional[LDAPUser]:
        """Perform synchronous LDAP bind and query against Active Directory."""
        if not username or not password:
            return None

        clean_user = username.strip()

        try:
            from ldap3 import ALL, Connection, Server, SUBTREE
            from ldap3.core.exceptions import LDAPException
            from ldap3.utils.conv import escape_filter_chars
        except ImportError:
            logger.error("ldap3 library is not installed. Active Directory authentication unavailable.")
            return None

        escaped_user = escape_filter_chars(clean_user)
        target_server = self._get_reachable_server()

        try:
            server = Server(
                target_server,
                port=self.port,
                use_ssl=self.use_ssl,
                get_info=ALL,
                connect_timeout=self.connect_timeout,
            )

            # Strategy 1: Service Account Bind + Search User DN + Verify User Bind
            if self.bind_dn and self.bind_password:
                admin_conn = Connection(
                    server,
                    user=self.bind_dn,
                    password=self.bind_password,
                    auto_bind=True,
                )
                # Strategy 1: Service Account Bind + Search User DN + Verify User Bind
                # First attempt Microsoft Active Directory schema (sAMAccountName)
                # Fall back to RFC2307 / OpenLDAP schema (uid) if sAMAccountName is not supported
                search_ok = False
                try:
                    search_filter = f"(&(objectClass=user)(sAMAccountName={escaped_user}))"
                    admin_conn.search(
                        search_base=self.base_dn,
                        search_filter=search_filter,
                        search_scope=SUBTREE,
                        attributes=["sAMAccountName", "displayName", "mail", "memberOf", "distinguishedName"],
                    )
                    search_ok = True
                except LDAPException:
                    search_ok = False

                if not search_ok or not admin_conn.entries:
                    search_filter = f"(|(&(objectClass=inetOrgPerson)(uid={escaped_user}))(uid={escaped_user}))"
                    admin_conn.search(
                        search_base=self.base_dn,
                        search_filter=search_filter,
                        search_scope=SUBTREE,
                        attributes=["uid", "displayName", "cn", "mail", "memberOf", "distinguishedName"],
                    )

                if not admin_conn.entries:
                    admin_conn.unbind()
                    return None

                entry = admin_conn.entries[0]
                user_dn = str(getattr(entry, "entry_dn", None) or getattr(entry, "distinguishedName", clean_user))
                admin_conn.unbind()

                # Verify user password against discovered DN
                user_conn = Connection(
                    server,
                    user=user_dn,
                    password=password,
                )
                if not user_conn.bind():
                    return None
                user_conn.unbind()

                # Extract attributes
                disp_attr = getattr(entry, "displayName", None) or getattr(entry, "cn", None)
                display_name_val = str(disp_attr.value) if disp_attr and disp_attr.value else clean_user
                mail_attr = getattr(entry, "mail", None)
                mail_val = str(mail_attr.value) if mail_attr and mail_attr.value else None

                member_of = []
                if hasattr(entry, "memberOf") and entry.memberOf:
                    member_of = (
                        [str(x) for x in entry.memberOf.values]
                        if hasattr(entry.memberOf, "values")
                        else [str(entry.memberOf.value)]
                    )

                return LDAPUser(
                    username=clean_user,
                    display_name=display_name_val,
                    email=mail_val,
                    groups=extract_group_names(member_of),
                    dn=user_dn,
                )

            # Strategy 2: Direct User Bind
            if "@" in clean_user or "\\" in clean_user:
                bind_user = clean_user
            elif self.user_dn_template:
                bind_user = self.user_dn_template.format(
                    username=clean_user,
                    domain=self.domain,
                    base_dn=self.base_dn,
                )
            elif self.domain:
                bind_user = f"{clean_user}@{self.domain}"
            else:
                bind_user = clean_user

            conn = Connection(
                server,
                user=bind_user,
                password=password,
            )
            if not conn.bind():
                return None

            # Credentials valid. Search user object for sAMAccountName, displayName, mail, memberOf
            display_name_val = clean_user
            mail_val = None
            member_of = []
            user_dn = bind_user

            try:
                search_ok = False
                try:
                    search_filter = f"(sAMAccountName={escaped_user})"
                    conn.search(
                        search_base=self.base_dn,
                        search_filter=search_filter,
                        search_scope=SUBTREE,
                        attributes=["sAMAccountName", "displayName", "mail", "memberOf", "distinguishedName"],
                    )
                    search_ok = True
                except LDAPException:
                    search_ok = False

                if not search_ok or not conn.entries:
                    search_filter = f"(uid={escaped_user})"
                    conn.search(
                        search_base=self.base_dn,
                        search_filter=search_filter,
                        search_scope=SUBTREE,
                        attributes=["uid", "displayName", "cn", "mail", "memberOf", "distinguishedName"],
                    )

                if conn.entries:
                    entry = conn.entries[0]
                    dn_attr = getattr(entry, "entry_dn", None) or getattr(entry, "distinguishedName", None)
                    if dn_attr:
                        user_dn = str(getattr(dn_attr, "value", dn_attr))
                    disp_attr = getattr(entry, "displayName", None) or getattr(entry, "cn", None)
                    if disp_attr and disp_attr.value:
                        display_name_val = str(disp_attr.value)
                    mail_attr = getattr(entry, "mail", None)
                    if mail_attr and mail_attr.value:
                        mail_val = str(mail_attr.value)
                    if hasattr(entry, "memberOf") and entry.memberOf:
                        member_of = (
                            [str(x) for x in entry.memberOf.values]
                            if hasattr(entry.memberOf, "values")
                            else [str(entry.memberOf.value)]
                        )
            except Exception as search_err:
                logger.warning(f"LDAP search for user attributes encountered an error: {search_err}")
            finally:
                conn.unbind()

            return LDAPUser(
                username=clean_user,
                display_name=display_name_val,
                email=mail_val,
                groups=extract_group_names(member_of),
                dn=user_dn,
            )

        except LDAPException as exc:
            logger.warning(f"LDAP bind failed for {clean_user}: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error in Active Directory LDAP authentication for {clean_user}: {exc}")
            return None

    async def authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """Non-blocking LDAP authentication executed via run_in_threadpool."""
        return await run_in_threadpool(self.authenticate_sync, username, password)


class MockLDAPClient:
    """Deterministic in-memory mock LDAP provider for tests."""

    def __init__(self, directory: Optional[Dict[str, Dict[str, Any]]] = None):
        self._directory: Dict[str, Dict[str, Any]] = {}
        if directory:
            for username, data in directory.items():
                self.add_user(
                    username=username,
                    password=data.get("password", ""),
                    display_name=data.get("display_name"),
                    email=data.get("email"),
                    groups=data.get("groups", []),
                    dn=data.get("dn"),
                )

    def add_user(
        self,
        username: str,
        password: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        groups: Optional[List[str]] = None,
        dn: Optional[str] = None,
    ) -> None:
        """Register or update an LDAP user in the mock directory."""
        clean_user = username.strip()
        self._directory[clean_user.lower()] = {
            "username": clean_user,
            "password": password,
            "display_name": display_name or clean_user,
            "email": email or f"{clean_user}@corp.example.com",
            "groups": list(groups or []),
            "dn": dn or f"CN={clean_user},OU=Users,DC=corp,DC=example,DC=com",
        }

    def remove_user(self, username: str) -> None:
        """Remove a user from the mock directory."""
        self._directory.pop(username.strip().lower(), None)

    def set_user_password(self, username: str, password: str) -> None:
        """Update a mock user's password."""
        user = self._directory.get(username.strip().lower())
        if user:
            user["password"] = password

    def set_user_groups(self, username: str, groups: List[str]) -> None:
        """Update a mock user's memberOf groups."""
        user = self._directory.get(username.strip().lower())
        if user:
            user["groups"] = list(groups)

    def authenticate_sync(self, username: str, password: str) -> Optional[LDAPUser]:
        """Verify credentials synchronously against the in-memory directory."""
        if not username or not password:
            return None
        record = self._directory.get(username.strip().lower())
        if not record:
            return None
        if record["password"] != password:
            return None

        return LDAPUser(
            username=record["username"],
            display_name=record["display_name"],
            email=record["email"],
            groups=extract_group_names(record["groups"]),
            dn=record["dn"],
        )

    async def authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """Asynchronously authenticate against mock directory."""
        return await run_in_threadpool(self.authenticate_sync, username, password)


# Global LDAP client registry for runtime and dependency injection
_global_ldap_client: Optional[LDAPClientProtocol] = None


def get_ldap_client() -> LDAPClientProtocol:
    """Get the currently configured LDAP client, or default ActiveDirectoryClient."""
    global _global_ldap_client
    if _global_ldap_client is not None:
        return _global_ldap_client
    return ActiveDirectoryClient.from_env()


def set_ldap_client(client: Optional[LDAPClientProtocol]) -> None:
    """Set or override the global LDAP client."""
    global _global_ldap_client
    _global_ldap_client = client


def get_ldap_client_dependency(request: Request) -> LDAPClientProtocol:
    """FastAPI dependency resolving the LDAP client from app state or global."""
    client = getattr(request.app.state, "ldap_client", None)
    if client is not None:
        return client
    return get_ldap_client()
