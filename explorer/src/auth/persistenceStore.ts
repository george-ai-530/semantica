/**
 * Graph Persistence Status Store.
 *
 * Fetches and tracks the server's graph persistence configuration and live status:
 *   - Backend mode: SQLite WAL, FalkorDB RESP2 mirror, or In-Memory
 *   - SQLite database path (e.g. /data/semantica_graphs.db)
 *   - FalkorDB mirror host / port
 *   - Persisted workspaces list
 */

import { useEffect, useSyncExternalStore } from 'react';

export interface PersistenceDiagnostics {
  enabled: boolean;
  backend: 'sqlite+falkordb' | 'sqlite' | 'falkordb' | 'memory';
  sqlite_path: string | null;
  falkordb_enabled: boolean;
  falkordb_host: string | null;
  falkordb_port: number | null;
  persisted_workspaces: string[];
  lastCheckedAt?: string;
  isLoading?: boolean;
  error?: string | null;
}

let persistenceState: PersistenceDiagnostics = {
  enabled: false,
  backend: 'memory',
  sqlite_path: null,
  falkordb_enabled: false,
  falkordb_host: null,
  falkordb_port: null,
  persisted_workspaces: [],
  lastCheckedAt: undefined,
  isLoading: false,
  error: null,
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

function getSnapshot(): PersistenceDiagnostics {
  return persistenceState;
}

export function getPersistenceState(): PersistenceDiagnostics {
  return persistenceState;
}

export function setPersistenceState(update: Partial<PersistenceDiagnostics>) {
  persistenceState = {
    ...persistenceState,
    ...update,
  };
  notify();
}

/**
 * Fetch persistence diagnostics from /api/info.
 */
export async function refreshPersistenceStatus(): Promise<PersistenceDiagnostics> {
  setPersistenceState({ isLoading: true, error: null });
  try {
    const res = await fetch('/api/info');
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const p = data.persistence || {};
    const newState: PersistenceDiagnostics = {
      enabled: Boolean(p.enabled),
      backend: (p.backend as any) || (p.enabled ? 'sqlite' : 'memory'),
      sqlite_path: p.sqlite_path || null,
      falkordb_enabled: Boolean(p.falkordb_enabled),
      falkordb_host: p.falkordb_host || null,
      falkordb_port: p.falkordb_port || null,
      persisted_workspaces: Array.isArray(p.persisted_workspaces) ? p.persisted_workspaces : [],
      lastCheckedAt: new Date().toLocaleTimeString(),
      isLoading: false,
      error: null,
    };
    persistenceState = newState;
    notify();
    return newState;
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : '探测持久化状态失败';
    const fallbackState: PersistenceDiagnostics = {
      ...persistenceState,
      isLoading: false,
      error: errorMsg,
      lastCheckedAt: new Date().toLocaleTimeString(),
    };
    persistenceState = fallbackState;
    notify();
    return fallbackState;
  }
}

/**
 * React hook to observe persistence state.
 */
export function usePersistence(pollIntervalMs = 30000) {
  const state = useSyncExternalStore(subscribe, getSnapshot);

  useEffect(() => {
    // Initial fetch on mount
    refreshPersistenceStatus();

    if (pollIntervalMs > 0) {
      const timer = setInterval(() => {
        refreshPersistenceStatus();
      }, pollIntervalMs);
      return () => clearInterval(timer);
    }
  }, [pollIntervalMs]);

  return {
    ...state,
    refresh: refreshPersistenceStatus,
  };
}
