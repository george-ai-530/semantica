"""
Thread-safe per-workspace GraphSession registry for multi-tenant graph isolation.

Each workspace maps to a distinct FalkorDB graph identifier (``graph:ws_<id>``)
and its own ``GraphSession`` instance. The registry handles lazy initialization,
caching, and graceful shutdown of all sessions.
"""

import logging
import threading
from typing import Callable, Dict, Optional

from ..context.context_graph import ContextGraph
from .session import GraphSession

logger = logging.getLogger(__name__)

# Default graph key builder used when no custom mapper is supplied.
DEFAULT_GRAPH_KEY_PREFIX = "graph:ws_"


def default_graph_key(ws_id: str) -> str:
    """Map a workspace ID to its FalkorDB graph key.

    The ``default`` workspace uses the legacy key ``graph:default`` for
    backwards compatibility with existing single-tenant installations.
    """
    if ws_id == "default":
        return "graph:default"
    return f"{DEFAULT_GRAPH_KEY_PREFIX}{ws_id}"


# ---------------------------------------------------------------------------
# Default domain seed datasets — pre-populate known tenant workspaces so their
# graphs survive container restarts without an external ingestion script.
# ---------------------------------------------------------------------------

def _seed_ws_user_a(graph: "ContextGraph") -> None:
    """Seed ws_user_a with the Deep Tech & Space Exploration R&D Graph."""
    nodes = [
        ("project_apollo_x", "project",
         "Project Apollo X — Next-generation crewed lunar return mission with deep-space habitat",
         {"domain": "space_exploration", "status": "active", "budget_usd": "4200000000",
          "lead_agency": "NASA-JPL", "target_launch": "2027-Q3"}),
        ("quantum_core_v2", "technology",
         "Quantum Core v2 — 256-qubit fault-tolerant superconducting quantum processor",
         {"domain": "quantum_computing", "qubit_count": "256", "error_rate": "0.001",
          "operating_temp_mk": "15", "manufacturer": "DeepQuant Labs"}),
        ("deep_space_probe", "spacecraft",
         "Deep Space Probe DSP-7 — autonomous ion-drive probe targeting Europa subsurface ocean",
         {"domain": "space_exploration", "propulsion": "ion_drive", "target_body": "Europa",
          "mission_duration_years": "12", "autonomous_ai": "DeepNav-3"}),
        ("propulsion_lab", "facility",
         "Advanced Propulsion Research Laboratory — testing nuclear thermal and ion thruster systems",
         {"domain": "aerospace_engineering", "location": "Mojave, CA",
          "max_thrust_kn": "890", "accreditation": "DOE-NE"}),
        ("neurosynth_ai", "technology",
         "NeuroSynth AI — neuromorphic computing stack for real-time deep-space navigation decisions",
         {"domain": "artificial_intelligence", "architecture": "neuromorphic",
          "inference_latency_ms": "0.3", "power_draw_w": "12"}),
        ("materials_lab_alpha", "facility",
         "Materials Lab Alpha — advanced nano-composite and radiation-shielding R&D for spacecraft hulls",
         {"domain": "materials_science", "location": "Houston, TX", "accreditation": "NASA-MSFC"}),
        ("helios_solar_array", "technology",
         "Helios Solar Array — 450 W/kg ultra-lightweight photovoltaic system for deep-space power",
         {"domain": "power_systems", "efficiency_pct": "42", "mass_kg": "28",
          "deployment": "fold-out"}),
    ]
    edges = [
        ("project_apollo_x", "quantum_core_v2", "uses_technology",
         {"role": "trajectory_optimization", "critical": "true"}),
        ("project_apollo_x", "propulsion_lab", "developed_at",
         {"contract": "NAS-2027-001"}),
        ("deep_space_probe", "neurosynth_ai", "powered_by",
         {"integration": "primary_guidance"}),
        ("deep_space_probe", "propulsion_lab", "tested_at",
         {"test_phase": "phase_3"}),
        ("deep_space_probe", "helios_solar_array", "powered_by",
         {"configuration": "dual_wing"}),
        ("project_apollo_x", "materials_lab_alpha", "sourced_from",
         {"material": "carbon_nanotube_composite"}),
        ("quantum_core_v2", "neurosynth_ai", "accelerates",
         {"workload": "deep_learning_inference"}),
    ]
    for node_id, node_type, content, props in nodes:
        graph.add_node(node_id, node_type=node_type, content=content, **props)
    for src, tgt, rel_type, props in edges:
        try:
            graph.add_edge(src, tgt, edge_type=rel_type, **props)
        except Exception:
            pass


