/**
 * src/workspaces/EnrichWorkspace/RegistryTab.tsx
 *
 * Document Registry — a live, filterable chronological audit log of every
 * KG / Ontology mutation that occurred in this session.
 */
import { useState } from "react";
import { ClipboardList, Filter, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { useRegistry, clearRegistry, type RegistryEntryOp } from "../../store/registryStore";

const OP_META: Record<
  RegistryEntryOp,
  { label: string; color: string; bg: string; border: string }
> = {
  import:       { label: "导入",       color: "#0052d9", bg: "rgba(0, 82, 217,0.12)",  border: "rgba(0, 82, 217,0.28)" },
  export:       { label: "导出",       color: "rgba(0, 0, 0, 0.6)", bg: "rgba(0, 0, 0,0.08)", border: "rgba(0, 0, 0,0.18)" },
  merge:        { label: "合并",        color: "#e37318", bg: "rgba(227, 115, 24,0.12)", border: "rgba(227, 115, 24,0.28)" },
  "add-node":   { label: "添加节点",     color: "#2ba471", bg: "rgba(43, 164, 113,0.12)",  border: "rgba(43, 164, 113,0.28)" },
  "update-node": { label: "更新节点",  color: "#0052d9", bg: "rgba(0, 82, 217,0.10)", border: "rgba(0, 82, 217,0.24)" },
  "add-edge":   { label: "添加边",     color: "#2ba471", bg: "rgba(43, 164, 113,0.10)",  border: "rgba(43, 164, 113,0.22)" },
  delete:       { label: "删除",       color: "#d54941", bg: "rgba(213, 73, 65,0.12)", border: "rgba(213, 73, 65,0.28)" },
  infer:        { label: "推断",        color: "#5e3ab8", bg: "rgba(123, 83, 216,0.12)", border: "rgba(123, 83, 216,0.28)" },
  "vocab-import": { label: "词汇",      color: "#0052d9", bg: "rgba(0, 82, 217,0.12)", border: "rgba(0, 82, 217,0.28)" },
};

const ALL_OPS: (RegistryEntryOp | "all")[] = [
  "all", "import", "export", "merge", "add-node", "update-node", "add-edge", "infer", "delete", "vocab-import",
];

function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(date: Date): string {
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function EntryRow({ entry }: { entry: ReturnType<typeof useRegistry>[number] }) {
  const [expanded, setExpanded] = useState(false);
  const meta = OP_META[entry.op];
  const hasDetail = entry.detail && Object.keys(entry.detail).length > 0;

  return (
    <div style={entryCardStyle}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        {/* Op Badge */}
        <span
          style={{
            flexShrink: 0,
            display: "inline-block",
            padding: "3px 8px",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: "0.07em",
            color: meta.color,
            background: meta.bg,
            border: `1px solid ${meta.border}`,
            marginTop: 1,
          }}
        >
          {meta.label}
        </span>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: 13, fontWeight: 500, wordBreak: "break-word" }}>
            {entry.summary}
          </div>
          <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: 11, marginTop: 3 }}>
            {formatDate(entry.timestamp)} · {formatTimestamp(entry.timestamp)}
          </div>
        </div>

        {/* Expand toggle */}
        {hasDetail ? (
          <button
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "收起详情" : "展开详情"}
            style={expandBtnStyle}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : null}
      </div>

      {/* Expanded detail */}
      {expanded && hasDetail ? (
        <pre style={detailPreStyle}>
          {JSON.stringify(entry.detail, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function RegistryTab() {
  const entries = useRegistry();
  const [activeFilter, setActiveFilter] = useState<RegistryEntryOp | "all">("all");

  const filtered = activeFilter === "all"
    ? entries
    : entries.filter((e) => e.op === activeFilter);

  return (
    <div style={shellStyle}>
      {/* Header */}
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <ClipboardList size={18} color="#0052d9" />
          <div>
            <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: 16, fontWeight: 700 }}>文档注册表</div>
            <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: 12 }}>
              本次会话中所有知识图谱与本体变更的审计日志
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: 12 }}>
            {entries.length} 个事件
          </span>
          {entries.length > 0 ? (
            <button
              onClick={clearRegistry}
              title="清除所有事件"
              style={clearBtnStyle}
            >
              <Trash2 size={13} />
              <span>清除</span>
            </button>
          ) : null}
        </div>
      </div>

      {/* Filter pills */}
      <div style={filterBarStyle}>
        <Filter size={13} color="rgba(0, 0, 0, 0.6)" />
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {ALL_OPS.map((op) => {
            const isActive = op === activeFilter;
            const meta = op === "all" ? null : OP_META[op as RegistryEntryOp];
            return (
              <button
                key={op}
                onClick={() => setActiveFilter(op as typeof activeFilter)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                  border: isActive
                    ? `1px solid ${meta?.border ?? "rgba(54, 110, 244,0.35)"}`
                    : "1px solid rgba(0, 0, 0, 0.06)",
                  background: isActive
                    ? (meta?.bg ?? "rgba(0, 82, 217,0.14)")
                    : "transparent",
                  color: isActive
                    ? (meta?.color ?? "#0052d9")
                    : "rgba(0, 0, 0, 0.6)",
                  transition: "all 140ms ease",
                }}
              >
                {op === "all" ? "全部" : (meta?.label ?? op)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Feed */}
      <div style={feedStyle}>
        {filtered.length === 0 ? (
          <div style={emptyStateStyle}>
            <ClipboardList size={36} color="rgba(54, 110, 244,0.15)" />
            <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: 14, marginTop: 12, fontWeight: 500 }}>
              暂无事件记录
            </div>
            <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: 12, marginTop: 4, textAlign: "center", maxWidth: 300 }}>
              导入文件、运行推理或合并实体后，相关活动将显示在此处。
            </div>
          </div>
        ) : (
          filtered.map((entry) => <EntryRow key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  );
}

