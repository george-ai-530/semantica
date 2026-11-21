/**
 * Standalone Login Page.
 *
 * Full-screen entry page: brand bar on top, slogan panel on the left and the
 * credential card on the right. Replaces the "browse first, login later"
 * landing for unauthenticated visitors; guests can still opt into read-only
 * browsing via the link under the card.
 *
 * Authentication talks to POST /api/auth/login through the shared auth store,
 * which supports both local accounts and LDAP directory accounts.
 *
 * Visual language: same as the COWIN knowledge-base login page (light mint
 * canvas, single soft card, 40px headline, #01c15c primary button).
 */

import { useState } from 'react';
import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2 } from 'lucide-react';
import { useAuth } from './authStore';

type LoginType = '' | 'ad' | 'local';

const AUTH_SOURCES: Array<{ id: LoginType; label: string; hint: string }> = [
  { id: '', label: '自动识别', hint: '先本地账号，再回落 LDAP' },
  { id: 'ad', label: '企业域', hint: 'LDAP / AD 目录账号' },
  { id: 'local', label: '本地账号', hint: '平台内置账号' },
];

export function LoginPage({ onGuest }: { onGuest?: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginType, setLoginType] = useState<LoginType>('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setErrorMessage('请输入账号和密码。');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    const result = await login(username, password, loginType || undefined);
    setIsLoading(false);

    if (!result.success) {
      setErrorMessage(result.error || '登录验证失败，请检查账号与密码。');
      return;
    }
    // Zustand-free store notifies subscribers; App swaps to the workspace view.
    setPassword('');
  }

  return (
    <div className="cowin-login">
      <style>{LOGIN_STYLES}</style>

      <header className="cowin-login__bar">
        <div className="cowin-login__brand">
          <img src="/favicon.png" alt="COWIN" width={30} height={30} />
          <span className="cowin-login__brand-sub">知识图谱 · 本体治理</span>
        </div>
      </header>

      <main className="cowin-login__main">
        <section className="cowin-login__hero">
          <h1 className="cowin-login__title">
            像生命系统一样
            <br />
            驾驭<span>知识网络。</span>
          </h1>
          <p className="cowin-login__lede">
            COWIN 将高密度知识图谱转化为可导航的指挥中心 ——
            发现、推理、溯源、距离智能与决策上下文，尽在一个界面。
          </p>
          <ul className="cowin-login__points">
            <li>多工作区隔离</li>
            <li>本体与词汇治理</li>
            <li>溯源与决策链</li>
          </ul>
        </section>

        <section className="cowin-login__card-wrap">
          <form className="cowin-login__card" onSubmit={handleSubmit} noValidate>
            <h2 className="cowin-login__card-title">登录</h2>

            {errorMessage && (
              <div className="cowin-login__alert" role="alert">
                <AlertCircle size={16} />
                <span>{errorMessage}</span>
              </div>
            )}

            <div className="cowin-login__field">
              <label className="cowin-login__label" htmlFor="cowin-login-account">
                <em>*</em> 账号
              </label>
              <input
                id="cowin-login-account"
                className="cowin-login__input"
                type="text"
                autoComplete="username"
                placeholder={loginType === 'ad' ? '请输入域账号，如 admin' : '请输入用户名'}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isLoading}
                autoFocus
              />
            </div>

            <div className="cowin-login__field">
              <label className="cowin-login__label" htmlFor="cowin-login-password">
                <em>*</em> 密码
              </label>
              <div className="cowin-login__input-wrap">
                <input
                  id="cowin-login-password"
                  className="cowin-login__input"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                />
                <button
                  type="button"
                  className="cowin-login__eye"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  tabIndex={-1}
                >
                  {showPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                </button>
              </div>
            </div>

            <div className="cowin-login__field cowin-login__field--source">
              <span className="cowin-login__label">认证来源</span>
              <div className="cowin-login__segmented" role="group" aria-label="认证来源">
                {AUTH_SOURCES.map((item) => (
                  <button
                    key={item.id || 'auto'}
                    type="button"
                    className="cowin-login__segment"
                    data-active={loginType === item.id}
                    title={item.hint}
                    onClick={() => setLoginType(item.id)}
                    disabled={isLoading}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <button
              className="cowin-login__submit"
              type="submit"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  正在验证…
                </>
              ) : (
                '登录'
              )}
            </button>

            {onGuest && (
              <button type="button" className="cowin-login__guest" onClick={onGuest}>
                先只看不登录（访客只读）
                <ArrowRight size={13} />
              </button>
            )}
          </form>
        </section>
      </main>
    </div>
  );
}

const LOGIN_STYLES = `
.cowin-login {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  overflow: auto;
  color: #1f2d24;
  font-family: inherit;
  background:
    radial-gradient(62% 78% at 4% 62%, #eaf7f0 0%, rgba(234, 247, 240, 0) 68%),
    radial-gradient(46% 58% at 40% 112%, #f0f9f4 0%, rgba(240, 249, 244, 0) 74%),
    #fcfefd;
}

/* ---------- top bar ---------- */
.cowin-login__bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 30px 34px 0 52px;
}
.cowin-login__brand { display: flex; align-items: center; gap: 10px; }
.cowin-login__brand img { display: block; border-radius: 4px; }
.cowin-login__brand-sub {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: #4a5b52;
}

/* ---------- main ---------- */
.cowin-login__main {
  flex: 1 1 auto;
  width: 100%;
  max-width: 1908px;
  margin: 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 48px;
  padding: 111px 187px 56px 52px;
  box-sizing: border-box;
}
.cowin-login__hero { padding-top: 2px; }
.cowin-login__title {
  margin: 0;
  font-size: clamp(30px, 2.9vw, 40px);
  line-height: 1.28;
  font-weight: 700;
  letter-spacing: 0.4px;
  color: #0f1f16;
}
.cowin-login__title span { color: #01a04e; }
.cowin-login__lede {
  margin: 26px 0 0;
  max-width: 34em;
  font-size: 15px;
  line-height: 1.9;
  color: #5c6b62;
}
.cowin-login__points {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 26px 0 0;
  padding: 0;
}
.cowin-login__points li {
  font-size: 12.5px;
  font-weight: 500;
  color: #3d6b53;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid #e2efe7;
  border-radius: 999px;
  padding: 7px 15px;
}

/* ---------- card ---------- */
.cowin-login__card-wrap {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
}
.cowin-login__card {
  width: 476px;
  background: #ffffff;
  border: none;
  border-radius: 12px;
  box-shadow: 0 10px 34px rgba(17, 47, 30, 0.07);
  padding: 36px 40px 40px;
  box-sizing: border-box;
}
.cowin-login__card-title {
  margin: 0 0 34px;
  text-align: center;
  font-size: 27px;
  line-height: 1.35;
  font-weight: 600;
  color: #14201a;
}

/* ---------- fields ---------- */
.cowin-login__field { margin-bottom: 32px; }
.cowin-login__field--source { margin-bottom: 25px; }
.cowin-login__label {
  display: block;
  margin-bottom: 12px;
  font-size: 16px;
  font-weight: 500;
  line-height: 20px;
  color: #26312a;
}
.cowin-login__label em { color: #e34d59; font-style: normal; margin-right: 3px; }
.cowin-login__input-wrap { position: relative; }
.cowin-login__input {
  width: 100%;
  box-sizing: border-box;
  height: 48px;
  padding: 0 14px;
  font-size: 15px;
  font-family: inherit;
  color: #1b241e;
  background: #ffffff;
  border: 1px solid #e3e7e3;
  border-radius: 8px;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.cowin-login__input-wrap .cowin-login__input { padding-right: 42px; }
.cowin-login__input::placeholder { color: #b3bbb5; }
.cowin-login__input:hover:not(:disabled) { border-color: #c9d6cd; }
.cowin-login__input:focus {
  outline: none;
  border-color: #01c15c;
  box-shadow: 0 0 0 3px rgba(1, 193, 92, 0.10);
}
.cowin-login__eye {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #9aa79f;
  cursor: pointer;
}
.cowin-login__eye:hover { background: #f4f8f5; color: #5d6f64; }

.cowin-login__segmented {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 4px;
  background: #f4f7f4;
  border-radius: 8px;
}
.cowin-login__segment {
  padding: 8px 4px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  color: #7b8880;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, box-shadow 160ms ease;
}
.cowin-login__segment:hover:not(:disabled) { color: #3d4a43; }
.cowin-login__segment[data-active='true'] {
  background: #ffffff;
  color: #019a4b;
  box-shadow: 0 1px 3px rgba(9, 61, 42, 0.10);
}

.cowin-login__alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 20px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: #c0392b;
  background: #fdf2f2;
  border: 1px solid #f6d6d6;
}

/* ---------- actions ---------- */
.cowin-login__submit {
  width: 100%;
  height: 54px;
  margin: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-family: inherit;
  font-size: 17px;
  font-weight: 500;
  color: #ffffff;
  background: #01c15c;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: background 160ms ease;
}
.cowin-login__submit:hover:not(:disabled) { background: #00b155; }
.cowin-login__submit:disabled { background: #8fdbb4; cursor: not-allowed; }

.cowin-login__guest {
  width: 100%;
  margin-top: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 2px;
  font-family: inherit;
  font-size: 13px;
  color: #7b8880;
  background: transparent;
  border: none;
  cursor: pointer;
}
.cowin-login__guest:hover { color: #019a4b; }

/* ---------- responsive ---------- */
@media (max-width: 1500px) {
  .cowin-login__main { padding: 88px 72px 56px 48px; }
  .cowin-login__card { width: 452px; }
}
@media (max-width: 1100px) {
  .cowin-login__main {
    padding: 64px 40px 48px;
    justify-content: center;
  }
  .cowin-login__hero { display: none; }
  .cowin-login__card-wrap { justify-content: center; }
}
@media (max-width: 560px) {
  .cowin-login__bar { padding: 20px 20px 0; }
  .cowin-login__main { padding: 32px 20px 40px; }
  .cowin-login__card { width: 100%; padding: 28px 22px 30px; }
  .cowin-login__card-title { font-size: 22px; margin-bottom: 26px; }
}
`;
