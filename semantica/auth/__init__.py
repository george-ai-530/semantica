"""
Enterprise authentication, multi-workspace isolation, and metadata storage.
"""

from .admin_routes import (
    require_admin,
    router as admin_router,
)
from .crypto import (
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_api_key_hash,
    verify_password,
)
from .dependencies import (
    anonymous_access_allowed,
    get_current_identity,
    get_expected_api_key,
    is_valid_api_key,
    require_auth,
    require_workspace_role,
)
from .ldap import (
    ActiveDirectoryClient,
    LDAPClientProtocol,
    LDAPUser,
    MockLDAPClient,
    extract_group_names,
    get_ldap_client,
    set_ldap_client,
)
from .models import (
    ApiKey,
    Group,
    RequestContext,
    User,
    Workspace,
    WorkspaceGrant,
)
from .routes import (
    LoginRequest,
    LoginResponse,
    router as auth_router,
)
from .store import (
    AuthStore,
    get_auth_store,
    set_auth_store,
)
from .tokens import (
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    verify_access_token,
)

__all__ = [
    "ActiveDirectoryClient",
    "ApiKey",
    "AuthStore",
    "Group",
    "LDAPClientProtocol",
    "LDAPUser",
    "LoginRequest",
    "LoginResponse",
    "MockLDAPClient",
    "RequestContext",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "User",
    "Workspace",
    "WorkspaceGrant",
    "admin_router",
    "anonymous_access_allowed",
    "auth_router",
    "create_access_token",
    "extract_group_names",
    "generate_api_key",
    "get_auth_store",
    "get_current_identity",
    "get_expected_api_key",
    "get_ldap_client",
    "hash_api_key",
    "hash_password",
    "is_valid_api_key",
    "require_admin",
    "require_auth",
    "require_workspace_role",
    "set_auth_store",
    "set_ldap_client",
    "verify_access_token",
    "verify_api_key_hash",
    "verify_password",
]
