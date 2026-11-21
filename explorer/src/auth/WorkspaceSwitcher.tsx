/**
 * Workspace Switcher Component.
 *
 * Placed in the top navigation bar to display and toggle the active workspace context.
 * Attaches X-Workspace-ID header to all outgoing API calls via the global interceptor.
 */

import { useState, useRef, useEffect } from 'react';
import { Layers, ChevronDown, Check, Shield } from 'lucide-react';
import { useAuth } from './authStore';

export function WorkspaceSwitcher() {
  const { activeWorkspace, workspaces, setActiveWorkspace, user } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
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

  const currentWs = workspaces.find((w) => w.id === activeWorkspace) || {
    id: activeWorkspace,
    name: activeWorkspace === 'default' ? '默认工作区' : activeWorkspace,
    role: user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer'),
  };

  const role = currentWs.role || user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer');

  return (
    <div className="ws-switcher-container" ref={containerRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="ws-switcher-btn"
        onClick={() => setIsOpen(!isOpen)}
        title="切换当前工作区 (Switch Active Workspace)"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          background: '#ffffff',
          border: '1px solid var(--ws-border)',
          borderRadius: 8,
          padding: '6px 12px',
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--ws-text)',
          cursor: 'pointer',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          transition: 'all 160ms ease',
        }}
      >
        <Layers size={15} style={{ color: 'var(--ws-accent)' }} />
        <span style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {currentWs.name}
        </span>
        <span
          className={`ws-pill ${
            role === 'Admin'
              ? 'ws-pill--purple'
              : role === 'Editor'
              ? 'ws-pill--green'
              : 'ws-pill--mono'
          }`}
          style={{ fontSize: 10, padding: '1px 6px' }}
        >
          {role}
        </span>
        <ChevronDown size={14} style={{ opacity: 0.6, transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 160ms ease' }} />
      </button>

      {isOpen && (
        <div
          className="ws-switcher-dropdown"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            minWidth: 260,
            background: '#ffffff',
            border: '1px solid var(--ws-border)',
            borderRadius: 10,
            boxShadow: '0 10px 30px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.06)',
            padding: 6,
            zIndex: 1000,
            animation: 'fadeIn 120ms ease',
          }}
        >
          <div
            style={{
              padding: '6px 10px',
              fontSize: 11,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'var(--ws-text-muted)',
              borderBottom: '1px solid var(--ws-border)',
              marginBottom: 4,
            }}
          >
            已授权工作区 ({workspaces.length})
          </div>

          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {workspaces.map((ws) => {
              const isSelected = ws.id === activeWorkspace;
              const wsRole = ws.role || user?.workspace_roles?.[ws.id] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer');
              return (
                <button
                  key={ws.id}
                  type="button"
                  onClick={() => {
                    setActiveWorkspace(ws.id);
                    setIsOpen(false);
                  }}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: isSelected ? 'var(--ws-accent-soft)' : 'transparent',
                    border: 'none',
                    color: isSelected ? 'var(--ws-accent)' : 'var(--ws-text)',
                    fontSize: 13,
                    fontWeight: isSelected ? 700 : 500,
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'background 120ms ease',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.background = 'rgba(0,0,0,0.04)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    {isSelected ? (
                      <Check size={14} style={{ color: 'var(--ws-accent)', flexShrink: 0 }} />
                    ) : (
                      <div style={{ width: 14 }} />
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                        {ws.name}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--ws-text-muted)', fontFamily: 'monospace' }}>
                        {ws.id}
                      </div>
                    </div>
                  </div>
                  <span
                    className={`ws-pill ${
                      wsRole === 'Admin'
                        ? 'ws-pill--purple'
                        : wsRole === 'Editor'
                        ? 'ws-pill--green'
                        : 'ws-pill--mono'
                    }`}
                    style={{ fontSize: 10, padding: '1px 6px', flexShrink: 0 }}
                  >
                    {wsRole}
                  </span>
                </button>
              );
            })}
          </div>

          {user?.global_role === 'admin' && (
            <div
              style={{
                borderTop: '1px solid var(--ws-border)',
                marginTop: 4,
                paddingTop: 4,
              }}
            >
              <div
                style={{
                  padding: '6px 10px',
                  fontSize: 11,
                  color: 'var(--ws-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Shield size={12} style={{ color: 'var(--ws-accent)' }} />
                <span>管理员可全局访问所有物理工作区</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
