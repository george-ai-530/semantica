/**
 * Administrative Governance Console Workspace.
 *
 * Provides dedicated administrative tooling for:
 *   1. External Guests: Account creation with password hashing and mandatory expiry datepicker
 *   2. Workspaces & Grants: Multi-workspace isolation and AD/local group ACL matrix
 *   3. Local Groups: Ad-hoc local group management and user assignments
 *   4. API Key Inventory: Global audit table, emergency revocation, and service accounts
 */

import { useState, useEffect } from 'react';
import {
  Shield,
  Users,
  Layers,
  Key,
  Plus,
  Trash2,
  Clock,
  AlertTriangle,
  Check,
  Copy,
  RefreshCw,
  UserCheck,
  UserX,
  X,
  UserPlus,
  Lock,
} from 'lucide-react';
import { useAuth } from '../../auth/authStore';
import { LoginModal } from '../../auth/LoginModal';

type AdminTab = 'guests' | 'workspaces' | 'groups' | 'keys';

interface ExternalUser {
  id: string;
  username: string;
  display_name?: string;
  email?: string;
  user_type: string;
  is_active: boolean;
  global_role: string;
  expires_at?: string;
  is_expired: boolean;
  created_at: string;
}

interface WorkspaceRecord {
  id: string;
  name: string;
  description?: string;
  graph_id: string;
  is_default: boolean;
}

interface WorkspaceGrantRecord {
  id: string;
  workspace_id: string;
  grantee_type: 'user' | 'group';
  grantee_id: string;
  role: 'Viewer' | 'Editor' | 'Admin';
  created_at: string;
}

interface LocalGroupRecord {
  id: string;
  name: string;
  group_type: string;
  description?: string;
  member_count?: number;
}

interface GlobalApiKeyRecord {
  id: string;
  name: string;
  key_prefix: string;
  user_id?: string;
  owner_username?: string;
  is_service: boolean;
  allowed_workspaces: string[];
  is_active: boolean;
  is_expired: boolean;
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
  last_used_ip?: string;
  revoked_at?: string;
}

