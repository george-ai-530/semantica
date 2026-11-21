/**
 * User Settings & Personal API Keys Drawer/Modal.
 *
 * Provides self-service personal API key creation with one-time copy display,
 * active key listing, key revocation, and user identity profile inspection.
 */

import { useState, useEffect } from 'react';
import {
  X,
  Key,
  User,
  Copy,
  Check,
  AlertTriangle,
  Plus,
  Trash2,
  Clock,
  Globe,
  LogOut,
} from 'lucide-react';
import { useAuth } from './authStore';

interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  is_service: boolean;
  allowed_workspaces: string[];
  scopes: string[];
  is_active: boolean;
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
  last_used_ip?: string;
}

export function UserSettingsModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const { user, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<'profile' | 'keys'>('keys');

  // Keys state
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [isLoadingKeys, setIsLoadingKeys] = useState(false);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [keyExpiry, setKeyExpiry] = useState('');
  const [createdRawKey, setCreatedRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadKeys();
    }
  }, [isOpen]);

  async function loadKeys() {
    setIsLoadingKeys(true);
    try {
      const res = await fetch('/api/auth/keys');
      if (res.ok) {
        const data = await res.json();
        setKeys(data);
      }
    } catch (err) {
      console.error('Failed to load personal API keys:', err);
    } finally {
      setIsLoadingKeys(false);
    }
  }

  async function handleCreateKey(e: React.FormEvent) {
    e.preventDefault();
    if (!keyName.trim()) {
      setErrorMessage('请输入密钥名称');
      return;
    }

    try {
      const res = await fetch('/api/auth/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: keyName.trim(),
          expires_at: keyExpiry || undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setErrorMessage(data.detail || '生成密钥失败');
        return;
      }

      setCreatedRawKey(data.raw_key);
      setKeyName('');
      setKeyExpiry('');
      setIsCreatingKey(false);
      setErrorMessage(null);
      await loadKeys();
    } catch (err) {
      setErrorMessage('创建请求出错，请稍后重试。');
    }
  }

  async function handleRevokeKey(keyId: string) {
    if (!window.confirm('确认立即吊销此 API 密钥？吊销后任何使用该密钥的客户端将立即失效。')) {
      return;
    }

    try {
      const res = await fetch(`/api/auth/keys/${keyId}`, { method: 'DELETE' });
      if (res.ok) {
        await loadKeys();
      }
    } catch (err) {
      console.error('Failed to revoke API key:', err);
    }
  }

  function handleCopyKey() {
    if (!createdRawKey) return;
    navigator.clipboard.writeText(createdRawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.45)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 620,
          background: '#ffffff',
          borderRadius: 14,
          boxShadow: '0 20px 45px rgba(0, 0, 0, 0.2)',
          border: '1px solid var(--ws-border)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          maxHeight: '85vh',
          animation: 'scaleIn 160ms ease-out',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--ws-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'linear-gradient(180deg, #fafafa 0%, #ffffff 100%)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'var(--ws-accent-soft)',
                color: 'var(--ws-accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
              }}
            >
              {user?.username?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: 'var(--ws-text)' }}>
                {user?.display_name || user?.username || '用户设置'}
              </h3>
              <p style={{ margin: 0, fontSize: 11, color: 'var(--ws-text-muted)' }}>
                {user?.email || (user?.type === 'ad' ? '企业 AD 域用户' : '本地用户')} • 角色: {user?.global_role || 'user'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--ws-text-muted)',
              padding: 4,
              borderRadius: 6,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Tab Navigation */}
        <div
          style={{
            display: 'flex',
            borderBottom: '1px solid var(--ws-border)',
            background: '#fafafa',
            padding: '0 20px',
          }}
        >
          <button
            type="button"
            onClick={() => setActiveTab('keys')}
            style={{
              padding: '10px 14px',
              fontSize: 13,
              fontWeight: 600,
              color: activeTab === 'keys' ? 'var(--ws-accent)' : 'var(--ws-text-muted)',
              borderBottom: activeTab === 'keys' ? '2px solid var(--ws-accent)' : '2px solid transparent',
              background: 'transparent',
              borderLeft: 'none',
              borderRight: 'none',
              borderTop: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Key size={14} />
            个人 API 密钥 ({keys.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('profile')}
            style={{
              padding: '10px 14px',
              fontSize: 13,
              fontWeight: 600,
              color: activeTab === 'profile' ? 'var(--ws-accent)' : 'var(--ws-text-muted)',
              borderBottom: activeTab === 'profile' ? '2px solid var(--ws-accent)' : '2px solid transparent',
              background: 'transparent',
              borderLeft: 'none',
              borderRight: 'none',
              borderTop: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <User size={14} />
            账号与权限详情
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {activeTab === 'keys' && (
            <div>
              {/* Notice Banner */}
              <div
                style={{
                  background: 'rgba(0, 82, 217, 0.05)',
                  border: '1px solid rgba(0, 82, 217, 0.18)',
                  borderRadius: 8,
                  padding: '10px 14px',
                  fontSize: 12,
                  color: 'var(--ws-text)',
                  marginBottom: 16,
                  lineHeight: 1.6,
                }}
              >
                <strong>💡 权限继承说明：</strong>您生成的个人 API 密钥严格继承您的 Active Directory / 工作区权限，专用于连接您的本地开发与 AI 智能体客户端（如 Cursor、Claude Desktop 或终端脚本）。
              </div>

              {/* One-Time Key Display Alert */}
              {createdRawKey && (
                <div
                  style={{
                    background: '#fffbe6',
                    border: '1px solid #ffe58f',
                    borderRadius: 8,
                    padding: '12px 16px',
                    marginBottom: 18,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#d48806', fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
                    <AlertTriangle size={16} />
                    <span>请立即复制并保存您的 API 密钥（仅显示一次）</span>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      background: '#ffffff',
                      border: '1px solid #d9d9d9',
                      borderRadius: 6,
                      padding: '8px 12px',
                    }}
                  >
                    <code
                      style={{
                        flex: 1,
                        fontFamily: 'monospace',
                        fontSize: 12,
                        wordBreak: 'break-all',
                        color: '#cf1322',
                        fontWeight: 600,
                      }}
                    >
                      {createdRawKey}
                    </code>
                    <button
                      type="button"
                      onClick={handleCopyKey}
                      className="ws-btn ws-btn--primary"
                      style={{ padding: '6px 10px', fontSize: 12 }}
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                      {copied ? '已复制' : '复制'}
                    </button>
                  </div>
                </div>
              )}

              {/* Action Bar */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ws-text)' }}>
                  有效密钥列表
                </span>
                {!isCreatingKey && (
                  <button
                    type="button"
                    onClick={() => setIsCreatingKey(true)}
                    className="ws-btn ws-btn--primary"
                    style={{ padding: '6px 12px', fontSize: 12 }}
                  >
                    <Plus size={14} />
                    生成新密钥
                  </button>
                )}
              </div>

              {/* Create Key Form */}
              {isCreatingKey && (
                <form
                  onSubmit={handleCreateKey}
                  style={{
                    background: '#f9f9f9',
                    border: '1px solid var(--ws-border)',
                    borderRadius: 8,
                    padding: 14,
                    marginBottom: 16,
                  }}
                >
                  <h4 style={{ margin: '0 0 10px', fontSize: 13, fontWeight: 700 }}>生成新个人 API 密钥</h4>
                  {errorMessage && (
                    <div style={{ color: '#d54941', fontSize: 12, marginBottom: 8 }}>{errorMessage}</div>
                  )}
                  <div style={{ marginBottom: 10 }}>
                    <label className="ws-label" style={{ marginBottom: 4 }}>密钥描述名称</label>
                    <input
                      type="text"
                      className="ws-input"
                      placeholder="如: Cursor-Desktop-Mac"
                      value={keyName}
                      onChange={(e) => setKeyName(e.target.value)}
                      autoFocus
                    />
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <label className="ws-label" style={{ marginBottom: 4 }}>有效期限 (可选)</label>
                    <input
                      type="datetime-local"
                      className="ws-input"
                      value={keyExpiry}
                      onChange={(e) => setKeyExpiry(e.target.value)}
                    />
                  </div>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      onClick={() => setIsCreatingKey(false)}
                      className="ws-btn ws-btn--ghost"
                      style={{ padding: '6px 12px', fontSize: 12 }}
                    >
                      取消
                    </button>
                    <button
                      type="submit"
                      className="ws-btn ws-btn--primary"
                      style={{ padding: '6px 14px', fontSize: 12 }}
                    >
                      立即生成
                    </button>
                  </div>
                </form>
              )}

              {/* Keys Table */}
              {isLoadingKeys ? (
                <div style={{ padding: 20, textAlign: 'center', color: 'var(--ws-text-muted)', fontSize: 13 }}>
                  加载密钥中…
                </div>
              ) : keys.length === 0 ? (
                <div
                  style={{
                    padding: '30px 20px',
                    textAlign: 'center',
                    background: '#fafafa',
                    borderRadius: 8,
                    border: '1px dashed var(--ws-border)',
                    color: 'var(--ws-text-muted)',
                    fontSize: 13,
                  }}
                >
                  暂未创建个人 API 密钥。点击上方按钮可生成新密钥。
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {keys.map((k) => (
                    <div
                      key={k.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 14px',
                        background: '#ffffff',
                        border: '1px solid var(--ws-border)',
                        borderRadius: 8,
                      }}
                    >
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--ws-text)' }}>{k.name}</span>
                          <span style={{ fontFamily: 'monospace', fontSize: 11, background: '#f0f0f0', padding: '1px 6px', borderRadius: 4 }}>
                            {k.key_prefix}…
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--ws-text-muted)', marginTop: 4, display: 'flex', gap: 12 }}>
                          <span>创建: {k.created_at ? new Date(k.created_at).toLocaleDateString() : '-'}</span>
                          {k.last_used_at && (
                            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <Clock size={11} /> 最近使用: {new Date(k.last_used_at).toLocaleDateString()}
                            </span>
                          )}
                          {k.last_used_ip && (
                            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <Globe size={11} /> IP: {k.last_used_ip}
                            </span>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRevokeKey(k.id)}
                        className="ws-btn ws-btn--danger"
                        style={{ padding: '4px 8px', fontSize: 11 }}
                        title="立即吊销"
                      >
                        <Trash2 size={13} />
                        吊销
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'profile' && (
            <div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid var(--ws-border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ws-text-muted)', textTransform: 'uppercase' }}>用户标识</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--ws-text)', marginTop: 2 }}>{user?.username} ({user?.id})</div>
                </div>

                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid var(--ws-border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ws-text-muted)', textTransform: 'uppercase' }}>全局系统角色</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ws-text)', marginTop: 2 }}>
                    <span className="ws-pill ws-pill--purple">{user?.global_role}</span>
                  </div>
                </div>

                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid var(--ws-border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ws-text-muted)', textTransform: 'uppercase' }}>所属安全组 (AD/Local Groups)</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                    {user?.groups && user.groups.length > 0 ? (
                      user.groups.map((grp) => (
                        <span key={grp} className="ws-pill ws-pill--mono" style={{ fontSize: 11 }}>
                          {grp}
                        </span>
                      ))
                    ) : (
                      <span style={{ fontSize: 12, color: 'var(--ws-text-muted)' }}>无所属组</span>
                    )}
                  </div>
                </div>

                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid var(--ws-border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ws-text-muted)', textTransform: 'uppercase' }}>已授权工作区及角色</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                    {user?.authorized_workspaces?.map((wsId) => (
                      <span key={wsId} className="ws-pill ws-pill--green" style={{ fontSize: 11 }}>
                        {wsId}: {user?.workspace_roles?.[wsId] || 'Viewer'}
                      </span>
                    ))}
                  </div>
                </div>

                <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    onClick={() => {
                      logout();
                      onClose();
                    }}
                    className="ws-btn ws-btn--danger"
                    style={{ padding: '8px 16px' }}
                  >
                    <LogOut size={14} />
                    退出登录
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
