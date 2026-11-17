export type ExploreView = 'graph' | 'memories' | 'vocabulary' | 'federated';

type ExploreWorkspaceTabsProps = {
  activeView: ExploreView;
  agentMemoryAvailable: boolean;
  onSelect: (view: ExploreView) => void;
};

export function ExploreWorkspaceTabs({
  activeView,
  agentMemoryAvailable,
  onSelect,
}: ExploreWorkspaceTabsProps) {
  return (
    <>
      <button className="workspace-tab" data-active={activeView === 'graph'} onClick={() => onSelect('graph')}>
        COWIN 图谱
      </button>
      <button className="workspace-tab" data-active={activeView === 'federated'} onClick={() => onSelect('federated')}>
        知识联邦检索
      </button>
      {agentMemoryAvailable ? (
        <button className="workspace-tab" data-active={activeView === 'memories'} onClick={() => onSelect('memories')}>
          记忆
        </button>
      ) : null}
      <button className="workspace-tab" data-active={activeView === 'vocabulary'} onClick={() => onSelect('vocabulary')}>
        词汇浏览
      </button>
    </>
  );
}
