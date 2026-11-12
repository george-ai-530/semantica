import assert from "node:assert/strict";
import test from "node:test";

import {
  focusedUnavailableReasonText,
  groupedViewReasonText,
} from "../src/workspaces/GraphWorkspace/graphViewCopy.ts";

test("groupedViewReasonText owns grouped-view copy for every reason code", () => {
  assert.equal(
    groupedViewReasonText({ code: "communities-undetected" }),
    "在检测到社区之前，分组视图不可用。",
  );
  assert.equal(
    groupedViewReasonText({ code: "community-nodes-missing" }),
    "由于无法创建任何社区节点，分组视图不可用。",
  );
  assert.equal(
    groupedViewReasonText({ code: "invalid-community-layout", nodeId: "community-a" }),
    "分组节点 community-a 的坐标无效。",
  );
  assert.equal(
    groupedViewReasonText({ code: "missing-grouped-node", edgeId: "edge-1" }),
    "分组边 edge-1 引用了缺失的分组节点。",
  );
  assert.equal(groupedViewReasonText(null), null);
});

test("focusedUnavailableReasonText owns focused-mode copy for every reason code", () => {
  assert.equal(
    focusedUnavailableReasonText({ code: "no-selection" }),
    "请选择一个节点以在聚焦模式下检查。",
  );
  assert.equal(
    focusedUnavailableReasonText({ code: "grouped-unresolvable" }),
    "聚焦模式对此分组所选项目不可用。",
  );
  assert.equal(
    focusedUnavailableReasonText({ code: "not-in-graph" }),
    "所选项目在当前图谱中不可用。",
  );
  assert.equal(focusedUnavailableReasonText(null), null);
});