def _seed_ws_user_b(graph: "ContextGraph") -> None:
    """Seed ws_user_b with the Global Financial & Enterprise Operations Graph."""
    nodes = [
        ("corp_nexus_holdings", "organization",
         "Corp Nexus Holdings — multinational conglomerate spanning fintech, insurance, and real estate",
         {"domain": "corporate_finance", "headquarters": "Singapore", "aum_usd_bn": "142",
          "employees": "48000", "stock_ticker": "CNH:SGX"}),
        ("series_b_syndicate", "investment_round",
         "Series B Syndicate — $320M cross-border fintech growth round led by Nexus Ventures and Sovereign Alpha",
         {"domain": "venture_capital", "amount_usd_m": "320",
          "lead_investors": "Nexus Ventures, Sovereign Alpha",
          "close_date": "2024-09-15", "post_money_valuation_usd_bn": "2.1"}),
        ("cross_border_settlement", "financial_system",
         "CrossBorder Settlement Engine — ISO 20022 compliant real-time FX settlement across 38 currencies",
         {"domain": "payments", "supported_currencies": "38", "daily_volume_usd_bn": "7.4",
          "latency_ms": "120", "protocol": "ISO_20022"}),
        ("compliance_risk_matrix", "risk_framework",
         "Compliance & Risk Matrix — enterprise-wide regulatory risk scoring across APAC, EU, and US jurisdictions",
         {"domain": "regulatory_compliance", "jurisdictions": "APAC,EU,US",
          "risk_dimensions": "12", "review_cycle": "quarterly", "framework": "Basel_IV"}),
        ("sovereign_alpha_fund", "fund",
         "Sovereign Alpha Fund — $4.8B sovereign wealth vehicle focused on digital infrastructure and fintech",
         {"domain": "asset_management", "aum_usd_bn": "4.8",
          "strategy": "digital_infrastructure", "domicile": "Abu Dhabi"}),
        ("nexus_kyc_platform", "technology",
         "Nexus KYC Platform — AI-driven identity verification and AML screening across 190 countries",
         {"domain": "regtech", "countries_covered": "190",
          "false_positive_rate_pct": "0.4", "daily_screenings": "2200000"}),
        ("apac_treasury_desk", "business_unit",
         "APAC Treasury Desk — regional liquidity management and hedging operations for Asia-Pacific markets",
         {"domain": "treasury_management", "region": "APAC",
          "managed_exposure_usd_bn": "18", "instruments": "FX,IRS,CDS"}),
    ]
    edges = [
        ("corp_nexus_holdings", "series_b_syndicate", "raised_funding",
         {"role": "lead_recipient", "equity_pct": "15.2"}),
        ("series_b_syndicate", "sovereign_alpha_fund", "funded_by",
         {"commitment_usd_m": "180", "tranche": "primary"}),
        ("corp_nexus_holdings", "cross_border_settlement", "operates",
         {"subsidiary": "NexusPay Ltd"}),
        ("cross_border_settlement", "compliance_risk_matrix", "governed_by",
         {"audit_cycle": "monthly"}),
        ("corp_nexus_holdings", "nexus_kyc_platform", "owns",
         {"ownership_pct": "100", "subsidiary": "NexusTech GmbH"}),
        ("nexus_kyc_platform", "compliance_risk_matrix", "feeds_data_into",
         {"feed_type": "aml_signals", "frequency": "real_time"}),
        ("corp_nexus_holdings", "apac_treasury_desk", "manages",
         {"reporting_line": "Group CFO"}),
        ("apac_treasury_desk", "cross_border_settlement", "uses",
         {"usage": "hedging_execution"}),
    ]
    for node_id, node_type, content, props in nodes:
        graph.add_node(node_id, node_type=node_type, content=content, **props)
    for src, tgt, rel_type, props in edges:
        try:
            graph.add_edge(src, tgt, edge_type=rel_type, **props)
        except Exception:
            pass


