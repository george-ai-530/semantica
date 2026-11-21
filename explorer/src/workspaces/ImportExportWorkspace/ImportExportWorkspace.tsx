import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { UploadCloud, Download, FileJson, FileText, CheckCircle2, AlertCircle, Loader2, Layers, Network, FileCode } from "lucide-react";
import { logEvent } from "../../store/registryStore";
import { useAuth } from "../../auth/authStore";

interface Toast { id: number; type: "success" | "error"; text: string }
type SupportedExportFormat = "json" | "csv" | "graphml" | "turtle";

export function ImportExportWorkspace() {
  const { activeWorkspace, workspaces, user } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [exportFormat, setExportFormat] = useState<SupportedExportFormat>("json");
  const [isExporting, setIsExporting] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const currentWs = workspaces.find((w) => w.id === activeWorkspace) || {
    id: activeWorkspace,
    name: activeWorkspace === 'default' ? '默认工作区' : activeWorkspace,
    role: user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer'),
  };
  const role = currentWs.role || user?.workspace_roles?.[activeWorkspace] || (user?.global_role === 'admin' ? 'Admin' : 'Viewer');

  function showToast(type: Toast["type"], text: string) {
    const id = Date.now();
    setToasts((p) => [...p, { id, type, text }]);
    setTimeout(() => setToasts((p) => p.filter((t) => t.id !== id)), 5000);
  }

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted.length > 0) setFile(accepted[0]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/json": [".json"], "text/csv": [".csv"] },
    maxFiles: 1,
  });

  async function handleImport() {
    if (!file) return;
    setIsUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/import", {
        method: "POST",
        headers: {
          "X-Workspace-ID": activeWorkspace,
        },
        body: fd,
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "导入失败"); }
      const data = await res.json();
      const nodeCount = data.nodes_imported ?? data.nodes_added ?? 0;
      const edgeCount = data.edges_imported ?? data.edges_added ?? 0;
      showToast("success", `已向 [${currentWs.name}] 导入 ${nodeCount} 个节点 · ${edgeCount} 条边`);
      logEvent("import", `已从 ${file.name} 向 ${activeWorkspace} 导入 ${nodeCount} 个节点 · ${edgeCount} 条边`, { file: file.name, workspace: activeWorkspace });
      setFile(null);
    } catch (e: unknown) {
      showToast("error", e instanceof Error ? e.message : "导入失败");
    } finally { setIsUploading(false); }
  }

  async function handleExport() {
    setIsExporting(true);
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-ID": activeWorkspace,
        },
        body: JSON.stringify({ format: exportFormat }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "导出失败"); }
      const blob = await res.blob();
      const extMap: Record<SupportedExportFormat, string> = {
        json: "json",
        csv: "csv",
        graphml: "graphml",
        turtle: "ttl",
      };
      const ext = extMap[exportFormat] || exportFormat;
      const filename = `${activeWorkspace}_export_${new Date().toISOString().slice(0, 10)}.${ext}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("success", `导出就绪 — ${filename}`);
      logEvent("export", `已将工作区 ${activeWorkspace} 导出为 ${exportFormat.toUpperCase()}`, { format: exportFormat, workspace: activeWorkspace });
    } catch (e: unknown) {
      showToast("error", e instanceof Error ? e.message : "导出失败");
    } finally { setIsExporting(false); }
  }

  return (
    <div className="ws-page ws-scroll">
      <div className="ws-padded" style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 980, margin: "0 auto", width: "100%" }}>
        {/* Page header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ width: 42, height: 42, borderRadius: 13, background: "var(--ws-accent-soft)", border: "1px solid var(--ws-border-strong)", display: "grid", placeItems: "center", color: "var(--ws-accent)", flexShrink: 0 }}>
              <UploadCloud size={20} />
            </div>
            <div>
              <h2 className="ws-title" style={{ fontSize: 18 }}>导入与导出</h2>
              <div className="ws-body" style={{ marginTop: 2 }}>管理当前工作区的数据集导入与多格式图谱快照导出。</div>
            </div>
          </div>

          {/* Active Workspace Pill */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              borderRadius: 8,
              background: "#ffffff",
              border: "1px solid var(--ws-border)",
              boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
            }}
          >
            <Layers size={14} style={{ color: "var(--ws-accent)" }} />
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--ws-text)" }}>
              {currentWs.name}
            </div>
            <span
              className={`ws-pill ${
                role === "Admin"
                  ? "ws-pill--purple"
                  : role === "Editor"
                  ? "ws-pill--green"
                  : "ws-pill--mono"
              }`}
              style={{ fontSize: 10, padding: "1px 6px" }}
            >
              {role}
            </span>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
          {/* ── Import card ── */}
          <div className="ws-card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <UploadCloud size={16} color="var(--ws-accent)" />
                <div style={{ color: "var(--ws-text)", fontWeight: 700, fontSize: 14 }}>导入实体与关系</div>
              </div>
              <span className="ws-pill ws-pill--mono" style={{ fontSize: 10, padding: "1px 6px" }}>
                目标: {activeWorkspace}
              </span>
            </div>

            {/* Dropzone */}
            <div
              {...getRootProps()}
              style={{
                border: `2px dashed ${isDragActive ? "var(--ws-accent)" : "var(--ws-border)"}`,
                borderRadius: "var(--ws-radius)",
                background: isDragActive ? "var(--ws-accent-soft)" : "rgba(0,0,0,0.04)",
                padding: 32,
                textAlign: "center",
                cursor: "pointer",
                transition: "all 200ms ease",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 10,
              }}
            >
              <input {...getInputProps()} />
              {file ? (
                <>
                  {file.name.endsWith(".json") ? <FileJson size={40} color="#2ba471" /> : <FileText size={40} color="#2ba471" />}
                  <div style={{ color: "var(--ws-text)", fontWeight: 700 }}>{file.name}</div>
                  <div className="ws-body" style={{ fontSize: 11 }}>{(file.size / 1024).toFixed(1)} KB — 点击可替换</div>
                </>
              ) : (
                <>
                  <UploadCloud size={36} color="var(--ws-accent)" style={{ opacity: 0.7 }} />
                  <div style={{ color: "var(--ws-text)", fontWeight: 600 }}>拖拽文件到此处，或点击选择</div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <div className="ws-pill ws-pill--mono">.json</div>
                    <span style={{ color: "var(--ws-text-dim)", fontSize: 11 }}>或</span>
                    <div className="ws-pill ws-pill--mono">.csv</div>
                  </div>
                </>
              )}
            </div>

            <button
              className="ws-btn ws-btn--primary"
              onClick={handleImport}
              disabled={!file || isUploading}
              style={{ width: "100%", justifyContent: "center" }}
            >
              {isUploading ? <><Loader2 size={15} className="ws-spin" />上传并写入中…</> : <><UploadCloud size={15} />上传并写入 {currentWs.name}</>}
            </button>
          </div>

          {/* ── Export card ── */}
          <div className="ws-card" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Download size={16} color="var(--ws-purple)" />
                <div style={{ color: "var(--ws-text)", fontWeight: 700, fontSize: 14 }}>导出工作区快照</div>
              </div>
              <span className="ws-pill ws-pill--purple" style={{ fontSize: 10, padding: "1px 6px" }}>
                源: {activeWorkspace}
              </span>
            </div>

            <div>
              <label className="ws-label" style={{ marginBottom: 6 }}>导出格式</label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {(
                  [
                    { id: "json", label: "JSON", icon: FileJson },
                    { id: "csv", label: "CSV", icon: FileText },
                    { id: "graphml", label: "GraphML", icon: Network },
                    { id: "turtle", label: "Turtle TTL", icon: FileCode },
                  ] as const
                ).map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    className={`ws-btn ${exportFormat === id ? "ws-btn--primary" : "ws-btn--ghost"}`}
                    style={{ justifyContent: "center", fontSize: 12, padding: "7px 10px" }}
                    onClick={() => setExportFormat(id)}
                  >
                    <Icon size={14} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div style={{ flex: 1, padding: "14px 16px", borderRadius: "var(--ws-radius-sm)", background: "rgba(0,0,0,0.04)", border: "1px solid var(--ws-border)" }}>
              <div style={{ color: "var(--ws-text-muted)", fontWeight: 700, fontSize: 12, marginBottom: 6 }}>格式特性说明</div>
              <div className="ws-body" style={{ fontSize: 12 }}>
                {exportFormat === "json"
                  ? "完整图谱快照：以标准化 JSON 格式包含所有节点属性、边权重、实体元数据及分组。"
                  : exportFormat === "csv"
                  ? "扁平化 CSV 表格：节点与边分行导出，最适合 Microsoft Excel / Pandas 统计分析。"
                  : exportFormat === "graphml"
                  ? "标准 XML 图交换协议：保留拓扑与结构，完美支持 Gephi、Cytoscape 及 Neo4j 导入。"
                  : "W3C RDF 语义三元组：Turtle 语法，适配本体治理、语义推理及 SPARQL 引擎。"}
              </div>
            </div>

            <button
              className="ws-btn"
              onClick={handleExport}
              disabled={isExporting}
              style={{ width: "100%", justifyContent: "center", background: "var(--ws-purple-soft)", borderColor: "rgba(123, 83, 216,0.3)", color: "#7b53d8" }}
            >
              {isExporting ? <><Loader2 size={15} className="ws-spin" />正在生成导出包…</> : <><Download size={15} />下载 {activeWorkspace} 导出文件</>}
            </button>
          </div>
        </div>
      </div>

      {/* Toasts */}
      <div style={{ position: "fixed", bottom: 28, right: 28, display: "flex", flexDirection: "column", gap: 10, zIndex: 1000 }}>
        {toasts.map((t) => (
          <div key={t.id} className="ws-animate-in" style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 18px", borderRadius: "var(--ws-radius-sm)", background: t.type === "success" ? "rgba(43, 164, 113, 0.10)" : "rgba(213, 73, 65, 0.08)", border: `1px solid ${t.type === "success" ? "rgba(43, 164, 113,0.4)" : "rgba(213, 73, 65,0.4)"}`, boxShadow: "0 8px 24px rgba(0,0,0,0.14)", backdropFilter: "blur(12px)" }}>
            {t.type === "success" ? <CheckCircle2 size={16} color="#2ba471" /> : <AlertCircle size={16} color="#d54941" />}
            <span style={{ color: "var(--ws-text)", fontSize: 13, fontWeight: 500 }}>{t.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
