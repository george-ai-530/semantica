/**
 * src/workspaces/LineageWorkspace/LineageDiagram.tsx
 */
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const THEME_CSS = `
  .react-flow { background: var(--ws-bg, #eeeeee); }
  .react-flow__node-group {
    background: rgba(0, 82, 217,0.04);
    border: 1px dashed rgba(0, 82, 217,0.18);
    border-radius: 10px;
  }
  .react-flow__node-default {
    background: rgba(255, 255, 255,0.92);
    color: var(--ws-text, rgba(0, 0, 0, 0.9));
    border: 1px solid rgba(0, 82, 217,0.22);
    border-radius: 8px;
    padding: 10px 12px;
    white-space: pre-wrap;
    font-size: 12px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  }
  .react-flow__controls { background: rgba(255, 255, 255,0.9); border: 1px solid rgba(0, 82, 217,0.18); border-radius: 10px; }
  .react-flow__controls-button { background: transparent; border-color: rgba(0, 82, 217,0.15); color: var(--ws-text-muted, rgba(0, 0, 0, 0.4)); }
  .react-flow__controls-button:hover { background: rgba(0, 82, 217,0.1); color: var(--ws-text, rgba(0, 0, 0, 0.9)); }
`;

export function LineageDiagram() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [searchId, setSearchId] = useState("");
  const [activeId, setActiveId] = useState("");
  const [error, setError] = useState("");

  const downloadReport = async (format: "json" | "markdown") => {
    if (!activeId) return;
    const response = await fetch(`/api/provenance/report?node_id=${encodeURIComponent(activeId)}&format=${format}`);
    if (!response.ok) {
      return;
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${activeId}_provenance.${format === "markdown" ? "md" : "json"}`;
    document.body.appendChild(anchor);
    anchor.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(anchor);
  };

  const [prevActiveId, setPrevActiveId] = useState(activeId);
  if (activeId !== prevActiveId) {
    setPrevActiveId(activeId);
    setError("");
    setNodes([]);
    setEdges([]);
  }

  useEffect(() => {
    let ignore = false;
    if (!activeId) return;

    const xLanes = [
      { id: "group_agent", type: "group", position: { x: 50, y: 50 }, style: { width: 800, height: 120 } },
      { id: "group_activity", type: "group", position: { x: 50, y: 200 }, style: { width: 800, height: 120 } },
      { id: "group_entity", type: "group", position: { x: 50, y: 350 }, style: { width: 800, height: 120 } }
    ];

    const fetchLineage = async () => {
      setError("");
      try {
        const res = await fetch("/api/provenance?node_id=" + encodeURIComponent(activeId));

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`HTTP ${res.status}：API 路由缺失或请求失败。${text.substring(0, 100)}`);
        }

        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("后端返回了非 JSON 响应（可能是 HTML 回退页面）。");
        }

        const data = await res.json();
        if (res.status === 207) {
          setError(data.message || "警告：加载溯源时仅部分成功。");
        }

        const counters: Record<string, number> = { "group_agent": 0, "group_activity": 0, "group_entity": 0 };

        const mappedNodes = data.nodes.map((n: any) => {
          const c = counters[n.parent_id] || 0;
          counters[n.parent_id] = c + 1;
          return {
            id: n.id,
            data: { label: n.label + "\n(" + n.prov_type + ")" },
            position: { x: 50 + c * 180, y: 30 },
            parentId: n.parent_id,
            extent: "parent",
            type: "default"
          };
        });

        const mappedEdges = data.edges.map((e: any) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          animated: true,
          style: { stroke: "#0052d9" }
        }));

        if (!ignore) {
          setNodes([...xLanes, ...mappedNodes]);
          setEdges(mappedEdges);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载溯源失败。");
      }
    };
    void fetchLineage();
    return () => { ignore = true; };
  }, [activeId]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "var(--ws-bg, #eeeeee)" }}>
      <style>{THEME_CSS}</style>

      {/* Toolbar */}
      <div style={{ position: "absolute", top: 14, left: 14, right: 14, zIndex: 10, display: "flex", gap: 8, alignItems: "center", background: "rgba(255, 255, 255,0.88)", backdropFilter: "blur(14px)", padding: "8px 12px", borderRadius: 12, border: "1px solid rgba(0, 82, 217,0.16)", boxShadow: "0 4px 20px rgba(0,0,0,0.15)" }}>
        <span className="ws-eyebrow" style={{ color: "var(--ws-accent, #0052d9)", marginRight: 4 }}>PROV-O 溯源</span>
        <input
          className="ws-input"
          type="text"
          placeholder="输入节点 ID…"
          value={searchId}
          onChange={(e) => setSearchId(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") setActiveId(searchId); }}
          style={{ width: 200, padding: "6px 10px", fontSize: 12 }}
        />
        <button className="ws-btn ws-btn--primary" style={{ padding: "6px 12px" }} onClick={() => setActiveId(searchId)}>
          追踪
        </button>
        <div style={{ flex: 1 }} />
        <button className="ws-btn ws-btn--ghost" style={{ padding: "6px 12px", fontSize: 11 }} disabled={!activeId} onClick={() => void downloadReport("json")}>
          导出 JSON
        </button>
        <button className="ws-btn ws-btn--ghost" style={{ padding: "6px 12px", fontSize: 11 }} disabled={!activeId} onClick={() => void downloadReport("markdown")}>
          导出 MD
        </button>
      </div>

      {error ? (
        <div style={{ position: "absolute", top: 60, left: 14, right: 14, zIndex: 10, padding: 12, borderRadius: 14, color: "#d54941", background: "rgba(213, 73, 65,0.1)", border: "1px solid rgba(213, 73, 65,0.18)" }}>
          {error}
        </div>
      ) : null}

      {activeId ? (
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background color="rgba(0, 82, 217,0.08)" gap={24} />
          <Controls />
        </ReactFlow>
      ) : (
        <div className="ws-empty" style={{ height: "100%", paddingTop: 72 }}>
          <div className="ws-empty-icon"><Link2 size={36} color="var(--ws-accent)" /></div>
          <div className="ws-empty-title">PROV-O 溯源查看器</div>
          <div className="ws-empty-body">在上方工具栏输入节点 ID 并点击“追踪”，即可查看其 W3C PROV-O 溯源图。</div>
        </div>
      )}
    </div>
  );
}
