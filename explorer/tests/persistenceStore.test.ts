import assert from 'node:assert/strict';
import test from 'node:test';

let mockFetchHandler: (input: any, init?: any) => Promise<any> = async () => ({
  status: 200,
  ok: true,
  json: async () => ({
    status: 'active',
    persistence: {
      enabled: true,
      backend: 'sqlite+falkordb',
      sqlite_path: '/data/semantica_graphs.db',
      falkordb_enabled: true,
      falkordb_host: '127.0.0.1',
      falkordb_port: 6379,
      persisted_workspaces: ['default', 'ws_user_a', 'ws_user_b'],
    },
  }),
});

const mockFetch = async (input: any, init?: any) => mockFetchHandler(input, init);
(globalThis as any).fetch = mockFetch as any;
(globalThis as any).window = { fetch: mockFetch };

import {
  getPersistenceState,
  refreshPersistenceStatus,
  setPersistenceState,
} from '../src/auth/persistenceStore';

test('persistenceStore: initially reflects memory/disabled default state', () => {
  const state = getPersistenceState();
  assert(typeof state.enabled === 'boolean');
  assert(Array.isArray(state.persisted_workspaces));
});

test('persistenceStore: refreshPersistenceStatus parses sqlite+falkordb response', async () => {
  mockFetchHandler = async (input: any) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/info')) {
      return {
        status: 200,
        ok: true,
        json: async () => ({
          status: 'active',
          persistence: {
            enabled: true,
            backend: 'sqlite+falkordb',
            sqlite_path: '/data/semantica_graphs.db',
            falkordb_enabled: true,
            falkordb_host: '10.0.0.5',
            falkordb_port: 6379,
            persisted_workspaces: ['default', 'ws_user_a', 'ws_user_b'],
          },
        }),
      } as any;
    }
    return { status: 404, ok: false } as any;
  };

  const state = await refreshPersistenceStatus();
  assert.equal(state.enabled, true);
  assert.equal(state.backend, 'sqlite+falkordb');
  assert.equal(state.sqlite_path, '/data/semantica_graphs.db');
  assert.equal(state.falkordb_enabled, true);
  assert.equal(state.falkordb_host, '10.0.0.5');
  assert.equal(state.falkordb_port, 6379);
  assert.deepEqual(state.persisted_workspaces, ['default', 'ws_user_a', 'ws_user_b']);
  assert.equal(state.error, null);
});

test('persistenceStore: handles pure sqlite WAL backend gracefully', async () => {
  mockFetchHandler = async () => ({
    status: 200,
    ok: true,
    json: async () => ({
      status: 'active',
      persistence: {
        enabled: true,
        backend: 'sqlite',
        sqlite_path: '/var/lib/semantica/semantica_graphs.db',
        falkordb_enabled: false,
        falkordb_host: null,
        falkordb_port: null,
        persisted_workspaces: ['default', 'ws_marketing'],
      },
    }),
  } as any);

  const state = await refreshPersistenceStatus();
  assert.equal(state.enabled, true);
  assert.equal(state.backend, 'sqlite');
  assert.equal(state.falkordb_enabled, false);
  assert.equal(state.sqlite_path, '/var/lib/semantica/semantica_graphs.db');
  assert.deepEqual(state.persisted_workspaces, ['default', 'ws_marketing']);
});

test('persistenceStore: handles memory fallback gracefully on network or server error', async () => {
  mockFetchHandler = async () => ({
    status: 500,
    ok: false,
    json: async () => ({ detail: 'Internal Server Error' }),
  } as any);

  const state = await refreshPersistenceStatus();
  assert(state.error !== null);
  assert.equal(state.isLoading, false);
});