export function AdminWorkspace() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<AdminTab>('guests');

  // Tab 1: External Guests state
  const [guests, setGuests] = useState<ExternalUser[]>([]);
  const [isLoadingGuests, setIsLoadingGuests] = useState(false);
  const [showCreateGuestModal, setShowCreateGuestModal] = useState(false);
  const [guestForm, setGuestForm] = useState({
    username: '',
    password: '',
    display_name: '',
    email: '',
    expires_at: '',
    is_active: true,
  });

  // Tab 2: Workspaces & Grants state
  const [adminWorkspaces, setAdminWorkspaces] = useState<WorkspaceRecord[]>([]);
  const [selectedWsId, setSelectedWsId] = useState<string>('default');
  const [grants, setGrants] = useState<WorkspaceGrantRecord[]>([]);
  const [isLoadingGrants, setIsLoadingGrants] = useState(false);
  const [showCreateWsModal, setShowCreateWsModal] = useState(false);
  const [wsForm, setWsForm] = useState({ name: '', id: '', description: '' });
  const [showAddGrantModal, setShowAddGrantModal] = useState(false);
  const [grantForm, setGrantForm] = useState({
    grantee_type: 'group' as 'group' | 'user',
    grantee_id: '',
    role: 'Viewer' as 'Viewer' | 'Editor' | 'Admin',
  });

  // Tab 3: Local Groups state
  const [groups, setGroups] = useState<LocalGroupRecord[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(false);
  const [showCreateGroupModal, setShowCreateGroupModal] = useState(false);
  const [groupForm, setGroupForm] = useState({ name: '', description: '' });
  const [selectedGroup, setSelectedGroup] = useState<LocalGroupRecord | null>(null);
  const [groupMembers, setGroupMembers] = useState<any[]>([]);
  const [showGroupMembersModal, setShowGroupMembersModal] = useState(false);
  const [newMemberUsername, setNewMemberUsername] = useState('');

  // Tab 4: API Keys state
  const [adminKeys, setAdminKeys] = useState<GlobalApiKeyRecord[]>([]);
  const [isLoadingAdminKeys, setIsLoadingAdminKeys] = useState(false);
  const [showCreateServiceKeyModal, setShowCreateServiceKeyModal] = useState(false);
  const [serviceKeyForm, setServiceKeyForm] = useState({ name: '', allowed_workspaces: '*', expires_at: '' });
  const [createdServiceRawKey, setCreatedServiceRawKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);

  // Guard non-admin access
  if (!user || user.global_role !== 'admin') {
    return (
      <div className="ws-page" style={{ padding: 40, alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ maxWidth: 520, textAlign: 'center', background: '#fff', padding: 36, borderRadius: 14, border: '1px solid var(--ws-border)', boxShadow: '0 8px 30px rgba(0,0,0,0.06)' }}>
          <div style={{ width: 64, height: 64, borderRadius: '50%', background: 'rgba(213, 73, 65, 0.08)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
            <Shield size={36} style={{ color: '#d54941' }} />
          </div>
          <h2 style={{ fontSize: 20, fontWeight: 800, margin: '0 0 10px', color: 'var(--ws-text)' }}>
            企业管理控制台 (需要 Admin 权限)
          </h2>
          <p style={{ fontSize: 13, color: 'var(--ws-text-muted)', lineHeight: 1.6, margin: '0 0 20px' }}>
            管理控制台汇集企业级治理中枢，受到严格的 RBAC 路由守护。<br />
            {user ? (
              <>您当前以 <strong>{user.display_name || user.username}</strong> ({user.global_role}) 身份登录，未获得全局管理员权限。</>
            ) : (
              <>当前处于访客未登录状态。请使用管理员凭据登录以解锁治理功能。</>
            )}
          </p>

          <div style={{ textAlign: 'left', background: '#f8f9fa', padding: '14px 18px', borderRadius: 10, border: '1px solid var(--ws-border)', marginBottom: 24, fontSize: 12, color: 'var(--ws-text)' }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>🛡️ 本控制台提供以下管控能力：</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, color: 'var(--ws-text-muted)' }}>
              <div>• 外部访客 CRUD 与到期强制失效</div>
              <div>• 多工作区隔离与 ACL 授权矩阵</div>
              <div>• 本地组织群组与成员分配</div>
              <div>• 全局 API 密钥清单与紧急撤销</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
            <button
              type="button"
              onClick={() => setIsLoginModalOpen(true)}
              className="ws-btn ws-btn--primary"
              style={{ padding: '8px 20px', fontSize: 13, fontWeight: 700 }}
            >
              <Lock size={14} />
              <span>以管理员身份登录 (admin / Young520)</span>
            </button>
          </div>
        </div>
        <LoginModal isOpen={isLoginModalOpen} onClose={() => setIsLoginModalOpen(false)} />
      </div>
    );
  }

  // Load active tab data
  useEffect(() => {
    if (activeTab === 'guests') loadGuests();
    if (activeTab === 'workspaces') {
      loadWorkspaces();
      loadGrants(selectedWsId);
    }
    if (activeTab === 'groups') loadGroups();
    if (activeTab === 'keys') loadAdminKeys();
  }, [activeTab]);

  function showMessage(text: string, type: 'success' | 'error' = 'success') {
    setFeedbackMsg({ text, type });
    setTimeout(() => setFeedbackMsg(null), 3000);
  }

  // ---------------------------------------------------------------------------
  // Tab 1: External Guests API
  // ---------------------------------------------------------------------------
  async function loadGuests() {
    setIsLoadingGuests(true);
    try {
      const res = await fetch('/api/admin/users/external');
      if (res.ok) {
        setGuests(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingGuests(false);
    }
  }

  async function handleCreateGuest(e: React.FormEvent) {
    e.preventDefault();
    if (!guestForm.username.trim() || !guestForm.password) {
      showMessage('用户名与密码必填', 'error');
      return;
    }
    try {
      const res = await fetch('/api/admin/users/external', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: guestForm.username.trim(),
          password: guestForm.password,
          display_name: guestForm.display_name.trim() || undefined,
          email: guestForm.email.trim() || undefined,
          expires_at: guestForm.expires_at || undefined,
          is_active: guestForm.is_active,
        }),
      });
      if (res.ok) {
        showMessage('访客账户创建成功');
        setShowCreateGuestModal(false);
        setGuestForm({ username: '', password: '', display_name: '', email: '', expires_at: '', is_active: true });
        loadGuests();
      } else {
        const data = await res.json();
        showMessage(data.detail || '创建失败', 'error');
      }
    } catch (e) {
      showMessage('网络请求异常', 'error');
    }
  }

  async function handleToggleGuestActive(u: ExternalUser) {
    try {
      const res = await fetch(`/api/admin/users/external/${u.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !u.is_active }),
      });
      if (res.ok) {
        showMessage(`账户 ${u.username} 已${u.is_active ? '停用' : '启用'}`);
        loadGuests();
      }
    } catch (e) {
      showMessage('操作失败', 'error');
    }
  }

  async function handleDeleteGuest(u: ExternalUser) {
    if (!window.confirm(`确认删除访客账户 ${u.username}？`)) return;
    try {
      const res = await fetch(`/api/admin/users/external/${u.id}`, { method: 'DELETE' });
      if (res.ok) {
        showMessage(`账户 ${u.username} 已删除`);
        loadGuests();
      }
    } catch (e) {
      showMessage('删除失败', 'error');
    }
  }

  // ---------------------------------------------------------------------------
  // Tab 2: Workspaces & Grants API
  // ---------------------------------------------------------------------------
  async function loadWorkspaces() {
    try {
      const res = await fetch('/api/admin/workspaces');
      if (res.ok) {
        const list = await res.json();
        setAdminWorkspaces(list);
        if (list.length > 0 && !list.some((w: any) => w.id === selectedWsId)) {
          setSelectedWsId(list[0].id);
          loadGrants(list[0].id);
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function loadGrants(wsId: string) {
    if (!wsId) return;
    setIsLoadingGrants(true);
    try {
      const res = await fetch(`/api/admin/workspaces/${wsId}/grants`);
      if (res.ok) {
        setGrants(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingGrants(false);
    }
  }

  async function handleCreateWorkspace(e: React.FormEvent) {
    e.preventDefault();
    if (!wsForm.name.trim()) {
      showMessage('工作区名称必填', 'error');
      return;
    }
    try {
      const res = await fetch('/api/admin/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: wsForm.name.trim(),
          workspace_id: wsForm.id.trim() || undefined,
          description: wsForm.description.trim() || undefined,
        }),
      });
      if (res.ok) {
        showMessage('工作区创建成功');
        setShowCreateWsModal(false);
        setWsForm({ name: '', id: '', description: '' });
        await loadWorkspaces();
      } else {
        const data = await res.json();
        showMessage(data.detail || '创建工作区失败', 'error');
      }
    } catch (e) {
      showMessage('网络请求异常', 'error');
    }
  }

  async function handleAddGrant(e: React.FormEvent) {
    e.preventDefault();
    if (!grantForm.grantee_id.trim()) {
      showMessage('授权主体标识必填', 'error');
      return;
    }
    try {
      const res = await fetch(`/api/admin/workspaces/${selectedWsId}/grants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          grantee_type: grantForm.grantee_type,
          grantee_id: grantForm.grantee_id.trim(),
          role: grantForm.role,
        }),
      });
      if (res.ok) {
        showMessage('权限授予配置成功');
        setShowAddGrantModal(false);
        setGrantForm({ grantee_type: 'group', grantee_id: '', role: 'Viewer' });
        loadGrants(selectedWsId);
      } else {
        const data = await res.json();
        showMessage(data.detail || '授予权限失败', 'error');
      }
    } catch (e) {
      showMessage('网络请求异常', 'error');
    }
  }

  async function handleRevokeGrant(grantId: string) {
    if (!window.confirm('确认移除此权限授予？')) return;
    try {
      const res = await fetch(`/api/admin/workspaces/${selectedWsId}/grants/${grantId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showMessage('权限已移除');
        loadGrants(selectedWsId);
      }
    } catch (e) {
      showMessage('移除失败', 'error');
    }
  }

  // ---------------------------------------------------------------------------
  // Tab 3: Local Groups API
  // ---------------------------------------------------------------------------
  async function loadGroups() {
    setIsLoadingGroups(true);
    try {
      const res = await fetch('/api/admin/groups');
      if (res.ok) {
        setGroups(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingGroups(false);
    }
  }

  async function handleCreateGroup(e: React.FormEvent) {
    e.preventDefault();
    if (!groupForm.name.trim()) {
      showMessage('组名称必填', 'error');
      return;
    }
    try {
      const res = await fetch('/api/admin/groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: groupForm.name.trim(),
          description: groupForm.description.trim() || undefined,
        }),
      });
      if (res.ok) {
        showMessage('本地安全组创建成功');
        setShowCreateGroupModal(false);
        setGroupForm({ name: '', description: '' });
        loadGroups();
      } else {
        const data = await res.json();
        showMessage(data.detail || '创建组失败', 'error');
      }
    } catch (e) {
      showMessage('网络请求异常', 'error');
    }
  }

  async function openGroupMembers(grp: LocalGroupRecord) {
    setSelectedGroup(grp);
    setShowGroupMembersModal(true);
    try {
      const res = await fetch(`/api/admin/groups/${grp.id}`);
      if (res.ok) {
        const data = await res.json();
        setGroupMembers(data.members || []);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function handleAddGroupMember(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedGroup || !newMemberUsername.trim()) return;
    try {
      const res = await fetch(`/api/admin/groups/${selectedGroup.id}/members`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newMemberUsername.trim() }),
      });
      if (res.ok) {
        showMessage('添加成员成功');
        setNewMemberUsername('');
        openGroupMembers(selectedGroup);
        loadGroups();
      } else {
        const data = await res.json();
        showMessage(data.detail || '添加失败', 'error');
      }
    } catch (e) {
      showMessage('请求失败', 'error');
    }
  }

  async function handleRemoveGroupMember(userId: string) {
    if (!selectedGroup) return;
    try {
      const res = await fetch(`/api/admin/groups/${selectedGroup.id}/members/${userId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showMessage('已移除成员');
        openGroupMembers(selectedGroup);
        loadGroups();
      }
    } catch (e) {
      showMessage('移除失败', 'error');
    }
  }

  // ---------------------------------------------------------------------------
  // Tab 4: API Keys Audit API
  // ---------------------------------------------------------------------------
  async function loadAdminKeys() {
    setIsLoadingAdminKeys(true);
    try {
      const res = await fetch('/api/admin/keys');
      if (res.ok) {
        setAdminKeys(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingAdminKeys(false);
    }
  }

  async function handleCreateServiceKey(e: React.FormEvent) {
    e.preventDefault();
    if (!serviceKeyForm.name.trim()) {
      showMessage('服务账号名称必填', 'error');
      return;
    }
    const workspaces = serviceKeyForm.allowed_workspaces === '*'
      ? ['*']
      : serviceKeyForm.allowed_workspaces.split(',').map((s) => s.trim()).filter(Boolean);

    try {
      const res = await fetch('/api/admin/keys/service', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: serviceKeyForm.name.trim(),
          allowed_workspaces: workspaces,
          expires_at: serviceKeyForm.expires_at || undefined,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setCreatedServiceRawKey(data.raw_key);
        setShowCreateServiceKeyModal(false);
        setServiceKeyForm({ name: '', allowed_workspaces: '*', expires_at: '' });
        loadAdminKeys();
      } else {
        showMessage(data.detail || '创建服务密钥失败', 'error');
      }
    } catch (e) {
      showMessage('请求失败', 'error');
    }
  }

  async function handleAdminRevokeKey(keyId: string, name: string) {
    if (!window.confirm(`⚠️ 安全告警：确认立即吊销密钥 "${name}"？吊销后任何持有此凭据的外部服务将立即被拒！`)) {
      return;
    }
    try {
      const res = await fetch(`/api/admin/keys/${keyId}`, { method: 'DELETE' });
      if (res.ok) {
        showMessage(`密钥 "${name}" 已成功吊销`);
        loadAdminKeys();
      } else {
        const data = await res.json();
        showMessage(data.detail || '吊销失败', 'error');
      }
    } catch (e) {
      showMessage('请求失败', 'error');
    }
  }

  return (
    <div className="ws-page">
      {/* Feedback Alert Toast */}
      {feedbackMsg && (
        <div
          style={{
            position: 'fixed',
            top: 18,
            right: 24,
            zIndex: 9999,
            padding: '10px 18px',
            borderRadius: 8,
            background: feedbackMsg.type === 'success' ? '#2ba471' : '#d54941',
            color: '#ffffff',
            fontSize: 13,
            fontWeight: 600,
            boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            animation: 'fadeIn 120ms ease',
          }}
        >
          {feedbackMsg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedbackMsg.text}</span>
        </div>
      )}

      {/* Hero Header */}
      <div
        style={{
          padding: '24px 32px 18px',
          background: 'linear-gradient(180deg, #ffffff 0%, #fafafa 100%)',
          borderBottom: '1px solid var(--ws-border)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <Shield size={22} style={{ color: 'var(--ws-accent)' }} />
          <span className="ws-eyebrow" style={{ color: 'var(--ws-accent)' }}>
            Enterprise Governance & Security
          </span>
        </div>
        <h1 className="ws-title" style={{ fontSize: 24 }}>管理控制台 (Admin Console)</h1>
        <p className="ws-body" style={{ margin: '4px 0 16px', maxWidth: 800 }}>
          集中配置外部访客凭据与有效期、工作区物理隔离与 AD 组角色授权矩阵、本地安全组及全局 API 密钥审计。
        </p>

        {/* Console Navigation Tabs */}
        <div style={{ display: 'flex', gap: 8 }}>
          {[
            { id: 'guests', label: '外部访客管理', icon: Users, count: guests.length },
            { id: 'workspaces', label: '工作区与权限授予', icon: Layers, count: adminWorkspaces.length },
            { id: 'groups', label: '本地安全组', icon: UserPlus, count: groups.length },
            { id: 'keys', label: 'API 密钥审计与服务账号', icon: Key, count: adminKeys.length },
          ].map((tab) => {
            const Icon = tab.icon;
            const isSelected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id as AdminTab)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 16px',
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: 'pointer',
                  border: isSelected ? '1px solid rgba(0, 82, 217, 0.4)' : '1px solid var(--ws-border)',
                  background: isSelected ? 'var(--ws-accent-soft)' : '#ffffff',
                  color: isSelected ? 'var(--ws-accent)' : 'var(--ws-text)',
                  boxShadow: isSelected ? '0 2px 6px rgba(0, 82, 217, 0.08)' : 'none',
                  transition: 'all 140ms ease',
                }}
              >
                <Icon size={16} />
                <span>{tab.label}</span>
                {tab.count !== undefined && (
                  <span
                    className="ws-pill ws-pill--mono"
                    style={{ fontSize: 10, padding: '1px 5px' }}
                  >
                    {tab.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Workspace Scroll Body */}
      <div className="ws-scroll" style={{ padding: '24px 32px' }}>
        {/* =================================================================== */}
        {/* Tab 1: External Guests                                              */}
        {/* =================================================================== */}
        {activeTab === 'guests' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>外部访客与临时顾问账户</h3>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ws-text-muted)' }}>
                  管理非 Active Directory 域账号的本地访客凭据，强制设定账户过期时间 (expires_at)。
                </p>
              </div>
              <button
                type="button"
                className="ws-btn ws-btn--primary"
                onClick={() => setShowCreateGuestModal(true)}
              >
                <Plus size={15} />
                创建访客账户
              </button>
            </div>

            {isLoadingGuests ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>加载访客列表中…</div>
            ) : guests.length === 0 ? (
              <div className="ws-panel" style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>
                当前暂无外部访客账户。点击右上角“创建访客账户”开始添加。
              </div>
            ) : (
              <div className="ws-panel" style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ background: '#f5f5f5', borderBottom: '1px solid var(--ws-border)' }}>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>用户名</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>姓名/显示名</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>邮箱</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>有效期限 (Expires At)</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>状态</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {guests.map((g) => (
                      <tr key={g.id} style={{ borderBottom: '1px solid var(--ws-border)', background: '#fff' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 600 }}>{g.username}</td>
                        <td style={{ padding: '10px 14px' }}>{g.display_name || '-'}</td>
                        <td style={{ padding: '10px 14px', color: 'var(--ws-text-muted)' }}>{g.email || '-'}</td>
                        <td style={{ padding: '10px 14px' }}>
                          {g.expires_at ? (
                            <span
                              className={`ws-pill ${g.is_expired ? 'ws-pill--red' : 'ws-pill--green'}`}
                              style={{ fontSize: 11 }}
                            >
                              <Clock size={11} />
                              {new Date(g.expires_at).toLocaleString()}
                              {g.is_expired && ' (已过期)'}
                            </span>
                          ) : (
                            <span className="ws-pill ws-pill--mono" style={{ fontSize: 11 }}>永久有效</span>
                          )}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            className={`ws-pill ${g.is_active ? 'ws-pill--green' : 'ws-pill--mono'}`}
                            style={{ fontSize: 11 }}
                          >
                            {g.is_active ? '正常' : '已停用'}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                          <button
                            type="button"
                            className="ws-btn ws-btn--ghost"
                            style={{ padding: '4px 8px', fontSize: 11, marginRight: 6 }}
                            onClick={() => handleToggleGuestActive(g)}
                          >
                            {g.is_active ? <UserX size={12} /> : <UserCheck size={12} />}
                            {g.is_active ? '停用' : '启用'}
                          </button>
                          <button
                            type="button"
                            className="ws-btn ws-btn--danger"
                            style={{ padding: '4px 8px', fontSize: 11 }}
                            onClick={() => handleDeleteGuest(g)}
                          >
                            <Trash2 size={12} />
                            删除
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* =================================================================== */}
        {/* Tab 2: Workspaces & Grants                                          */}
        {/* =================================================================== */}
        {activeTab === 'workspaces' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>工作区隔离与 ACL 角色授权矩阵</h3>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ws-text-muted)' }}>
                  将 AD 安全组 (如 <code>CN=Finance-Team</code>) 或本地用户映射至各工作区角色 (Viewer, Editor, Admin)。
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className="ws-btn ws-btn--ghost"
                  onClick={() => setShowCreateWsModal(true)}
                >
                  <Plus size={15} />
                  新建工作区
                </button>
                <button
                  type="button"
                  className="ws-btn ws-btn--primary"
                  onClick={() => setShowAddGrantModal(true)}
                >
                  <Plus size={15} />
                  添加权限授予
                </button>
              </div>
            </div>

            {/* Workspace Filter Bar */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                marginBottom: 16,
                background: '#ffffff',
                padding: '10px 16px',
                borderRadius: 8,
                border: '1px solid var(--ws-border)',
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 700 }}>当前审查工作区:</span>
              <select
                className="ws-input"
                style={{ maxWidth: 260, padding: '6px 10px' }}
                value={selectedWsId}
                onChange={(e) => {
                  setSelectedWsId(e.target.value);
                  loadGrants(e.target.value);
                }}
              >
                {adminWorkspaces.map((ws) => (
                  <option key={ws.id} value={ws.id}>
                    {ws.name} ({ws.id}) {ws.is_default ? '★默认' : ''}
                  </option>
                ))}
              </select>
              <span style={{ fontSize: 12, color: 'var(--ws-text-muted)' }}>
                物理图谱标识: <code>graph:{selectedWsId}</code>
              </span>
            </div>

            {isLoadingGrants ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>加载授权中…</div>
            ) : grants.length === 0 ? (
              <div className="ws-panel" style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>
                当前工作区暂无特定 ACL 授予规则。点击上方“添加权限授予”进行配置。
              </div>
            ) : (
              <div className="ws-panel">
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ background: '#f5f5f5', borderBottom: '1px solid var(--ws-border)' }}>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>授权主体类型</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>主体标识 (DN / 组名 / 用户名)</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>授予角色 (RBAC Role)</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>授予时间</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grants.map((gr) => (
                      <tr key={gr.id} style={{ borderBottom: '1px solid var(--ws-border)', background: '#fff' }}>
                        <td style={{ padding: '10px 14px' }}>
                          <span className={`ws-pill ${gr.grantee_type === 'group' ? 'ws-pill--accent' : 'ws-pill--mono'}`}>
                            {gr.grantee_type === 'group' ? '安全组 (Group)' : '单用户 (User)'}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', fontFamily: 'monospace', fontWeight: 600 }}>
                          {gr.grantee_id}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            className={`ws-pill ${
                              gr.role === 'Admin'
                                ? 'ws-pill--purple'
                                : gr.role === 'Editor'
                                ? 'ws-pill--green'
                                : 'ws-pill--mono'
                            }`}
                          >
                            {gr.role}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--ws-text-muted)' }}>
                          {new Date(gr.created_at).toLocaleDateString()}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                          <button
                            type="button"
                            className="ws-btn ws-btn--danger"
                            style={{ padding: '4px 8px', fontSize: 11 }}
                            onClick={() => handleRevokeGrant(gr.id)}
                          >
                            <Trash2 size={12} />
                            移除授权
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* =================================================================== */}
        {/* Tab 3: Local Groups                                                 */}
        {/* =================================================================== */}
        {activeTab === 'groups' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>本地 Ad-Hoc 跨部门安全组</h3>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ws-text-muted)' }}>
                  无需向企业 IT 提单即可快速组建跨项目本地任务组，并批量分配图谱访问权限。
                </p>
              </div>
              <button
                type="button"
                className="ws-btn ws-btn--primary"
                onClick={() => setShowCreateGroupModal(true)}
              >
                <Plus size={15} />
                新建本地组
              </button>
            </div>

            {isLoadingGroups ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>加载组列表中…</div>
            ) : groups.length === 0 ? (
              <div className="ws-panel" style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>
                暂无本地安全组。
              </div>
            ) : (
              <div className="ws-panel">
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ background: '#f5f5f5', borderBottom: '1px solid var(--ws-border)' }}>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>组名称</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>类型</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>描述说明</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>成员人数</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((grp) => (
                      <tr key={grp.id} style={{ borderBottom: '1px solid var(--ws-border)', background: '#fff' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 700 }}>{grp.name}</td>
                        <td style={{ padding: '10px 14px' }}>
                          <span className={`ws-pill ${grp.group_type === 'ad' ? 'ws-pill--accent' : 'ws-pill--mono'}`}>
                            {grp.group_type === 'ad' ? 'AD 同步组' : '本地自定义组'}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--ws-text-muted)' }}>{grp.description || '-'}</td>
                        <td style={{ padding: '10px 14px' }}>{grp.member_count ?? 0} 人</td>
                        <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                          <button
                            type="button"
                            className="ws-btn ws-btn--ghost"
                            style={{ padding: '4px 10px', fontSize: 11 }}
                            onClick={() => openGroupMembers(grp)}
                          >
                            <Users size={12} />
                            管理成员
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* =================================================================== */}
        {/* Tab 4: API Key Inventory & Service Accounts                         */}
        {/* =================================================================== */}
        {activeTab === 'keys' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>全系统 API 密钥全局审计与服务账号</h3>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--ws-text-muted)' }}>
                  审计所有机器间调用的 API 密钥、绑定负责人及最近来源 IP，支持高危令牌一键紧急吊销。
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className="ws-btn ws-btn--ghost"
                  onClick={loadAdminKeys}
                >
                  <RefreshCw size={14} />
                  刷新审计
                </button>
                <button
                  type="button"
                  className="ws-btn ws-btn--primary"
                  onClick={() => setShowCreateServiceKeyModal(true)}
                >
                  <Plus size={15} />
                  创建服务账号密钥
                </button>
              </div>
            </div>

            {/* Created Service Key One-time Alert */}
            {createdServiceRawKey && (
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
                  <span>服务账号密钥创建成功（仅展示一次，请立即复制）</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#fff', padding: 8, borderRadius: 6, border: '1px solid #d9d9d9' }}>
                  <code style={{ flex: 1, color: '#cf1322', fontWeight: 600, fontFamily: 'monospace', fontSize: 12 }}>
                    {createdServiceRawKey}
                  </code>
                  <button
                    type="button"
                    className="ws-btn ws-btn--primary"
                    style={{ padding: '4px 10px', fontSize: 12 }}
                    onClick={() => {
                      navigator.clipboard.writeText(createdServiceRawKey);
                      setCopiedKey(true);
                      setTimeout(() => setCopiedKey(false), 2000);
                    }}
                  >
                    {copiedKey ? <Check size={13} /> : <Copy size={13} />}
                    {copiedKey ? '已复制' : '复制'}
                  </button>
                </div>
              </div>
            )}

            {isLoadingAdminKeys ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>加载全局密钥清单中…</div>
            ) : adminKeys.length === 0 ? (
              <div className="ws-panel" style={{ padding: 40, textAlign: 'center', color: 'var(--ws-text-muted)' }}>
                暂无活跃 API 密钥。
              </div>
            ) : (
              <div className="ws-panel">
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ background: '#f5f5f5', borderBottom: '1px solid var(--ws-border)' }}>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>密钥名称</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>前缀</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>类型 / 所有者</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>许可工作区</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>最近调用 IP</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700 }}>状态</th>
                      <th style={{ padding: '10px 14px', fontWeight: 700, textAlign: 'right' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminKeys.map((k) => (
                      <tr key={k.id} style={{ borderBottom: '1px solid var(--ws-border)', background: '#fff' }}>
                        <td style={{ padding: '10px 14px', fontWeight: 700 }}>{k.name}</td>
                        <td style={{ padding: '10px 14px', fontFamily: 'monospace' }}>{k.key_prefix}…</td>
                        <td style={{ padding: '10px 14px' }}>
                          <span className={`ws-pill ${k.is_service ? 'ws-pill--purple' : 'ws-pill--mono'}`}>
                            {k.is_service ? '服务账号' : `用户: ${k.owner_username || k.user_id}`}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', fontSize: 12 }}>
                          {k.allowed_workspaces?.join(', ') || '*'}
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--ws-text-muted)', fontSize: 12 }}>
                          {k.last_used_ip || '未记录'}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          {k.revoked_at ? (
                            <span className="ws-pill ws-pill--red">已吊销</span>
                          ) : k.is_expired ? (
                            <span className="ws-pill ws-pill--amber">已过期</span>
                          ) : (
                            <span className="ws-pill ws-pill--green">活跃中</span>
                          )}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                          {!k.revoked_at && (
                            <button
                              type="button"
                              className="ws-btn ws-btn--danger"
                              style={{ padding: '4px 8px', fontSize: 11 }}
                              onClick={() => handleAdminRevokeKey(k.id, k.name)}
                            >
                              <Trash2 size={12} />
                              一键吊销
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* =================================================================== */}
      {/* Modals                                                              */}
      {/* =================================================================== */}

      {/* 1. Create External Guest Modal */}
      {showCreateGuestModal && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowCreateGuestModal(false); }}>
          <div style={modalBoxStyle(440)}>
            <div style={modalHeaderStyle}>
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>新建外部访客账户</h4>
              <button type="button" onClick={() => setShowCreateGuestModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <form onSubmit={handleCreateGuest} style={{ padding: 20 }}>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">用户名 (Username) *</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: consultant_bob"
                  value={guestForm.username}
                  onChange={(e) => setGuestForm({ ...guestForm, username: e.target.value })}
                  autoFocus
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">初始密码 (Password) *</label>
                <input
                  type="password"
                  className="ws-input"
                  placeholder="建议高强度密码"
                  value={guestForm.password}
                  onChange={(e) => setGuestForm({ ...guestForm, password: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">姓名 / 显示名</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: Bob Consultant"
                  value={guestForm.display_name}
                  onChange={(e) => setGuestForm({ ...guestForm, display_name: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">电子邮箱</label>
                <input
                  type="email"
                  className="ws-input"
                  placeholder="bob@external.com"
                  value={guestForm.email}
                  onChange={(e) => setGuestForm({ ...guestForm, email: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="ws-label">账户过期截止日期 (Expires At)</label>
                <input
                  type="datetime-local"
                  className="ws-input"
                  value={guestForm.expires_at}
                  onChange={(e) => setGuestForm({ ...guestForm, expires_at: e.target.value })}
                />
                <span style={{ fontSize: 11, color: 'var(--ws-text-muted)' }}>到期后系统将自动强制拒绝登录</span>
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
                <button type="button" className="ws-btn ws-btn--ghost" onClick={() => setShowCreateGuestModal(false)}>取消</button>
                <button type="submit" className="ws-btn ws-btn--primary">创建访客</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 2. Create Workspace Modal */}
      {showCreateWsModal && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowCreateWsModal(false); }}>
          <div style={modalBoxStyle(420)}>
            <div style={modalHeaderStyle}>
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>创建独立物理工作区</h4>
              <button type="button" onClick={() => setShowCreateWsModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <form onSubmit={handleCreateWorkspace} style={{ padding: 20 }}>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">工作区名称 *</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: 财务部专有图谱"
                  value={wsForm.name}
                  onChange={(e) => setWsForm({ ...wsForm, name: e.target.value })}
                  autoFocus
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">工作区唯一 ID (可选)</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: ws_finance"
                  value={wsForm.id}
                  onChange={(e) => setWsForm({ ...wsForm, id: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="ws-label">描述说明</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="该工作区专用于财务与合规审计数据"
                  value={wsForm.description}
                  onChange={(e) => setWsForm({ ...wsForm, description: e.target.value })}
                />
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
                <button type="button" className="ws-btn ws-btn--ghost" onClick={() => setShowCreateWsModal(false)}>取消</button>
                <button type="submit" className="ws-btn ws-btn--primary">创建工作区</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 3. Add Grant Modal */}
      {showAddGrantModal && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowAddGrantModal(false); }}>
          <div style={modalBoxStyle(440)}>
            <div style={modalHeaderStyle}>
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>添加工作区角色授予</h4>
              <button type="button" onClick={() => setShowAddGrantModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <form onSubmit={handleAddGrant} style={{ padding: 20 }}>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">目标工作区</label>
                <input type="text" className="ws-input" value={selectedWsId} disabled style={{ background: '#f5f5f5' }} />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">授权主体类型</label>
                <select
                  className="ws-input"
                  value={grantForm.grantee_type}
                  onChange={(e) => setGrantForm({ ...grantForm, grantee_type: e.target.value as any })}
                >
                  <option value="group">安全组 (Active Directory Group 或 Local Group)</option>
                  <option value="user">单个用户 (User ID 或 Username)</option>
                </select>
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">主体标识 (DN 或 名称) *</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder={grantForm.grantee_type === 'group' ? '如: CN=Finance-Team 或 Finance-Team' : '如: jdoe 或 usr_abc'}
                  value={grantForm.grantee_id}
                  onChange={(e) => setGrantForm({ ...grantForm, grantee_id: e.target.value })}
                  autoFocus
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="ws-label">分配角色 (Role)</label>
                <select
                  className="ws-input"
                  value={grantForm.role}
                  onChange={(e) => setGrantForm({ ...grantForm, role: e.target.value as any })}
                >
                  <option value="Viewer">Viewer (仅只读检索与浏览)</option>
                  <option value="Editor">Editor (读写、实体图谱更新)</option>
                  <option value="Admin">Admin (工作区完全管理与成员分配)</option>
                </select>
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
                <button type="button" className="ws-btn ws-btn--ghost" onClick={() => setShowAddGrantModal(false)}>取消</button>
                <button type="submit" className="ws-btn ws-btn--primary">确认授予</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 4. Create Group Modal */}
      {showCreateGroupModal && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowCreateGroupModal(false); }}>
          <div style={modalBoxStyle(420)}>
            <div style={modalHeaderStyle}>
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>新建本地安全组</h4>
              <button type="button" onClick={() => setShowCreateGroupModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <form onSubmit={handleCreateGroup} style={{ padding: 20 }}>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">组名称 *</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: AI-Core-Taskforce"
                  value={groupForm.name}
                  onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })}
                  autoFocus
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="ws-label">说明描述</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="临时跨部门协作工作组"
                  value={groupForm.description}
                  onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })}
                />
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
                <button type="button" className="ws-btn ws-btn--ghost" onClick={() => setShowCreateGroupModal(false)}>取消</button>
                <button type="submit" className="ws-btn ws-btn--primary">创建组</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 5. Group Members Modal */}
      {showGroupMembersModal && selectedGroup && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowGroupMembersModal(false); }}>
          <div style={modalBoxStyle(500)}>
            <div style={modalHeaderStyle}>
              <div>
                <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>成员管理: {selectedGroup.name}</h4>
                <span style={{ fontSize: 11, color: 'var(--ws-text-muted)' }}>管理该组关联的用户成员</span>
              </div>
              <button type="button" onClick={() => setShowGroupMembersModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <div style={{ padding: 20 }}>
              {/* Add member form */}
              <form onSubmit={handleAddGroupMember} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="输入要加入组的用户名 (如: alice 或 jdoe)"
                  value={newMemberUsername}
                  onChange={(e) => setNewMemberUsername(e.target.value)}
                  style={{ flex: 1 }}
                />
                <button type="submit" className="ws-btn ws-btn--primary" style={{ flexShrink: 0 }}>
                  添加成员
                </button>
              </form>

              {/* Members list */}
              <div style={{ maxHeight: 220, overflowY: 'auto', border: '1px solid var(--ws-border)', borderRadius: 8 }}>
                {groupMembers.length === 0 ? (
                  <div style={{ padding: 20, textAlign: 'center', color: 'var(--ws-text-muted)', fontSize: 12 }}>
                    该组暂无成员。在上方输入用户名以添加。
                  </div>
                ) : (
                  groupMembers.map((m) => (
                    <div
                      key={m.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '8px 12px',
                        borderBottom: '1px solid var(--ws-border)',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{m.username}</div>
                        <div style={{ fontSize: 11, color: 'var(--ws-text-muted)' }}>{m.email || m.id}</div>
                      </div>
                      <button
                        type="button"
                        className="ws-btn ws-btn--danger"
                        style={{ padding: '3px 8px', fontSize: 11 }}
                        onClick={() => handleRemoveGroupMember(m.id)}
                      >
                        移除
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 6. Create Service Account Key Modal */}
      {showCreateServiceKeyModal && (
        <div className="ws-modal-backdrop" style={modalBackdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setShowCreateServiceKeyModal(false); }}>
          <div style={modalBoxStyle(440)}>
            <div style={modalHeaderStyle}>
              <h4 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>配置服务账号 API 密钥</h4>
              <button type="button" onClick={() => setShowCreateServiceKeyModal(false)} style={closeBtnStyle}><X size={18} /></button>
            </div>
            <form onSubmit={handleCreateServiceKey} style={{ padding: 20 }}>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">服务账号名称 *</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="如: Data-Pipeline-Ingest-Worker"
                  value={serviceKeyForm.name}
                  onChange={(e) => setServiceKeyForm({ ...serviceKeyForm, name: e.target.value })}
                  autoFocus
                />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label className="ws-label">许可工作区 (以逗号分隔，或填 * 表示全部)</label>
                <input
                  type="text"
                  className="ws-input"
                  placeholder="* 或 ws_engineering, ws_finance"
                  value={serviceKeyForm.allowed_workspaces}
                  onChange={(e) => setServiceKeyForm({ ...serviceKeyForm, allowed_workspaces: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label className="ws-label">过期截止时间 (可选)</label>
                <input
                  type="datetime-local"
                  className="ws-input"
                  value={serviceKeyForm.expires_at}
                  onChange={(e) => setServiceKeyForm({ ...serviceKeyForm, expires_at: e.target.value })}
                />
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
                <button type="button" className="ws-btn ws-btn--ghost" onClick={() => setShowCreateServiceKeyModal(false)}>取消</button>
                <button type="submit" className="ws-btn ws-btn--primary">创建并生成凭证</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline Modal Styling Helpers
// ---------------------------------------------------------------------------
const modalBackdropStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0, 0, 0, 0.45)',
  backdropFilter: 'blur(3px)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 3000,
  padding: 16,
};

function modalBoxStyle(width: number): React.CSSProperties {
  return {
    width: '100%',
    maxWidth: width,
    background: '#ffffff',
    borderRadius: 12,
    boxShadow: '0 20px 45px rgba(0,0,0,0.2)',
    border: '1px solid var(--ws-border)',
    overflow: 'hidden',
    animation: 'scaleIn 140ms ease-out',
  };
}

const modalHeaderStyle: React.CSSProperties = {
  padding: '16px 20px',
  borderBottom: '1px solid var(--ws-border)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  background: 'linear-gradient(180deg, #fafafa 0%, #ffffff 100%)',
};

const closeBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--ws-text-muted)',
  padding: 4,
};
