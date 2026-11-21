"""
Federated GraphRAG routes for cross-workspace search and retrieval.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..dependencies import get_session
from ..schemas import NodeResponse, SearchResultItem
from ..session import GraphSession
from ...auth.dependencies import get_current_identity, require_workspace_role
from ...auth.models import RequestContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph/federated", tags=["Federated GraphRAG"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class FederatedSearchRequest(BaseModel):
    """Search request that spans multiple workspaces."""

    query: str
    federated_workspaces: List[str] = Field(
        default_factory=list,
        description="Additional workspace IDs to include in the search.",
    )
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=200)


class FederatedSearchResultItem(BaseModel):
    """A single federated search result with provenance."""

    node: NodeResponse
    score: float = 0.0
    rrf_score: float = 0.0
    origin_workspace: str = ""
    hop_distance: Optional[int] = None


class FederatedSearchResponse(BaseModel):
    """Response from a federated cross-workspace search."""

    results: List[FederatedSearchResultItem]
    total: int
    query: str
    workspaces_queried: List[str]
    fusion_method: str = "rrf"


class FederatedNodesRequest(BaseModel):
    """Request to retrieve nodes from multiple workspaces."""

    federated_workspaces: List[str] = Field(
        default_factory=list,
        description="Additional workspace IDs to include.",
    )
    node_type: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)


class FederatedNodeItem(BaseModel):
    """A node annotated with its origin workspace."""

    node: NodeResponse
    origin_workspace: str = ""


class FederatedNodesResponse(BaseModel):
    """Response from a federated node retrieval."""

    nodes: List[FederatedNodeItem]
    total: int
    workspaces_queried: List[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/search", response_model=FederatedSearchResponse)
async def federated_search_route(
    body: FederatedSearchRequest,
    request: Request,
    identity: RequestContext = Depends(get_current_identity),
):
    """Execute a governed federated search across the caller's primary workspace
    and additional authorized workspaces, fusing results with RRF.
    """
    from ..federated import federated_search
    from ..workspace_registry import WorkspaceSessionRegistry

    registry: Optional[WorkspaceSessionRegistry] = getattr(
        request.app.state, "workspace_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workspace session registry is not configured.",
        )

    primary_ws = identity.current_workspace or "default"

    try:
        result = await federated_search(
            registry=registry,
            identity=identity,
            query=body.query,
            primary_workspace=primary_ws,
            federated_workspaces=body.federated_workspaces,
            limit=body.limit,
            filters=body.filters,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    items = [
        FederatedSearchResultItem(
            node=NodeResponse(**r.node),
            score=r.score,
            rrf_score=r.rrf_score,
            origin_workspace=r.origin_workspace,
            hop_distance=r.hop_distance,
        )
        for r in result.results
    ]

    return FederatedSearchResponse(
        results=items,
        total=result.total,
        query=result.query,
        workspaces_queried=result.workspaces_queried,
    )


@router.post("/nodes", response_model=FederatedNodesResponse)
async def federated_nodes_route(
    body: FederatedNodesRequest,
    request: Request,
    identity: RequestContext = Depends(get_current_identity),
):
    """Retrieve nodes from the caller's primary workspace and additional
    authorized workspaces, with provenance annotations.
    """
    from ..federated import federated_get_nodes
    from ..workspace_registry import WorkspaceSessionRegistry

    registry: Optional[WorkspaceSessionRegistry] = getattr(
        request.app.state, "workspace_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workspace session registry is not configured.",
        )

    primary_ws = identity.current_workspace or "default"

    try:
        nodes, total, queried = federated_get_nodes(
            registry=registry,
            identity=identity,
            primary_workspace=primary_ws,
            federated_workspaces=body.federated_workspaces,
            node_type=body.node_type,
            limit=body.limit,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    items = [
        FederatedNodeItem(
            node=NodeResponse(**{k: v for k, v in n.items() if k != "origin_workspace"}),
            origin_workspace=n.get("origin_workspace", ""),
        )
        for n in nodes
    ]

    return FederatedNodesResponse(
        nodes=items,
        total=total,
        workspaces_queried=queried,
    )
