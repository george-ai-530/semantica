/**
 * Federated Knowledge Search & GraphRAG Cross-Workspace Retrieval Tab.
 *
 * Dispatches concurrent searches across multiple isolated workspace graphs,
 * aggregates and ranks results, and tags every item with origin provenance.
 */

import { useState } from 'react';
import {
  Search,
  Layers,
  Sparkles,
  CheckSquare,
  Square,
  AlertCircle,
  Database,
  Loader2,
} from 'lucide-react';
import { useAuth } from '../../auth/authStore';

interface FederatedResultItem {
  id: string;
  label?: string;
  content?: string;
  origin_workspace: string;
  score?: number;
  properties?: Record<string, any>;
  node_type?: string;
}

export function FederatedSearchTab() {
  const { activeWorkspace, workspaces } = useAuth();
  const [query, setQuery] = useState('');
  const [selectedWorkspaces, setSelectedWorkspaces] = useState<string[]>(() => {
    return workspaces.map((w) => w.id);
  });
  const limit = 10;
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<FederatedResultItem[]>([]);
  const [queriedWorkspaces, setQueriedWorkspaces] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  // Sync selected workspaces if list changed and nothing selected
  if (selectedWorkspaces.length === 0 && workspaces.length > 0) {
    setSelectedWorkspaces(workspaces.map((w) => w.id));
  }

  function toggleWorkspace(wsId: string) {
    if (selectedWorkspaces.includes(wsId)) {
      if (selectedWorkspaces.length > 1) {
        setSelectedWorkspaces(selectedWorkspaces.filter((id) => id !== wsId));
      }
    } else {
      setSelectedWorkspaces([...selectedWorkspaces, wsId]);
    }
  }

  async function handleSearch(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    setErrorMessage(null);
    setHasSearched(true);

    try {
      const res = await fetch('/api/graph/federated/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          federated_workspaces: selectedWorkspaces,
          limit,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setErrorMessage(data.detail || '联邦检索请求失败，请检查工作区读取权限。');
        setResults([]);
        return;
      }

      setResults(data.results || []);
      setQueriedWorkspaces(data.queried_workspaces || selectedWorkspaces);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : '网络请求失败');
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }

  const sampleQueries = [
    'COWIN 核心架构规范',
    'OpenLDAP 389 身份认证策略',
    '多工作区 ACL 隔离原则',
    '知识图谱 PROV-O 谱系溯源',
  ];

  return (
    <div
      style={{
        padding: '24px 32px',
        maxWidth: 1200,
        margin: '0 auto',
        height: '100%',
        overflowY: 'auto',
        boxSizing: 'border-box',
      }}
    >
      {/* Header Banner */}
      <div
        style={{
          background: 'linear-gradient(135deg, #0052d9 0%, #266cfb 100%)',
          borderRadius: 14,
          padding: '22px 28px',
          color: '#ffffff',
          marginBottom: 24,
          boxShadow: '0 8px 24px rgba(0, 82, 217, 0.16)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 16,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Sparkles size={20} />
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800 }}>
              知识联邦检索 (Federated GraphRAG)
            </h2>
          </div>
          <p style={{ margin: 0, fontSize: 13, opacity: 0.9, maxWidth: 650, lineHeight: 1.5 }}>
            跨多个隔离租户空间（默认空间、研发工程、商业智能等）并发召回关联知识切片与图谱实体，
            严格遵循 RBAC 访问控制边界，并自动附加来源空间元数据（Origin Workspace Provenance）。
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span
            style={{
              background: 'rgba(255,255,255,0.18)',
              padding: '6px 12px',
              borderRadius: 8,
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            当前主空间: <code>{activeWorkspace}</code>
          </span>
        </div>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSearch} style={{ marginBottom: 20 }}>
        <div
          style={{
            display: 'flex',
            gap: 10,
            background: '#ffffff',
            padding: 8,
            borderRadius: 12,
            border: '1px solid var(--ws-border)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', flex: 1, paddingLeft: 12 }}>
            <Search size={18} style={{ color: 'var(--ws-text-muted)', marginRight: 10 }} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入关键词、自然语言问题或架构概念发起跨工作区联合检索…"
              style={{
                width: '100%',
                border: 'none',
                outline: 'none',
                fontSize: 14,
                color: 'var(--ws-text)',
                background: 'transparent',
              }}
            />
          </div>
          <button
            type="submit"
            className="ws-btn ws-btn--primary"
            style={{ padding: '9px 24px', fontSize: 14, fontWeight: 700 }}
            disabled={isLoading || !query.trim()}
          >
            {isLoading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>检索中…</span>
              </>
            ) : (
              <>
                <Search size={15} />
                <span>联合检索</span>
              </>
            )}
          </button>
        </div>
      </form>

      {/* Target Workspaces Selector */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          padding: '14px 18px',
          border: '1px solid var(--ws-border)',
          marginBottom: 24,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={16} style={{ color: 'var(--ws-accent)' }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ws-text)' }}>
            联合检索目标空间：
          </span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {workspaces.map((ws) => {
              const checked = selectedWorkspaces.includes(ws.id);
              return (
                <button
                  key={ws.id}
                  type="button"
                  onClick={() => toggleWorkspace(ws.id)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '4px 10px',
                    borderRadius: 6,
                    border: checked ? '1px solid var(--ws-accent)' : '1px solid var(--ws-border)',
                    background: checked ? 'var(--ws-accent-soft)' : '#f9f9f9',
                    color: checked ? 'var(--ws-accent)' : 'var(--ws-text-muted)',
                    fontSize: 12,
                    fontWeight: checked ? 700 : 500,
                    cursor: 'pointer',
                    transition: 'all 120ms ease',
                  }}
                >
                  {checked ? <CheckSquare size={13} /> : <Square size={13} />}
                  <span>{ws.name}</span>
                  <code style={{ fontSize: 10, opacity: 0.7 }}>({ws.id})</code>
                </button>
              );
            })}
          </div>
        </div>

        {/* Quick Sample Queries */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--ws-text-muted)' }}>示例:</span>
          {sampleQueries.map((sq) => (
            <button
              key={sq}
              type="button"
              onClick={() => {
                setQuery(sq);
              }}
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 4,
                border: '1px solid var(--ws-border)',
                background: '#fafafa',
                color: 'var(--ws-text)',
                cursor: 'pointer',
              }}
            >
              {sq}
            </button>
          ))}
        </div>
      </div>

      {/* Error Feedback */}
      {errorMessage && (
        <div
          style={{
            padding: '14px 18px',
            borderRadius: 10,
            background: 'var(--ws-red-soft)',
            border: '1px solid rgba(213, 73, 65, 0.28)',
            color: '#d54941',
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 13,
          }}
        >
          <AlertCircle size={18} style={{ flexShrink: 0 }} />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Results Section */}
      {hasSearched && (
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--ws-text)' }}>
              联邦检索结果 ({results.length})
            </h3>
            <span style={{ fontSize: 12, color: 'var(--ws-text-muted)' }}>
              覆盖空间: {queriedWorkspaces.map((w) => `@${w}`).join(', ')}
            </span>
          </div>

          {results.length === 0 && !isLoading ? (
            <div
              style={{
                background: '#ffffff',
                borderRadius: 12,
                padding: '48px 24px',
                textAlign: 'center',
                border: '1px solid var(--ws-border)',
              }}
            >
              <Database size={40} style={{ color: 'var(--ws-text-dim)', marginBottom: 12 }} />
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ws-text)', marginBottom: 4 }}>
                未召回匹配的跨空间知识切片
              </div>
              <div style={{ fontSize: 12, color: 'var(--ws-text-muted)' }}>
                请尝试更换关键词，或者确认勾选了包含对应知识的目标工作区。
              </div>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 12 }}>
              {results.map((item, idx) => (
                <div
                  key={`${item.origin_workspace}_${item.id}_${idx}`}
                  style={{
                    background: '#ffffff',
                    borderRadius: 10,
                    padding: '16px 20px',
                    border: '1px solid var(--ws-border)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                    transition: 'all 120ms ease',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginBottom: 8,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        className={`ws-pill ${
                          item.origin_workspace === 'ws_rd'
                            ? 'ws-pill--purple'
                            : item.origin_workspace === 'ws_biz'
                            ? 'ws-pill--green'
                            : 'ws-pill--mono'
                        }`}
                        style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px' }}
                      >
                        空间: {item.origin_workspace}
                      </span>
                      <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--ws-text)' }}>
                        {item.label || item.id}
                      </span>
                    </div>

                    {typeof item.score === 'number' && (
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          color: 'var(--ws-accent)',
                          background: 'var(--ws-accent-soft)',
                          padding: '2px 8px',
                          borderRadius: 6,
                        }}
                      >
                        相关度: {(item.score * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>

                  {item.content && (
                    <p
                      style={{
                        margin: '0 0 10px',
                        fontSize: 13,
                        color: 'var(--ws-text-muted)',
                        lineHeight: 1.6,
                      }}
                    >
                      {item.content}
                    </p>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 11, color: 'var(--ws-text-dim)' }}>
                    <span>实体 ID: <code>{item.id}</code></span>
                    {item.node_type && <span>类型: <code>{item.node_type}</code></span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
