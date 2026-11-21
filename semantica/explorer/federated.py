"""
Governed Cross-Workspace Federated GraphRAG & Reciprocal Rank Fusion.

Enables search and graph traversal to span multiple physical workspace graphs
while enforcing strict read-grant validation and preserving provenance metadata.

Federation is **strictly read-only**: no mutations are dispatched to any
federated workspace, and results always carry ``origin_workspace`` provenance.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..auth.models import RequestContext
from .session import GraphSession
from .workspace_registry import WorkspaceSessionRegistry

logger = logging.getLogger(__name__)

# Default RRF constant (k=60 is standard in literature)
RRF_K = 60

# Thread pool for dispatching blocking GraphSession.search calls concurrently
_federation_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="federated")


@dataclass
class FederatedSearchResult:
    """A single search result annotated with provenance."""

    node: Dict[str, Any]
    score: float
    origin_workspace: str
    rrf_score: float = 0.0
    hop_distance: Optional[int] = None


@dataclass
class FederatedSearchResponse:
    """Merged, ranked results from a federated search."""

    results: List[FederatedSearchResult]
    total: int
    query: str
    workspaces_queried: List[str]
    fusion_method: str = "rrf"


def validate_federation_grants(
    identity: RequestContext,
    federated_workspaces: Sequence[str],
) -> List[str]:
    """Verify that the caller has at least ``Viewer`` read access on every
    requested federated workspace.

    Returns:
        The list of denied workspace IDs (empty if all are authorized).
    """
    denied: List[str] = []
    for ws_id in federated_workspaces:
        if not identity.has_workspace_access(ws_id, required_role="Viewer"):
            denied.append(ws_id)
    return denied


def reciprocal_rank_fusion(
    ranked_lists: Dict[str, List[FederatedSearchResult]],
    k: int = RRF_K,
) -> List[FederatedSearchResult]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion (RRF).

    Each result list is a workspace-local ranking. RRF assigns each result a
    score of ``1 / (k + rank)`` per list it appears in, then sums across all
    lists. Results are de-duplicated by ``(node_id, origin_workspace)`` and
    ordered by descending RRF score.

    Args:
        ranked_lists: Mapping of workspace_id → ordered results (best first).
        k: RRF smoothing constant (default 60).

    Returns:
        Merged list ordered by descending RRF score.
    """
    # Accumulator keyed by (node_id, origin_workspace)
    scores: Dict[tuple, float] = {}
    best_result: Dict[tuple, FederatedSearchResult] = {}

    for ws_id, results in ranked_lists.items():
        for rank, result in enumerate(results, start=1):
            node_id = result.node.get("id", "")
            key = (node_id, result.origin_workspace)
            rrf_contribution = 1.0 / (k + rank)
            scores[key] = scores.get(key, 0.0) + rrf_contribution

            # Keep the result with the highest original score for metadata
            if key not in best_result or result.score > best_result[key].score:
                best_result[key] = result

    # Apply accumulated RRF scores and sort
    merged: List[FederatedSearchResult] = []
    for key, rrf_score in scores.items():
        result = best_result[key]
        result.rrf_score = rrf_score
        merged.append(result)

    merged.sort(key=lambda r: r.rrf_score, reverse=True)
    return merged


def _search_workspace(
    session: GraphSession,
    ws_id: str,
    query: str,
    limit: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[FederatedSearchResult]:
    """Execute a search on a single workspace session (blocking, run in thread)."""
    raw_results = session.search(query, limit=limit, filters=filters or {})
    return [
        FederatedSearchResult(
            node=r.get("node", {}),
            score=r.get("score", 0.0),
            origin_workspace=ws_id,
        )
        for r in raw_results
    ]


async def federated_search(
    registry: WorkspaceSessionRegistry,
    identity: RequestContext,
    query: str,
    primary_workspace: str,
    federated_workspaces: List[str],
    limit: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    rrf_k: int = RRF_K,
) -> FederatedSearchResponse:
    """Execute a governed federated search across multiple workspaces.

    1. Validates read grants on all federated workspaces.
    2. Dispatches concurrent searches to primary + federated workspaces.
    3. Merges results via Reciprocal Rank Fusion (RRF).

    Args:
        registry: Workspace session registry for session lookup.
        identity: Authenticated caller context.
        query: Search query string.
        primary_workspace: Caller's active workspace (always included).
        federated_workspaces: Additional workspaces to query.
        limit: Per-workspace result limit before fusion.
        filters: Optional search filters forwarded to each workspace.
        rrf_k: RRF smoothing constant.

    Raises:
        PermissionError: If caller lacks Viewer access on any federated workspace.

    Returns:
        Fused search response with provenance annotations.
    """
    # Validate grants
    denied = validate_federation_grants(identity, federated_workspaces)
    if denied:
        raise PermissionError(
            f"Access denied: Viewer role required on workspace(s): {', '.join(denied)}"
        )

    # Build the full set of workspaces to query (primary always included, dedup)
    all_workspaces = list(dict.fromkeys([primary_workspace] + list(federated_workspaces)))

    loop = asyncio.get_running_loop()

    # Dispatch concurrent searches
    async def _search_one(ws_id: str) -> tuple[str, List[FederatedSearchResult]]:
        session = registry.get(ws_id)
        results = await loop.run_in_executor(
            _federation_pool,
            _search_workspace,
            session,
            ws_id,
            query,
            limit,
            filters,
        )
        return ws_id, results

    tasks = [_search_one(ws_id) for ws_id in all_workspaces]
    workspace_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful results, log failures
    ranked_lists: Dict[str, List[FederatedSearchResult]] = {}
    for result in workspace_results:
        if isinstance(result, Exception):
            logger.error("Federated search error: %s", result)
            continue
        ws_id, results = result
        ranked_lists[ws_id] = results

    # Fuse with RRF
    merged = reciprocal_rank_fusion(ranked_lists, k=rrf_k)

    return FederatedSearchResponse(
        results=merged[:limit],
        total=len(merged),
        query=query,
        workspaces_queried=list(ranked_lists.keys()),
    )


def federated_get_nodes(
    registry: WorkspaceSessionRegistry,
    identity: RequestContext,
    primary_workspace: str,
    federated_workspaces: List[str],
    node_type: Optional[str] = None,
    limit: int = 100,
) -> tuple[List[Dict[str, Any]], int, List[str]]:
    """Synchronous federated node retrieval across workspaces.

    Returns:
        Tuple of (nodes_with_provenance, total_count, workspaces_queried).

    Raises:
        PermissionError: If caller lacks Viewer on any federated workspace.
    """
    denied = validate_federation_grants(identity, federated_workspaces)
    if denied:
        raise PermissionError(
            f"Access denied: Viewer role required on workspace(s): {', '.join(denied)}"
        )

    all_workspaces = list(dict.fromkeys([primary_workspace] + list(federated_workspaces)))

    all_nodes: List[Dict[str, Any]] = []
    for ws_id in all_workspaces:
        session = registry.get(ws_id)
        nodes, _total = session.get_nodes(node_type=node_type, limit=limit)
        for node in nodes:
            node_with_provenance = dict(node)
            node_with_provenance["origin_workspace"] = ws_id
            all_nodes.append(node_with_provenance)

    return all_nodes[:limit], len(all_nodes), all_workspaces
