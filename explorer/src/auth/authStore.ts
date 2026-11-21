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
import { clearGraph } from '../store/graphStore';

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

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
  activeWorkspace: string;
  workspaces: WorkspaceItem[];
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

// In-memory reactive immutable state
let authState: AuthState = {
  token: getStoredItem(TOKEN_STORAGE_KEY),
  user: null,
  activeWorkspace: getStoredItem(WORKSPACE_STORAGE_KEY) || 'default',
  workspaces: [
    { id: 'default', name: '默认工作区 (Default)', is_default: true, role: 'Admin' },
  ],
};

const listeners = new Set<() => void>();

function notify() {
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

function getSnapshot(): AuthState {
  return authState;
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
      headers.set('X-Workspace-ID', authState.activeWorkspace);
    }

    // Attach Bearer JWT token if user is signed in
    if (authState.token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${authState.token}`);
    }

    initObj.headers = headers;
    const response = await originalFetch(input, initObj);

    // If 401 received on a protected route with a token, the token might be expired
    if (response.status === 401 && authState.token) {
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
  return authState.token;
}

export function getCurrentUser(): AuthUser | null {
  return authState.user;
}

export function getActiveWorkspace(): string {
  return authState.activeWorkspace;
}

export function getWorkspaces(): WorkspaceItem[] {
  return authState.workspaces;
}

export function setActiveWorkspace(workspaceId: string) {
  authState = {
    ...authState,
    activeWorkspace: workspaceId,
  };
  setStoredItem(WORKSPACE_STORAGE_KEY, workspaceId);
  notify();
}

export function setAuthToken(token: string | null) {
  authState = {
    ...authState,
    token,
    user: token ? authState.user : null,
  };
  setStoredItem(TOKEN_STORAGE_KEY, token);
  notify();
}

export async function fetchUserWorkspaces(): Promise<WorkspaceItem[]> {
  try {
    const res = await fetch('/api/auth/workspaces');
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        // If activeWorkspace is 'default' (or not in available list), and user has a dedicated non-default workspace (e.g. ws_user_a),
        // automatically switch to their primary workspace.
        const nonDefaultPrimary = data.find((ws: any) => !ws.is_default && (ws.role === 'Admin' || ws.role === 'Editor'));
        let nextActive = authState.activeWorkspace;
        if (!data.some((ws: any) => ws.id === nextActive) || (nextActive === 'default' && nonDefaultPrimary && authState.user?.global_role !== 'admin')) {
          nextActive = nonDefaultPrimary ? nonDefaultPrimary.id : data[0].id;
        }

        authState = {
          ...authState,
          workspaces: data,
          activeWorkspace: nextActive,
        };
        setStoredItem(WORKSPACE_STORAGE_KEY, nextActive);
        notify();
        return data;
      }
    }
  } catch (err) {
    console.debug('Failed to fetch workspaces:', err);
  }
  return authState.workspaces;
}

export async function refreshProfile(): Promise<AuthUser | null> {
  if (!authState.token) {
    return null;
  }
  try {
    const res = await fetch('/api/auth/me');
    if (res.ok) {
      const data = await res.json();
      const profile: AuthUser = {
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

      authState = {
        ...authState,
        user: profile,
      };
      notify();
      await fetchUserWorkspaces();
      return profile;
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

    const profile: AuthUser | null = data.user
      ? {
          id: data.user.id,
          username: data.user.username,
          display_name: data.user.display_name,
          email: data.user.email,
          global_role: data.user.global_role,
          groups: data.user.groups || [],
          authorized_workspaces: data.user.authorized_workspaces || ['default'],
          workspace_roles: data.user.workspace_roles || {},
          type: data.user.type,
        }
      : null;

    setStoredItem(TOKEN_STORAGE_KEY, data.access_token);
    authState = {
      ...authState,
      token: data.access_token,
      user: profile,
    };
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
  setStoredItem(TOKEN_STORAGE_KEY, null);
  setStoredItem(WORKSPACE_STORAGE_KEY, 'default');
  authState = {
    token: null,
    user: null,
    activeWorkspace: 'default',
    workspaces: [
      { id: 'default', name: '默认工作区 (Default)', is_default: true, role: 'Admin' },
    ],
  };
  // Immediately wipe tenant graph nodes/edges from memory so logged-out
  // users never see another tenant's data on the canvas.
  try { clearGraph(); } catch { /* store may not be ready on first render */ }
  notify();
}

// ---------------------------------------------------------------------------
// React Hook
// ---------------------------------------------------------------------------

export function useAuth() {
  const state = useSyncExternalStore(subscribe, getSnapshot);

  // Initialize profile on mount if token exists
  useEffect(() => {
    if (state.token && !state.user) {
      refreshProfile();
    }
  }, [state.token, state.user]);

  return {
    token: state.token,
    user: state.user,
    isAuthenticated: Boolean(state.token && state.user),
    isAdmin: state.user?.global_role === 'admin',
    activeWorkspace: state.activeWorkspace,
    workspaces: state.workspaces,
    setActiveWorkspace,
    login,
    logout,
    refreshProfile,
    fetchUserWorkspaces,
  };
}
