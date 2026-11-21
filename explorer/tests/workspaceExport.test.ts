import assert from 'node:assert/strict';
import test from 'node:test';

// Setup minimal globals
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (key: string) => store.get(key) || null,
    setItem: (key: string, val: string) => store.set(key, String(val)),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
  };
}

let lastFetchRequest: { url: string; headers: Headers; body?: any } | null = null;

const mockFetch = async (input: any, init?: any) => {
  const url = typeof input === 'string' ? input : input.toString();
  const headers = new Headers(init?.headers || {});
  lastFetchRequest = { url, headers, body: init?.body };

  if (url.includes('/api/export')) {
    return {
      status: 200,
      ok: true,
      blob: async () => new Blob(['{"entities":[],"relationships":[]}'], { type: 'application/json' }),
      json: async () => ({ status: 'success' }),
    } as any;
  }
  return { status: 404, ok: false } as any;
};

(globalThis as any).fetch = mockFetch as any;
(globalThis as any).window = {
  fetch: mockFetch,
  location: { pathname: '/', hash: '', search: '' },
};

import { setActiveWorkspace, installFetchInterceptor, getActiveWorkspace } from '../src/auth/authStore';

test('workspaceExport: fetch interceptor attaches active X-Workspace-ID header to /api/export', async () => {
  installFetchInterceptor();
  setActiveWorkspace('ws_user_a');
  assert.equal(getActiveWorkspace(), 'ws_user_a');

  await globalThis.fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'json' }),
  });

  assert(lastFetchRequest !== null);
  assert.equal(lastFetchRequest.url, '/api/export');
  assert.equal(lastFetchRequest.headers.get('X-Workspace-ID'), 'ws_user_a');

  const parsedBody = JSON.parse(lastFetchRequest.body);
  assert.equal(parsedBody.format, 'json');
});

test('workspaceExport: handles multi-format exports including csv, graphml, and turtle', async () => {
  installFetchInterceptor();
  setActiveWorkspace('ws_user_b');

  for (const fmt of ['json', 'csv', 'graphml', 'turtle']) {
    await globalThis.fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: fmt }),
    });

    assert(lastFetchRequest !== null);
    assert.equal(lastFetchRequest.headers.get('X-Workspace-ID'), 'ws_user_b');
    const parsedBody = JSON.parse(lastFetchRequest.body);
    assert.equal(parsedBody.format, fmt);
  }
});
