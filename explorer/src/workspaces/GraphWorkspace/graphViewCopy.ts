import type { FocusedUnavailableReason, GroupedViewUnavailableReason } from "./types";

const GROUPED_VIEW_COPY = {
  "communities-undetected": "在检测到社区之前，分组视图不可用。",
  "community-nodes-missing": "由于无法创建任何社区节点，分组视图不可用。",
} as const;

const FOCUSED_MODE_COPY = {
  "no-selection": "请选择一个节点以在聚焦模式下检查。",
  "grouped-unresolvable": "聚焦模式对此分组所选项目不可用。",
  "not-in-graph": "所选项目在当前图谱中不可用。",
} as const;

export function groupedViewReasonText(
  reason: GroupedViewUnavailableReason | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }

  switch (reason.code) {
    case "communities-undetected":
      return GROUPED_VIEW_COPY["communities-undetected"];
    case "community-nodes-missing":
      return GROUPED_VIEW_COPY["community-nodes-missing"];
    case "invalid-community-layout":
      return `分组节点 ${reason.nodeId} 的坐标无效。`;
    case "missing-grouped-node":
      return `分组边 ${reason.edgeId} 引用了缺失的分组节点。`;
  }
}

export function focusedUnavailableReasonText(
  reason: FocusedUnavailableReason | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }

  return FOCUSED_MODE_COPY[reason.code];
}