class WorkspaceSessionRegistry:
    """Concurrent registry that creates, caches, and retrieves per-workspace
    ``GraphSession`` instances.

    Thread-safety is provided by an internal ``RLock``; all public methods are
    safe to call from concurrent request threads.

    Parameters:
        graph_key_fn:
            Optional callable mapping ``ws_id -> str`` that returns the
            FalkorDB graph key for a workspace. Defaults to
            :func:`default_graph_key`.
        provenance_storage_path:
            Optional path forwarded to each ``GraphSession`` for its
            provenance database.
        session_factory:
            Optional callable ``(graph_key: str) -> GraphSession`` for custom
            session construction (e.g. connecting to a real FalkorDB instance).
            When omitted the registry creates an in-memory ``ContextGraph``
            session for each workspace.
    """

    def __init__(
        self,
        graph_key_fn: Optional[Callable[[str], str]] = None,
        provenance_storage_path: Optional[str] = None,
        session_factory: Optional[Callable[[str], GraphSession]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, GraphSession] = {}
        self._graph_keys: Dict[str, str] = {}  # ws_id -> graph_key
        self._graph_key_fn = graph_key_fn or default_graph_key
        self._provenance_storage_path = provenance_storage_path
        self._session_factory = session_factory
        self._closed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, ws_id: str) -> GraphSession:
        """Return the ``GraphSession`` for *ws_id*, creating it lazily if needed.

        Raises:
            RuntimeError: If the registry has been shut down.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("WorkspaceSessionRegistry is shut down")
            session = self._sessions.get(ws_id)
            if session is not None:
                return session
            return self._create_locked(ws_id)

    def get_if_exists(self, ws_id: str) -> Optional[GraphSession]:
        """Return the cached session for *ws_id* without creating one."""
        with self._lock:
            return self._sessions.get(ws_id)

    def register(self, ws_id: str, session: GraphSession) -> None:
        """Externally register a pre-built session (e.g. the legacy default session).

        If the workspace already has a session, it is **replaced** silently.
        """
        graph_key = self._graph_key_fn(ws_id)
        with self._lock:
            self._sessions[ws_id] = session
            self._graph_keys[ws_id] = graph_key
            logger.info(
                "Registered external session for workspace %s (graph_key=%s)",
                ws_id,
                graph_key,
            )

    def remove(self, ws_id: str) -> Optional[GraphSession]:
        """Remove and return the session for *ws_id*, or ``None``."""
        with self._lock:
            self._graph_keys.pop(ws_id, None)
            return self._sessions.pop(ws_id, None)

    def graph_key_for(self, ws_id: str) -> str:
        """Return the FalkorDB graph key for a workspace without creating a session."""
        with self._lock:
            cached = self._graph_keys.get(ws_id)
            if cached:
                return cached
        return self._graph_key_fn(ws_id)

    @property
    def active_workspaces(self) -> list[str]:
        """List workspace IDs with live sessions."""
        with self._lock:
            return list(self._sessions.keys())

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def shutdown(self) -> None:
        """Gracefully close all cached sessions and prevent new ones from being created.

        Idempotent: calling twice has no additional effect.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            ws_ids = list(self._sessions.keys())

        for ws_id in ws_ids:
            try:
                session = self._sessions.pop(ws_id, None)
                if session is not None:
                    logger.info("Shutting down session for workspace %s", ws_id)
                    # GraphSession has no explicit close(), but clear heavy
                    # cached state to free memory promptly.
                    session.invalidate_embedding_cache()
            except Exception:
                logger.exception("Error shutting down session for workspace %s", ws_id)

        with self._lock:
            self._sessions.clear()
            self._graph_keys.clear()

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_locked(self, ws_id: str) -> GraphSession:
        """Create a new ``GraphSession`` for *ws_id*. Must be called under ``_lock``."""
        graph_key = self._graph_key_fn(ws_id)
        self._graph_keys[ws_id] = graph_key

        if self._session_factory is not None:
            session = self._session_factory(graph_key)
        else:
            # In-memory ContextGraph for each workspace.
            graph = ContextGraph(advanced_analytics=False)
            # Pre-populate default domain datasets for known tenant workspaces so
            # that their graphs survive container restarts without requiring an
            # external populate script to re-ingest data.
            if ws_id == "ws_user_a":
                _seed_ws_user_a(graph)
            elif ws_id == "ws_user_b":
                _seed_ws_user_b(graph)
            session = GraphSession(
                graph,
                provenance_storage_path=self._provenance_storage_path,
            )

        self._sessions[ws_id] = session
        logger.info(
            "Lazily initialized session for workspace %s (graph_key=%s)",
            ws_id,
            graph_key,
        )
        return session