/* ─── styles ─────────────────────────────────────────────────────── */

const shellStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  width: "100%",
  height: "100%",
  background: "#eeeeee",
  overflow: "hidden",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "20px 24px 16px",
  borderBottom: "1px solid rgba(0, 82, 217,0.1)",
  flexShrink: 0,
};

const filterBarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "12px 24px",
  borderBottom: "1px solid rgba(0, 0, 0, 0.05)",
  flexShrink: 0,
};

const feedStyle: React.CSSProperties = {
  flex: 1,
  overflowY: "auto",
  padding: "16px 24px",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const entryCardStyle: React.CSSProperties = {
  padding: "12px 14px",
  borderRadius: 12,
  background: "linear-gradient(135deg, rgba(255, 255, 255,0.6), rgba(255, 255, 255,0.4))",
  border: "1px solid rgba(0, 0, 0, 0.06)",
  boxShadow: "inset 0 1px 0 rgba(0, 0, 0, 0.03)",
};

const expandBtnStyle: React.CSSProperties = {
  flexShrink: 0,
  background: "transparent",
  border: "none",
  color: "rgba(0, 0, 0, 0.6)",
  cursor: "pointer",
  padding: 4,
  borderRadius: 6,
  display: "flex",
  alignItems: "center",
};

const detailPreStyle: React.CSSProperties = {
  marginTop: 10,
  padding: "10px 12px",
  borderRadius: 8,
  background: "rgba(0,0,0,0.045)",
  border: "1px solid rgba(0, 0, 0, 0.06)",
  color: "#0052d9",
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
};

const clearBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "5px 10px",
  borderRadius: 8,
  border: "1px solid rgba(213, 73, 65,0.22)",
  background: "rgba(213, 73, 65,0.06)",
  color: "#d54941",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

const emptyStateStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  padding: 40,
  minHeight: 280,
};
