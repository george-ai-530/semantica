/**
 * Authentication and Multi-Workspace Client Store.
 *
 * Manages JWT tokens, authenticated user profile, active workspace context,
 * and sets up a global fetch interceptor that attaches:
 *   - `Authorization: Bearer <token>`
 *   - `X-Workspace-ID: <active_workspace>`
 * to all outgoing API requests.
 */

import { useEffect, useSyncExternalStore } from 'react';

export interface AuthUser {
  id: string;
  username: string;
  display_name?: string;
  email?: string;
  global_role: string;
  groups: string[];
  authorized_workspaces: string[];
  workspace_roles: Record<string, string>;
  type?: 'ad' | 'local' | 'service';
}

export interface WorkspaceItem {
  id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  role?: string;
}

const TOKEN_STORAGE_KEY = 'semantica_auth_token';
const WORKSPACE_STORAGE_KEY = 'semantica_active_workspace';

function getStoredItem(key: string): string | null {
  try {
    if (typeof localStorage !== 'undefined') {
      return localStorage.getItem(key);
    }
  } catch {
    // ignore
  }
  return null;
}

function setStoredItem(key: string, val: string | null) {
  try {
    if (typeof localStorage !== 'undefined') {
      if (val === null) {
        localStorage.removeItem(key);
      } else {
        localStorage.setItem(key, val);
      }
    }
  } catch {
    // ignore
  }
}

// In-memory reactive state
let currentToken: string | null = getStoredItem(TOKEN_STORAGE_KEY);
let currentUser: AuthUser | null = null;
let currentWorkspace: string = getStoredItem(WORKSPACE_STORAGE_KEY) || 'default';
let currentWorkspaces: WorkspaceItem[] = [
  { id: 'default', name: '默认工作区 (Default)', is_default: true, role: 'Admin' },
];

let storeVersion = 0;
const listeners = new Set<() => void>();

function notify() {
  storeVersion++;
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

function getSnapshot() {
  return storeVersion;
}

// ---------------------------------------------------------------------------
// Global Fetch Interceptor
// ---------------------------------------------------------------------------
let interceptorInstalled = false;

export function installFetchInterceptor() {
  if (interceptorInstalled || typeof window === 'undefined') {
    return;
  }
  interceptorInstalled = true;

  const originalFetch = window.fetch;
  const interceptedFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const initObj = init ? { ...init } : {};
    const headers = new Headers(initObj.headers || {});

    // Attach active workspace header
    if (!headers.has('X-Workspace-ID')) {
      headers.set('X-Workspace-ID', currentWorkspace);
    }

    // Attach Bearer JWT token if user is signed in
    if (currentToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${currentToken}`);
    }

    initObj.headers = headers;
    const response = await originalFetch(input, initObj);

    // If 401 received on a protected route with a token, the token might be expired
    if (response.status === 401 && currentToken) {
      const urlStr = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      // Do not clear on login failures
      if (!urlStr.includes('/api/auth/login')) {
        console.warn('[AuthInterceptor] 401 Unauthorized encountered, token may be expired.');
      }
    }

    return response;
  };

  window.fetch = interceptedFetch;
  if (typeof globalThis !== 'undefined') {
    globalThis.fetch = interceptedFetch as any;
  }
}

// Automatically install interceptor on module load
installFetchInterceptor();

// ---------------------------------------------------------------------------
// Store Actions
// ---------------------------------------------------------------------------

export function getAuthToken(): string | null {
  return currentToken;
}

export function getCurrentUser(): AuthUser | null {
  return currentUser;
}

export function getActiveWorkspace(): string {
  return currentWorkspace;
}

export function getWorkspaces(): WorkspaceItem[] {
  return currentWorkspaces;
}

export function setActiveWorkspace(workspaceId: string) {
  currentWorkspace = workspaceId;
  setStoredItem(WORKSPACE_STORAGE_KEY, workspaceId);
  notify();
}

export function setAuthToken(token: string | null) {
  currentToken = token;
  if (token) {
    setStoredItem(TOKEN_STORAGE_KEY, token);
  } else {
    setStoredItem(TOKEN_STORAGE_KEY, null);
    currentUser = null;
  }
  notify();
}

export async function fetchUserWorkspaces(): Promise<WorkspaceItem[]> {
  try {
    const res = await fetch('/api/auth/workspaces');
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        currentWorkspaces = data;
        // If current workspace is not in list, select the first one
        if (!data.some((ws) => ws.id === currentWorkspace)) {
          setActiveWorkspace(data[0].id);
        }
        notify();
        return data;
      }
    }
  } catch (err) {
    console.debug('Failed to fetch workspaces:', err);
  }
  return currentWorkspaces;
}

export async function refreshProfile(): Promise<AuthUser | null> {
  if (!currentToken) {
    return null;
  }
  try {
    const res = await fetch('/api/auth/me');
    if (res.ok) {
      const data = await res.json();
      currentUser = {
        id: data.user_id,
        username: data.username,
        display_name: data.extra?.display_name || data.username,
        email: data.extra?.email,
        global_role: data.global_role,
        groups: data.groups || [],
        authorized_workspaces: data.authorized_workspaces || ['default'],
        workspace_roles: data.workspace_roles || {},
        type: data.extra?.type,
      };
      notify();
      await fetchUserWorkspaces();
      return currentUser;
    } else if (res.status === 401) {
      setAuthToken(null);
    }
  } catch (err) {
    console.debug('Failed to refresh profile:', err);
  }
  return null;
}

export async function login(
  username: string,
  password: string,
  loginType?: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: username.trim(),
        password,
        login_type: loginType || undefined,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      return {
        success: false,
        error: data.detail || '登录失败，请检查凭据。',
      };
    }

    currentToken = data.access_token;
    setStoredItem(TOKEN_STORAGE_KEY, data.access_token);
    if (data.user) {
      currentUser = {
        id: data.user.id,
        username: data.user.username,
        display_name: data.user.display_name,
        email: data.user.email,
        global_role: data.user.global_role,
        groups: data.user.groups || [],
        authorized_workspaces: data.user.authorized_workspaces || ['default'],
        workspace_roles: data.user.workspace_roles || {},
        type: data.user.type,
      };
    }
    notify();
    await fetchUserWorkspaces();
    return { success: true };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : '网络连接失败，请稍后重试。',
    };
  }
}

export function logout() {
  setAuthToken(null);
  currentWorkspace = 'default';
  setStoredItem(WORKSPACE_STORAGE_KEY, 'default');
  notify();
}

// ---------------------------------------------------------------------------
// React Hook
// ---------------------------------------------------------------------------

export function useAuth() {
  useSyncExternalStore(subscribe, getSnapshot);

  // Initialize profile on mount if token exists
  useEffect(() => {
    if (currentToken && !currentUser) {
      refreshProfile();
    }
  }, []);

  return {
    token: currentToken,
    user: currentUser,
    isAuthenticated: Boolean(currentToken && currentUser),
    isAdmin: currentUser?.global_role === 'admin',
    activeWorkspace: currentWorkspace,
    workspaces: currentWorkspaces,
    setActiveWorkspace,
    login,
    logout,
    refreshProfile,
    fetchUserWorkspaces,
  };
}
