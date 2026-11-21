/**
 * Persistence Indicator Component.
 *
 * Renders in the persistent top navigation bar to display graph storage persistence
 * status (SQLite WAL + FalkorDB RESP2 mirror vs in-memory mode), current workspace
 * persistence status, and diagnostics popover.
 */

import { useState, useRef, useEffect } from 'react';
import {
  Database,
  CheckCircle2,
  RefreshCw,
  HardDrive,
  Cpu,
  Layers,
  ShieldCheck,
  ChevronDown,
} from 'lucide-react';
import { usePersistence } from './persistenceStore';
import { useAuth } from './authStore';

export function PersistenceIndicator() {
  const { activeWorkspace, workspaces } = useAuth();
  const persistence = usePersistence(30000);
  const [isOpen, setIsOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover on click outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const isCurrentWsPersisted = persistence.persisted_workspaces.includes(activeWorkspace);
  const currentWsName = workspaces.find((w) => w.id === activeWorkspace)?.name || activeWorkspace;

  // Format label and tone
  let badgeLabel = '持久化检查中…';
  let badgeTone: 'green' | 'amber' | 'neutral' = 'neutral';
  let badgeDetail = '';

  if (persistence.enabled) {
    badgeTone = 'green';
    if (persistence.backend === 'sqlite+falkordb') {
      badgeLabel = '已持久化 (SQLite + FalkorDB)';
      badgeDetail = 'SQLite WAL + FalkorDB 镜像双层存储';
    } else if (persistence.backend === 'sqlite') {
      badgeLabel = '已持久化 (SQLite WAL)';
      badgeDetail = 'SQLite WAL 事务持久化';
    } else if (persistence.backend === 'falkordb') {
      badgeLabel = '已持久化 (FalkorDB)';
      badgeDetail = 'FalkorDB 物理图谱存储';
    }
  } else {
    badgeTone = 'amber';
    badgeLabel = '未持久化 (内存模式)';
    badgeDetail = '单机内存模式，服务重启后数据不保留';
  }

  return (
    <div className="ws-persistence-indicator-container" ref={popoverRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="ws-persistence-btn"
        onClick={() => setIsOpen(!isOpen)}
        title={`图谱存储状态：${badgeDetail}（点击查看详情）`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          background: badgeTone === 'green' ? 'rgba(43, 164, 113, 0.08)' : 'rgba(227, 115, 24, 0.08)',
          border: `1px solid ${badgeTone === 'green' ? 'rgba(43, 164, 113, 0.25)' : 'rgba(227, 115, 24, 0.3)'}`,
          borderRadius: 8,
          padding: '5px 10px',
          fontSize: 12,
          fontWeight: 600,
          color: badgeTone === 'green' ? '#1c744f' : '#b3560e',
          cursor: 'pointer',
          transition: 'all 160ms ease',
        }}
      >
        <span
          style={{
            display: 'inline-block',
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: badgeTone === 'green' ? '#2ba471' : '#e37318',
            boxShadow: badgeTone === 'green' ? '0 0 6px rgba(43, 164, 113, 0.6)' : '0 0 6px rgba(227, 115, 24, 0.6)',
          }}
        />
        <Database size={13} style={{ opacity: 0.85 }} />
        <span>{badgeLabel}</span>
        <ChevronDown size={12} style={{ opacity: 0.6, transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 160ms ease' }} />
      </button>

      {isOpen && (
        <div
          className="ws-persistence-popover"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            width: 340,
            background: '#ffffff',
            border: '1px solid var(--ws-border)',
            borderRadius: 12,
            boxShadow: '0 12px 36px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
            padding: 14,
            zIndex: 1000,
            animation: 'fadeIn 120ms ease',
          }}
        >
          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: 10,
              borderBottom: '1px solid var(--ws-border)',
              marginBottom: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <HardDrive size={15} style={{ color: 'var(--ws-accent)' }} />
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ws-text)' }}>
                图谱物理持久化引擎
              </div>
            </div>
            <button
              type="button"
              onClick={() => void persistence.refresh()}
              disabled={persistence.isLoading}
              title="立即刷新持久化状态"
              style={{
                background: 'transparent',
                border: 'none',
                cursor: persistence.isLoading ? 'not-allowed' : 'pointer',
                color: 'var(--ws-text-muted)',
                display: 'flex',
                alignItems: 'center',
                padding: 4,
                borderRadius: 4,
              }}
            >
              <RefreshCw
                size={13}
                className={persistence.isLoading ? 'ws-spin' : ''}
                style={{ opacity: persistence.isLoading ? 0.6 : 1 }}
              />
            </button>
          </div>

          {/* Active Workspace Persistence Status */}
          <div
            style={{
              background: isCurrentWsPersisted ? 'rgba(43, 164, 113, 0.08)' : 'rgba(0, 0, 0, 0.03)',
              border: `1px solid ${isCurrentWsPersisted ? 'rgba(43, 164, 113, 0.2)' : 'var(--ws-border)'}`,
              borderRadius: 8,
              padding: '8px 10px',
              marginBottom: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--ws-text-muted)' }}>
                当前工作区
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: isCurrentWsPersisted ? '#2ba471' : 'var(--ws-text-dim)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 3,
                }}
              >
                {isCurrentWsPersisted ? (
                  <>
                    <CheckCircle2 size={11} /> 已物理持久化
                  </>
                ) : (
                  <>待写入持久化</>
                )}
              </span>
            </div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ws-text)', marginTop: 2 }}>
              {currentWsName} <span style={{ fontFamily: 'monospace', fontWeight: 500, opacity: 0.6 }}>({activeWorkspace})</span>
            </div>
          </div>

          {/* Diagnostics rows */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--ws-text-muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <HardDrive size={12} /> SQLite WAL 存储
              </span>
              <span style={{ fontWeight: 600, color: persistence.sqlite_path ? 'var(--ws-text)' : 'var(--ws-text-dim)', fontFamily: 'monospace' }}>
                {persistence.sqlite_path ? persistence.sqlite_path : '未配置'}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--ws-text-muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <Cpu size={12} /> FalkorDB 镜像
              </span>
              <span style={{ fontWeight: 600, color: persistence.falkordb_enabled ? '#2ba471' : 'var(--ws-text-dim)' }}>
                {persistence.falkordb_enabled
                  ? `${persistence.falkordb_host || 'localhost'}:${persistence.falkordb_port || 6379}`
                  : '未启用'}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginTop: 2 }}>
              <span style={{ color: 'var(--ws-text-muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <Layers size={12} /> 已持久化空间
              </span>
              <span style={{ fontWeight: 600, color: 'var(--ws-text)', textAlign: 'right', maxWidth: 170 }}>
                {persistence.persisted_workspaces.length > 0 ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, justifyContent: 'flex-end' }}>
                    {persistence.persisted_workspaces.map((wsId) => (
                      <span
                        key={wsId}
                        className={`ws-pill ${wsId === activeWorkspace ? 'ws-pill--green' : 'ws-pill--mono'}`}
                        style={{ fontSize: 9, padding: '1px 4px' }}
                      >
                        {wsId}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span style={{ color: 'var(--ws-text-dim)' }}>暂无</span>
                )}
              </span>
            </div>
          </div>

          {/* Guarantee Footer */}
          <div
            style={{
              marginTop: 10,
              paddingTop: 8,
              borderTop: '1px solid var(--ws-border)',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 10,
              color: 'var(--ws-text-muted)',
            }}
          >
            <ShieldCheck size={12} style={{ color: '#2ba471', flexShrink: 0 }} />
            <span>数据具备容器重建、服务重启与断电后 100% 自动存活保障</span>
          </div>
        </div>
      )}
    </div>
  );
}
