import type { CSSProperties } from "react";

import type { GraphPlugin } from "./types";

const TEMPORAL_PANEL_ID = "temporal-panel";

function formatTemporalLabel(value: Date | null) {
  if (!value) {
    return "未选择时间";
  }
  return `${value.getFullYear()}/${String(value.getMonth() + 1).padStart(2, "0")}`;
}

export const temporalOverlayPlugin: GraphPlugin = {
  id: "temporal-overlay",
  mount: () => {},
  unmount: () => {},
  onStateChange: () => {},
  toolbarItems: (context) => [
    {
      id: "temporal-toggle",
      label: "时间",
      title: "切换时间上下文面板",
      active: context.isPanelOpen(TEMPORAL_PANEL_ID),
      order: 40,
      onClick: () => context.dispatchAction({ type: "togglePanel", panelId: TEMPORAL_PANEL_ID }),
    },
  ],
  renderOverlay: (context) => {
    const temporal = context.getTemporalState();
    if (!temporal?.currentTime) {
      return null;
    }

    const label = formatTemporalLabel(temporal.currentTime);
    return {
      id: "temporal-overlay-chip",
      layer: 1,
      order: 10,
      element: (
        <div
          style={{
            position: "absolute",
            left: 140,
            bottom: 26,
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 12px",
            borderRadius: 999,
            border: "1px solid rgba(54, 110, 244, 0.18)",
            background: "linear-gradient(135deg, rgba(6, 15, 27, 0.88), rgba(11, 22, 39, 0.76))",
            boxShadow: "0 12px 30px rgba(0, 0, 0, 0.28)",
            color: "rgba(0, 0, 0, 0.9)",
            fontSize: 11,
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            pointerEvents: "none",
          }}
        >
          <span style={{ color: "#366ef4", fontWeight: 700 }}>时间</span>
          <span>{label}</span>
          {typeof temporal.activeNodeCount === "number" ? (
            <span style={{ color: "rgba(0, 0, 0, 0.6)" }}>{temporal.activeNodeCount.toLocaleString()} 个活跃</span>
          ) : null}
        </div>
      ),
    };
  },
  renderPanel: (context) => {
    if (!context.isPanelOpen(TEMPORAL_PANEL_ID)) {
      return null;
    }

    const temporal = context.getTemporalState();
    return {
      id: TEMPORAL_PANEL_ID,
      title: "时间上下文",
      placement: "bottom",
      order: 30,
      defaultOpen: false,
      preferredWidth: 320,
      preferredHeight: 220,
      content: (
        <div style={panelBodyStyle}>
          <div style={panelEyebrowStyle}>当前滑块状态</div>
          <div style={detailRowStyle}>
            <span style={detailLabelStyle}>当前</span>
            <span style={detailValueStyle}>{formatTemporalLabel(temporal?.currentTime ?? null)}</span>
          </div>
          <div style={detailRowStyle}>
            <span style={detailLabelStyle}>范围</span>
            <span style={detailValueStyle}>
              {(temporal?.minDate ?? "1970")} → {(temporal?.maxDate ?? "now")}
            </span>
          </div>
          <div style={detailRowStyle}>
            <span style={detailLabelStyle}>活跃节点</span>
            <span style={detailValueStyle}>
              {typeof temporal?.activeNodeCount === "number" ? temporal.activeNodeCount.toLocaleString() : "全部"}
            </span>
          </div>
        </div>
      ),
    };
  },
};

const panelBodyStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const panelEyebrowStyle: CSSProperties = {
  color: "rgba(0, 0, 0, 0.6)",
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const detailRowStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 16,
  padding: "8px 10px",
  borderRadius: 12,
  border: "1px solid rgba(0, 0, 0, 0.06)",
  background: "rgba(0, 0, 0, 0.025)",
};

const detailLabelStyle: CSSProperties = {
  color: "rgba(0, 0, 0, 0.6)",
  fontSize: 12,
};

const detailValueStyle: CSSProperties = {
  color: "rgba(0, 0, 0, 0.9)",
  fontSize: 12,
  fontWeight: 600,
};
