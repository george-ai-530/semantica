/**
 * Dual-Track Login Modal Component.
 *
 * Supports corporate Active Directory (LDAP 389) authentication and
 * external guest local password verification. Stores signed JWT access token.
 */

import { useState } from 'react';
import { X, Lock, User, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAuth } from './authStore';

export function LoginModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginType, setLoginType] = useState<'' | 'ad' | 'local'>('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setErrorMessage('请输入用户名和密码。');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    const result = await login(username, password, loginType || undefined);
    setIsLoading(false);

    if (result.success) {
      setSuccessMessage('登录成功！正在进入工作区…');
      setTimeout(() => {
        onClose();
        setSuccessMessage(null);
        setPassword('');
      }, 700);
    } else {
      setErrorMessage(result.error || '登录验证失败。');
    }
  }

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
          maxWidth: 420,
          background: '#ffffff',
          borderRadius: 14,
          boxShadow: '0 20px 40px rgba(0, 0, 0, 0.18)',
          border: '1px solid var(--ws-border)',
          overflow: 'hidden',
          animation: 'scaleIn 160ms ease-out',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '18px 22px',
            borderBottom: '1px solid var(--ws-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'linear-gradient(180deg, #fafafa 0%, #ffffff 100%)',
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: 'var(--ws-text)' }}>
              用户登录 / Enterprise Sign In
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ws-text-muted)' }}>
              Active Directory LDAP 389 与 外部访客双轨认证
            </p>
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

        {/* Form Body */}
        <form onSubmit={handleSubmit} style={{ padding: '20px 22px' }}>
          {errorMessage && (
            <div
              style={{
                marginBottom: 16,
                padding: '10px 14px',
                borderRadius: 8,
                background: 'var(--ws-red-soft)',
                border: '1px solid rgba(213, 73, 65, 0.28)',
                color: '#d54941',
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <AlertCircle size={16} style={{ flexShrink: 0 }} />
              <span>{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div
              style={{
                marginBottom: 16,
                padding: '10px 14px',
                borderRadius: 8,
                background: 'var(--ws-green-soft)',
                border: '1px solid rgba(43, 164, 113, 0.28)',
                color: '#2ba471',
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <CheckCircle2 size={16} style={{ flexShrink: 0 }} />
              <span>{successMessage}</span>
            </div>
          )}

          {/* Mode Selector */}
          <div style={{ marginBottom: 16 }}>
            <label className="ws-label" style={{ marginBottom: 6 }}>认证来源</label>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 6,
                background: '#f2f2f2',
                padding: 3,
                borderRadius: 8,
              }}
            >
              {[
                { id: '', label: '自动识别' },
                { id: 'ad', label: 'AD 域员工' },
                { id: 'local', label: '外部访客' },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setLoginType(item.id as '' | 'ad' | 'local')}
                  style={{
                    padding: '6px 4px',
                    fontSize: 11,
                    fontWeight: 600,
                    borderRadius: 6,
                    border: 'none',
                    cursor: 'pointer',
                    background: loginType === item.id ? '#ffffff' : 'transparent',
                    color: loginType === item.id ? 'var(--ws-accent)' : 'var(--ws-text-muted)',
                    boxShadow: loginType === item.id ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
                    transition: 'all 140ms ease',
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {/* Username */}
          <div style={{ marginBottom: 14 }}>
            <label className="ws-label" style={{ marginBottom: 6 }}>
              {loginType === 'ad' ? '企业域用户名 (sAMAccountName)' : '用户名 (Username)'}
            </label>
            <div style={{ position: 'relative' }}>
              <User
                size={16}
                style={{
                  position: 'absolute',
                  left: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--ws-text-muted)',
                  pointerEvents: 'none',
                }}
              />
              <input
                type="text"
                className="ws-input"
                style={{ paddingLeft: 34 }}
                placeholder={loginType === 'ad' ? '如: jdoe 或 alice' : '用户名'}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                disabled={isLoading}
              />
            </div>
          </div>

          {/* Password */}
          <div style={{ marginBottom: 20 }}>
            <label className="ws-label" style={{ marginBottom: 6 }}>密码 (Password)</label>
            <div style={{ position: 'relative' }}>
              <Lock
                size={16}
                style={{
                  position: 'absolute',
                  left: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--ws-text-muted)',
                  pointerEvents: 'none',
                }}
              />
              <input
                type="password"
                className="ws-input"
                style={{ paddingLeft: 34 }}
                placeholder="请输入密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
              />
            </div>
          </div>

          {/* Submit */}
          <button
            type="submit"
            className="ws-btn ws-btn--primary"
            style={{ width: '100%', justifyContent: 'center', padding: '10px 16px', fontWeight: 700 }}
            disabled={isLoading}
          >
            {isLoading ? '正在验证身份…' : '登 录'}
          </button>

          {/* Quick Credential Hints for Ease of Verification */}
          <div
            style={{
              marginTop: 16,
              padding: '10px 12px',
              borderRadius: 8,
              background: '#f8f9fa',
              border: '1px solid var(--ws-border)',
              fontSize: 11,
              color: 'var(--ws-text-muted)',
              lineHeight: 1.5,
            }}
          >
            <div style={{ fontWeight: 700, color: 'var(--ws-text)', marginBottom: 4 }}>💡 常用凭据提示（所有密码均已统一为 1）：</div>
            <div>• <strong>系统管理员</strong>: <code>admin</code> / <code>1</code> (拥有全站与管理控制台最高权限)</div>
            <div>• <strong>测试账号 A</strong>: <code>user_a</code> / <code>1</code> (专属空间 ws_user_a)</div>
            <div>• <strong>测试账号 B</strong>: <code>user_b</code> / <code>1</code> (专属空间 ws_user_b)</div>
            <div>• <strong>LDAP 域员工</strong>: <code>testuser</code> / <code>1</code> (经由 NAS OpenLDAP 389 直连认证)</div>
          </div>
        </form>
      </div>
    </div>
  );
}
