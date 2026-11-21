import assert from 'node:assert/strict';
import test from 'node:test';

// Setup minimal browser globals for testing
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (key: string) => store.get(key) || null,
    setItem: (key: string, val: string) => store.set(key, String(val)),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
  };
}

let mockFetchHandler: (input: any, init?: any) => Promise<any> = async () => ({
  status: 200,
  ok: true,
  json: async () => ({ status: 'ok' }),
});

const mockFetch = async (input: any, init?: any) => mockFetchHandler(input, init);

(globalThis as any).window = {
  location: { pathname: '/', hash: '', search: '' },
  history: { pushState: () => {}, replaceState: () => {} },
  fetch: mockFetch,
};
globalThis.fetch = mockFetch as any;

import {
  getActiveWorkspace,
  setActiveWorkspace,
  getAuthToken,
  setAuthToken,
  installFetchInterceptor,
  login,
  logout,
  getCurrentUser,
  getWorkspaces,
} from '../src/auth/authStore';

test('authStore: switches active workspace and persists to localStorage', () => {
  setActiveWorkspace('ws_finance');
  assert.equal(getActiveWorkspace(), 'ws_finance');
  assert.equal(globalThis.localStorage.getItem('semantica_active_workspace'), 'ws_finance');

  setActiveWorkspace('default');
  assert.equal(getActiveWorkspace(), 'default');
});

test('authStore: manages token lifecycle in memory and localStorage', () => {
  setAuthToken('test_jwt_bearer_token_123');
  assert.equal(getAuthToken(), 'test_jwt_bearer_token_123');
  assert.equal(globalThis.localStorage.getItem('semantica_auth_token'), 'test_jwt_bearer_token_123');

  setAuthToken(null);
  assert.equal(getAuthToken(), null);
  assert.equal(globalThis.localStorage.getItem('semantica_auth_token'), null);
});

test('authStore: fetch interceptor automatically attaches X-Workspace-ID and Authorization headers', async () => {
  let capturedHeaders: Headers | null = null;
  mockFetchHandler = async (_input: any, init?: any) => {
    capturedHeaders = init?.headers;
    return {
      status: 200,
      ok: true,
      json: async () => ({}),
    } as any;
  };

  installFetchInterceptor();

  setActiveWorkspace('ws_engineering');
  setAuthToken('jwt_secret_token_abc');

  await globalThis.fetch('/api/graph/stats');

  assert(capturedHeaders !== null);
  assert.equal(capturedHeaders.get('X-Workspace-ID'), 'ws_engineering');
  assert.equal(capturedHeaders.get('Authorization'), 'Bearer jwt_secret_token_abc');
});

test('authStore: login flow sets user profile, token, and handles logout', async () => {
  mockFetchHandler = async (input: any) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/auth/login')) {
      return {
        status: 200,
        ok: true,
        json: async () => ({
          access_token: 'signed_jwt_token_xyz',
          token_type: 'bearer',
          user: {
            id: 'usr_alice123',
            username: 'alice',
            display_name: 'Alice Smith',
            global_role: 'admin',
            groups: ['CN=Engineering-Team'],
            authorized_workspaces: ['default', 'ws_engineering'],
            workspace_roles: { default: 'Admin', ws_engineering: 'Admin' },
            type: 'ad',
          },
        }),
      } as any;
    }
    if (url.includes('/api/auth/workspaces')) {
      return {
        status: 200,
        ok: true,
        json: async () => [
          { id: 'default', name: '默认工作区', role: 'Admin' },
          { id: 'ws_engineering', name: '工程研发空间', role: 'Admin' },
        ],
      } as any;
    }
    return { status: 200, ok: true, json: async () => ({}) } as any;
  };

  const loginRes = await login('alice', 'Password123!', 'ad');
  assert.equal(loginRes.success, true);
  assert.equal(getAuthToken(), 'signed_jwt_token_xyz');

  const user = getCurrentUser();
  assert(user !== null);
  assert.equal(user.username, 'alice');
  assert.equal(user.global_role, 'admin');
  assert.equal(user.authorized_workspaces.length, 2);

  const workspaces = getWorkspaces();
  assert(workspaces.length >= 2);
  assert(workspaces.some((w) => w.id === 'ws_engineering'));

  // Test logout
  logout();
  assert.equal(getAuthToken(), null);
  assert.equal(getCurrentUser(), null);
  assert.equal(getActiveWorkspace(), 'default');
});

test('authStore: handles failed login with error detail', async () => {
  mockFetchHandler = async () => {
    return {
      status: 401,
      ok: false,
      json: async () => ({ detail: 'User account has expired.' }),
    } as any;
  };

  const loginRes = await login('expired_user', 'WrongPass');
  assert.equal(loginRes.success, false);
  assert.equal(loginRes.error, 'User account has expired.');
});
