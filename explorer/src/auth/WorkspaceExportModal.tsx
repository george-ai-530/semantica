/**
 * Workspace Export Modal Component.
 *
 * Allows users to export the active workspace graph in multiple formats:
 *   - JSON (Graphology / Semantica format with complete attributes)
 *   - CSV (Nodes and edges tabular format for Excel / analysis)
 *   - GraphML (Standard XML graph exchange for Gephi / Cytoscape)
 *   - Turtle (W3C RDF TTL syntax for semantic web & reasoning)
 */

import { useState } from 'react';
import {
  Download,
  Layers,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { useAuth } from './authStore';

export interface WorkspaceExportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export type ExportFormat = 'json' | 'csv' | 'graphml' | 'turtle';

const FORMAT_OPTIONS: Array<{
  id: ExportFormat;
  label: string;
  ext: string;
  description: string;
  mime: string;
}> = [
  {
    id: 'json',
    label: 'JSON 快照',
    ext: 'json',
    description: 'Graphology / Semantica 原生结构，保留完整节点、边、属性及元数据',
    mime: 'application/json',
  },
  {
    id: 'csv',
    label: 'CSV 实体与边表',
    ext: 'csv',
    description: '标准逗号分隔值表格，适配 Microsoft Excel、Pandas 与数据报表处理',
    mime: 'text/csv',
  },
  {
    id: 'graphml',
    label: 'GraphML (XML)',
    ext: 'graphml',
    description: '标准图结构 XML 交换协议，适配 Gephi、Cytoscape、yEd 及 Neo4j 导入',
    mime: 'application/xml',
  },
  {
    id: 'turtle',
    label: 'Turtle (RDF TTL)',
    ext: 'ttl',
    description: 'W3C 语义网标准三元组格式，适配本体推理、SPARQL 与图数据库',
    mime: 'text/turtle',
  },
];

export function WorkspaceExportModal({ isOpen, onClose }: WorkspaceExportModalProps) {
  const { activeWorkspace, workspaces, user } = useAuth();
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('json');
  const [isExporting, setIsExporting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const currentWs = workspaces.find((w) => w.id === activeWorkspace) || {
    id: activeWorkspace,
    name: activeWorkspace === 'default' ? '默认工作区' : activeWorkspace,
    role: user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer'),
  };

  const role = currentWs.role || user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer');

  async function handleExport() {
    setIsExporting(true);
    setStatusMessage(null);
    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Workspace-ID': activeWorkspace,
        },
        body: JSON.stringify({ format: selectedFormat }),
      });

      if (!res.ok) {
        let errorDetail = '导出请求失败';
        try {
          const errData = await res.json();
          errorDetail = errData.detail || errorDetail;
        } catch {
          // ignore
        }
        throw new Error(errorDetail);
      }

      const blob = await res.blob();
      const formatOpt = FORMAT_OPTIONS.find((f) => f.id === selectedFormat) || FORMAT_OPTIONS[0];
      const filename = `${activeWorkspace}_graph_export_${new Date().toISOString().slice(0, 10)}.${formatOpt.ext}`;

      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);

      setStatusMessage({
        type: 'success',
        text: `已成功导出并下载：${filename}`,
      });
      setTimeout(() => {
        onClose();
        setStatusMessage(null);
      }, 1500);
    } catch (err: unknown) {
      setStatusMessage({
        type: 'error',
        text: err instanceof Error ? err.message : '导出失败，请检查网络或后端状态。',
      });
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.45)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
        animation: 'fadeIn 120ms ease',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !isExporting) onClose();
      }}
    >
      <div
        className="ws-card"
        style={{
          width: 500,
          maxWidth: '92vw',
          background: '#ffffff',
          borderRadius: 14,
          boxShadow: '0 20px 48px rgba(0, 0, 0, 0.2)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--ws-border)',
            background: 'rgba(0, 0, 0, 0.015)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: 'var(--ws-purple-soft)',
                color: 'var(--ws-purple)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Download size={18} />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ws-text)' }}>
                导出当前工作区数据
              </div>
              <div style={{ fontSize: 11, color: 'var(--ws-text-muted)' }}>
                生成该物理工作区图谱拓扑与属性快照
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isExporting}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--ws-text-muted)',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Active Workspace Info Banner */}
          <div
            style={{
              padding: '10px 14px',
              borderRadius: 8,
              background: 'var(--ws-accent-soft)',
              border: '1px solid rgba(0, 82, 217, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Layers size={16} style={{ color: 'var(--ws-accent)' }} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ws-text)' }}>
                  {currentWs.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--ws-text-muted)', fontFamily: 'monospace' }}>
                  ID: {activeWorkspace}
                </div>
              </div>
            </div>
            <span
              className={`ws-pill ${
                role === 'Admin'
                  ? 'ws-pill--purple'
                  : role === 'Editor'
                  ? 'ws-pill--green'
                  : 'ws-pill--mono'
              }`}
              style={{ fontSize: 11, padding: '2px 8px' }}
            >
              {role}
            </span>
          </div>

          {/* Format Selection */}
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 700, color: 'var(--ws-text)', marginBottom: 8 }}>
              选择导出格式
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {FORMAT_OPTIONS.map((opt) => {
                const isSelected = selectedFormat === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setSelectedFormat(opt.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 12,
                      padding: '10px 12px',
                      borderRadius: 8,
                      border: `1.5px solid ${isSelected ? 'var(--ws-accent)' : 'var(--ws-border)'}`,
                      background: isSelected ? 'var(--ws-accent-soft)' : '#ffffff',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 120ms ease',
                    }}
                  >
                    <div
                      style={{
                        marginTop: 2,
                        width: 16,
                        height: 16,
                        borderRadius: '50%',
                        border: `2px solid ${isSelected ? 'var(--ws-accent)' : 'var(--ws-border)'}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}
                    >
                      {isSelected && (
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--ws-accent)' }} />
                      )}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ws-text)' }}>
                          {opt.label}
                        </span>
                        <span className="ws-pill ws-pill--mono" style={{ fontSize: 10, padding: '1px 5px' }}>
                          .{opt.ext}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--ws-text-muted)', marginTop: 2 }}>
                        {opt.description}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Status Message */}
          {statusMessage && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                borderRadius: 8,
                background: statusMessage.type === 'success' ? 'rgba(43, 164, 113, 0.1)' : 'rgba(213, 73, 65, 0.1)',
                color: statusMessage.type === 'success' ? '#1c744f' : '#b7271e',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {statusMessage.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              <span>{statusMessage.text}</span>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: 10,
            padding: '14px 20px',
            borderTop: '1px solid var(--ws-border)',
            background: 'rgba(0, 0, 0, 0.015)',
          }}
        >
          <button
            type="button"
            className="ws-btn ws-btn--secondary"
            onClick={onClose}
            disabled={isExporting}
            style={{ padding: '7px 14px', fontSize: 13 }}
          >
            取消
          </button>
          <button
            type="button"
            className="ws-btn ws-btn--primary"
            onClick={handleExport}
            disabled={isExporting}
            style={{ padding: '7px 16px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}
          >
            {isExporting ? (
              <>
                <Loader2 size={15} className="ws-spin" />
                <span>正在生成导出包…</span>
              </>
            ) : (
              <>
                <Download size={15} />
                <span>立即下载导出文件</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
