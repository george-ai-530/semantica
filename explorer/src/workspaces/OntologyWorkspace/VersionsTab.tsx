import { useCallback, useEffect, useState } from "react";
import {
  Layers,
  GitMerge,
  Clock,
  FileText,
  CheckCircle,
  XCircle,
  AlertCircle,
  Send,
  X,
  ArrowRight,
  Scale,
} from "lucide-react";

interface VersionEntry {
  version_id: string;
  ontology_uri: string;
  state: "draft" | "published";
  author: string;
  date: string;
  diff_summary: Record<string, any>;
}

interface Proposal {
  proposal_id: string;
  draft_id: string;
  ontology_uri: string;
  summary: string;
  author: string;
  reviewer: string | null;
  state: "draft" | "proposed" | "approved" | "published" | "rejected";
  impact_analysis: Record<string, any>;
  shacl_validation: Record<string, any>;
  created_at: string;
  updated_at: string;
  comments: Record<string, any>[];
}

export function VersionsTab() {
  const [ontologyUri, setOntologyUri] = useState<string>("");
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [showProposalModal, setShowProposalModal] = useState(false);
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [comparePair, setComparePair] = useState<{ v1: string; v2: string } | null>(null);
  const [compareResult, setCompareResult] = useState<Record<string, any> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const loadVersions = useCallback(async () => {
    if (!ontologyUri) return;
    setError("");
    try {
      const response = await fetch(`/api/ontology/versions/${encodeURIComponent(ontologyUri)}`);
      if (response.ok) {
        const data = await response.json();
        setVersions(data);
        if (response.status === 207) setError(data.message || "警告：加载版本部分成功。");
      } else {
        setError(`加载版本失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载版本失败。");
    }
  }, [ontologyUri]);

  const loadProposals = useCallback(async () => {
    setError("");
    try {
      const response = await fetch("/api/ontology/proposals");
      if (response.ok) {
        const data = await response.json();
        setProposals(data);
        if (response.status === 207) setError(data.message || "警告：加载提案部分成功。");
      } else {
        setError(`加载提案失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载提案失败。");
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    async function fetchInitial() {
      if (!ignore) setError("");
      try {
        const propRes = await fetch("/api/ontology/proposals");
        if (propRes.ok) {
          const propData = await propRes.json();
          if (!ignore) {
            setProposals(propData);
            if (propRes.status === 207) setError(propData.message || "警告：加载提案部分成功。");
          }
        } else if (!ignore) {
          setError(`加载提案失败 (${propRes.status})`);
        }
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "加载提案失败。");
      }

      if (!ontologyUri) return;
      try {
        const verRes = await fetch(`/api/ontology/versions/${encodeURIComponent(ontologyUri)}`);
        if (verRes.ok) {
          const verData = await verRes.json();
          if (!ignore) {
            setVersions(verData);
            if (verRes.status === 207) setError(verData.message || "警告：加载版本部分成功。");
          }
        } else if (!ignore) {
          setError((prev) => prev || `加载版本失败 (${verRes.status})`);
        }
      } catch (err) {
        if (!ignore) setError((prev) => prev || (err instanceof Error ? err.message : "加载版本失败。"));
      }
    }
    void fetchInitial();
    return () => { ignore = true; };
  }, [ontologyUri]);

  const approveProposal = useCallback(async (proposalId: string) => {
    setError("");
    try {
      const response = await fetch(`/api/ontology/proposals/${proposalId}/approve`, {
        method: "POST",
      });
      if (response.ok) {
        if (response.status === 207) {
          const data = await response.json().catch(() => ({}));
          setError(data.message || "警告：批准提案部分成功。");
        } else {
          alert("提案已批准");
        }
        loadProposals();
      } else {
        setError(`批准提案失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "批准提案失败。");
    }
  }, [loadProposals]);

  const rejectProposal = useCallback(async (proposalId: string) => {
    setError("");
    try {
      const response = await fetch(`/api/ontology/proposals/${proposalId}/reject`, {
        method: "POST",
      });
      if (response.ok) {
        if (response.status === 207) {
          const data = await response.json().catch(() => ({}));
          setError(data.message || "警告：拒绝提案部分成功。");
        } else {
          alert("提案已拒绝");
        }
        loadProposals();
      } else {
        setError(`拒绝提案失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "拒绝提案失败。");
    }
  }, [loadProposals]);

  const publishProposal = useCallback(async (proposalId: string) => {
    setError("");
    try {
      const response = await fetch(`/api/ontology/proposals/${proposalId}/publish`, {
        method: "POST",
      });
      if (response.ok) {
        if (response.status === 207) {
          const data = await response.json().catch(() => ({}));
          setError(data.message || "警告：发布提案部分成功。");
        } else {
          alert("提案已发布");
        }
        loadProposals();
        loadVersions();
      } else {
        setError(`发布提案失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布提案失败。");
    }
  }, [loadProposals, loadVersions]);

  const runVersionComparison = useCallback(async () => {
    if (!comparePair || !ontologyUri) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/ontology/versions/${encodeURIComponent(ontologyUri)}/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version1: comparePair.v1,
          version2: comparePair.v2,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        if (response.status === 207) setError(data.message || "警告：对比版本部分成功。");
        setCompareResult(data);
      } else {
        setError(`对比版本失败 (${response.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "对比版本失败。");
    } finally {
      setIsLoading(false);
    }
  }, [comparePair, ontologyUri]);

  const getStateIcon = (state: string) => {
    switch (state) {
      case "published":
        return <CheckCircle size={16} color="#2ba471" />;
      case "approved":
        return <CheckCircle size={16} color="#0052d9" />;
      case "rejected":
        return <XCircle size={16} color="#d54941" />;
      case "proposed":
        return <AlertCircle size={16} color="#e37318" />;
      default:
        return <Clock size={16} color="rgba(0, 0, 0, 0.6)" />;
    }
  };

  const containerStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    background: "#eeeeee",
    padding: "20px",
    overflow: "auto",
  };

  const headerStyle: React.CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "20px",
  };

  const titleStyle: React.CSSProperties = {
    margin: 0,
    color: "rgba(0, 0, 0, 0.9)",
    fontSize: "20px",
    fontWeight: "700",
  };

  const sectionStyle: React.CSSProperties = {
    marginBottom: "24px",
  };

  const sectionTitleStyle: React.CSSProperties = {
    margin: "0 0 12px",
    color: "rgba(0, 0, 0, 0.9)",
    fontSize: "14px",
    fontWeight: "600",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  };

  const listStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  };

  const itemStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "12px 16px",
    borderRadius: "8px",
    background: "rgba(255, 255, 255, 0.8)",
    border: "1px solid rgba(54, 110, 244, 0.12)",
    transition: "160ms ease",
  };

  const modalOverlayStyle: React.CSSProperties = {
    position: "fixed",
    inset: 0,
    background: "rgba(0, 0, 0, 0.7)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  };

  const modalStyle: React.CSSProperties = {
    background: "rgba(255, 255, 255, 0.95)",
    border: "1px solid rgba(54, 110, 244, 0.2)",
    borderRadius: "12px",
    padding: "24px",
    minWidth: "480px",
    maxWidth: "640px",
    maxHeight: "80vh",
    overflow: "auto",
    backdropFilter: "blur(18px)",
  };

  const buttonStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    padding: "8px 14px",
    borderRadius: "6px",
    border: "1px solid rgba(54, 110, 244, 0.2)",
    background: "rgba(0, 82, 217, 0.1)",
    color: "rgba(0, 0, 0, 0.9)",
    fontSize: "12px",
    fontWeight: "600",
    cursor: "pointer",
    transition: "160ms ease",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: "6px",
    border: "1px solid rgba(54, 110, 244, 0.2)",
    background: "rgba(255, 255, 255, 0.8)",
    color: "rgba(0, 0, 0, 0.9)",
    fontSize: "13px",
    marginBottom: "12px",
  };

  const errorStyle: React.CSSProperties = { padding: "12px", borderRadius: "14px", color: "#d54941", background: "rgba(213, 73, 65,0.1)", border: "1px solid rgba(213, 73, 65,0.18)", marginBottom: "16px" };

  return (
    <div style={containerStyle}>
      <div style={headerStyle}>
        <h1 style={titleStyle}>版本与变更提案</h1>
        <input
          type="text"
          placeholder="本体 URI"
          value={ontologyUri}
          onChange={(e) => setOntologyUri(e.target.value)}
          style={{ ...inputStyle, width: "300px", marginBottom: 0 }}
        />
      </div>

      {error ? <div style={errorStyle}>{error}</div> : null}

      <div style={sectionStyle}>
        <h2 style={sectionTitleStyle}>
          <Layers size={16} />
          版本历史
        </h2>
        <div style={listStyle}>
          {versions.length === 0 ? (
            <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: "13px" }}>未找到版本</div>
          ) : (
            versions.map((version) => (
              <div key={version.version_id} style={itemStyle}>
                {getStateIcon(version.state)}
                <div style={{ flex: 1 }}>
                  <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: "13px", fontWeight: "600" }}>
                    {version.version_id}
                  </div>
                  <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: "11px" }}>
                    {version.author} • {new Date(version.date).toLocaleDateString()}
                  </div>
                </div>
                <button
                  style={buttonStyle}
                  onClick={() => {
                    setComparePair({ v1: version.version_id, v2: versions[0]?.version_id || "" });
                    setShowCompareModal(true);
                  }}
                >
                  <ArrowRight size={12} />
                  对比
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div style={sectionStyle}>
        <h2 style={sectionTitleStyle}>
          <GitMerge size={16} />
          变更提案
        </h2>
        <div style={listStyle}>
          {proposals.length === 0 ? (
            <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: "13px" }}>未找到提案</div>
          ) : (
            proposals.map((proposal) => (
              <div key={proposal.proposal_id} style={itemStyle}>
                {getStateIcon(proposal.state)}
                <div style={{ flex: 1 }}>
                  <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: "13px", fontWeight: "600" }}>
                    {proposal.summary}
                  </div>
                  <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: "11px" }}>
                    {proposal.author} • {new Date(proposal.created_at).toLocaleDateString()}
                  </div>
                </div>
                {proposal.state === "proposed" && (
                  <div style={{ display: "flex", gap: "6px" }}>
                    <button style={buttonStyle} onClick={() => approveProposal(proposal.proposal_id)}>
                      <CheckCircle size={12} />
                      批准
                    </button>
                    <button style={buttonStyle} onClick={() => rejectProposal(proposal.proposal_id)}>
                      <XCircle size={12} />
                      拒绝
                    </button>
                  </div>
                )}
                {proposal.state === "approved" && (
                  <button style={buttonStyle} onClick={() => publishProposal(proposal.proposal_id)}>
                    <Send size={12} />
                    发布
                  </button>
                )}
                <button
                  style={buttonStyle}
                  onClick={() => {
                    setSelectedProposal(proposal);
                    setShowProposalModal(true);
                  }}
                >
                  <FileText size={12} />
                  详情
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {showProposalModal && selectedProposal && (
        <div style={modalOverlayStyle} onClick={() => setShowProposalModal(false)}>
          <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "rgba(0, 0, 0, 0.9)", fontSize: "16px" }}>提案详情</h3>
              <button onClick={() => setShowProposalModal(false)} style={{ background: "none", border: "none", color: "rgba(0, 0, 0, 0.6)", cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                摘要
              </label>
              <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: "13px" }}>{selectedProposal.summary}</div>
            </div>
            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                状态
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "rgba(0, 0, 0, 0.9)", fontSize: "13px" }}>
                {getStateIcon(selectedProposal.state)}
                {selectedProposal.state}
              </div>
            </div>
            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                影响分析
              </label>
              <pre style={{ background: "rgba(255, 255, 255, 0.8)", padding: "12px", borderRadius: "6px", color: "rgba(0, 0, 0, 0.9)", fontSize: "12px", overflow: "auto" }}>
                {JSON.stringify(selectedProposal.impact_analysis, null, 2)}
              </pre>
            </div>
            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                SHACL 校验
              </label>
              <pre style={{ background: "rgba(255, 255, 255, 0.8)", padding: "12px", borderRadius: "6px", color: "rgba(0, 0, 0, 0.9)", fontSize: "12px", overflow: "auto" }}>
                {JSON.stringify(selectedProposal.shacl_validation, null, 2)}
              </pre>
            </div>
            <div>
              <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                评论 ({selectedProposal.comments.length})
              </label>
              <div style={{ maxHeight: "120px", overflow: "auto" }}>
                {selectedProposal.comments.map((comment) => (
                  <div key={comment.id} style={{ padding: "8px", background: "rgba(255, 255, 255, 0.6)", borderRadius: "4px", marginBottom: "6px" }}>
                    <div style={{ color: "rgba(0, 0, 0, 0.9)", fontSize: "12px", fontWeight: "600" }}>{comment.author}</div>
                    <div style={{ color: "rgba(0, 0, 0, 0.6)", fontSize: "11px" }}>{comment.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {showCompareModal && comparePair && (
        <div style={modalOverlayStyle} onClick={() => setShowCompareModal(false)}>
          <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "rgba(0, 0, 0, 0.9)", fontSize: "16px" }}>对比版本</h3>
              <button onClick={() => setShowCompareModal(false)} style={{ background: "none", border: "none", color: "rgba(0, 0, 0, 0.6)", cursor: "pointer" }}>
                <X size={18} />
              </button>
            </div>
            <div style={{ display: "flex", gap: "12px", marginBottom: "16px" }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                  版本 1
                </label>
                <input
                  type="text"
                  value={comparePair.v1}
                  onChange={(e) => setComparePair({ ...comparePair, v1: e.target.value })}
                  style={inputStyle}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ display: "block", color: "rgba(0, 0, 0, 0.6)", fontSize: "12px", marginBottom: "4px" }}>
                  版本 2
                </label>
                <input
                  type="text"
                  value={comparePair.v2}
                  onChange={(e) => setComparePair({ ...comparePair, v2: e.target.value })}
                  style={inputStyle}
                />
              </div>
            </div>
            <button style={buttonStyle} onClick={runVersionComparison} disabled={isLoading}>
              <Scale size={12} />
              {isLoading ? "对比中..." : "对比"}
            </button>
            {compareResult && (
              <pre style={{ marginTop: "16px", background: "rgba(255, 255, 255, 0.8)", padding: "12px", borderRadius: "6px", color: "rgba(0, 0, 0, 0.9)", fontSize: "12px", overflow: "auto" }}>
                {JSON.stringify(compareResult, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
