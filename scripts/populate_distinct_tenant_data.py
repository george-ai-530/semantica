#!/usr/bin/env python3
"""
Populate Distinct Tenant Data for Multi-Tenant Isolation Demo
=============================================================

Ingests two clearly distinguishable domain datasets into isolated workspaces:
  - user_a / ws_user_a: Deep Tech & Space Exploration R&D Graph
  - user_b / ws_user_b: Global Financial & Enterprise Operations Graph

Usage:
    .venv/bin/python scripts/populate_distinct_tenant_data.py [--base-url URL]

Default base URL: http://192.168.1.15:8000
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from io import BytesIO


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://192.168.1.15:8000"


# ---------------------------------------------------------------------------
# Dataset Definitions
# ---------------------------------------------------------------------------

DATASET_USER_A = {
    "workspace_id": "ws_user_a",
    "username": "user_a",
    "password": "1",
    "description": "Deep Tech & Space Exploration R&D Graph",
    "graph": {
        "nodes": [
            {
                "id": "project_apollo_x",
                "type": "project",
                "properties": {
                    "content": "Project Apollo X — Next-generation crewed lunar return mission with deep-space habitat",
                    "domain": "space_exploration",
                    "status": "active",
                    "budget_usd": "4200000000",
                    "lead_agency": "NASA-JPL",
                    "target_launch": "2027-Q3",
                },
            },
            {
                "id": "quantum_core_v2",
                "type": "technology",
                "properties": {
                    "content": "Quantum Core v2 — 256-qubit fault-tolerant superconducting quantum processor",
                    "domain": "quantum_computing",
                    "qubit_count": "256",
                    "error_rate": "0.001",
                    "operating_temp_mk": "15",
                    "manufacturer": "DeepQuant Labs",
                },
            },
            {
                "id": "deep_space_probe",
                "type": "spacecraft",
                "properties": {
                    "content": "Deep Space Probe DSP-7 — autonomous ion-drive probe targeting Europa subsurface ocean",
                    "domain": "space_exploration",
                    "propulsion": "ion_drive",
                    "target_body": "Europa",
                    "mission_duration_years": "12",
                    "autonomous_ai": "DeepNav-3",
                },
            },
            {
                "id": "propulsion_lab",
                "type": "facility",
                "properties": {
                    "content": "Advanced Propulsion Research Laboratory — testing nuclear thermal and ion thruster systems",
                    "domain": "aerospace_engineering",
                    "location": "Mojave, CA",
                    "max_thrust_kn": "890",
                    "accreditation": "DOE-NE",
                },
            },
            {
                "id": "neurosynth_ai",
                "type": "technology",
                "properties": {
                    "content": "NeuroSynth AI — neuromorphic computing stack for real-time deep-space navigation decisions",
                    "domain": "artificial_intelligence",
                    "architecture": "neuromorphic",
                    "inference_latency_ms": "0.3",
                    "power_draw_w": "12",
                },
            },
            {
                "id": "materials_lab_alpha",
                "type": "facility",
                "properties": {
                    "content": "Materials Lab Alpha — advanced nano-composite and radiation-shielding R&D for spacecraft hulls",
                    "domain": "materials_science",
                    "location": "Houston, TX",
                    "accreditation": "NASA-MSFC",
                },
            },
            {
                "id": "helios_solar_array",
                "type": "technology",
                "properties": {
                    "content": "Helios Solar Array — 450 W/kg ultra-lightweight photovoltaic system for deep-space power",
                    "domain": "power_systems",
                    "efficiency_pct": "42",
                    "mass_kg": "28",
                    "deployment": "fold-out",
                },
            },
        ],
        "edges": [
            {
                "source": "project_apollo_x",
                "target": "quantum_core_v2",
                "type": "uses_technology",
                "weight": 0.9,
                "properties": {"role": "trajectory_optimization", "critical": "true"},
            },
            {
                "source": "project_apollo_x",
                "target": "propulsion_lab",
                "type": "developed_at",
                "weight": 1.0,
                "properties": {"contract": "NAS-2027-001"},
            },
            {
                "source": "deep_space_probe",
                "target": "neurosynth_ai",
                "type": "powered_by",
                "weight": 0.95,
                "properties": {"integration": "primary_guidance"},
            },
            {
                "source": "deep_space_probe",
                "target": "propulsion_lab",
                "type": "tested_at",
                "weight": 0.85,
                "properties": {"test_phase": "phase_3"},
            },
            {
                "source": "deep_space_probe",
                "target": "helios_solar_array",
                "type": "powered_by",
                "weight": 0.9,
                "properties": {"configuration": "dual_wing"},
            },
            {
                "source": "project_apollo_x",
                "target": "materials_lab_alpha",
                "type": "sourced_from",
                "weight": 0.8,
                "properties": {"material": "carbon_nanotube_composite"},
            },
            {
                "source": "quantum_core_v2",
                "target": "neurosynth_ai",
                "type": "accelerates",
                "weight": 0.75,
                "properties": {"workload": "deep_learning_inference"},
            },
        ],
    },
}

DATASET_USER_B = {
    "workspace_id": "ws_user_b",
    "username": "user_b",
    "password": "1",
    "description": "Global Financial & Enterprise Operations Graph",
    "graph": {
        "nodes": [
            {
                "id": "corp_nexus_holdings",
                "type": "organization",
                "properties": {
                    "content": "Corp Nexus Holdings — multinational conglomerate spanning fintech, insurance, and real estate",
                    "domain": "corporate_finance",
                    "headquarters": "Singapore",
                    "aum_usd_bn": "142",
                    "employees": "48000",
                    "stock_ticker": "CNH:SGX",
                },
            },
            {
                "id": "series_b_syndicate",
                "type": "investment_round",
                "properties": {
                    "content": "Series B Syndicate — $320M cross-border fintech growth round led by Nexus Ventures and Sovereign Alpha",
                    "domain": "venture_capital",
                    "amount_usd_m": "320",
                    "lead_investors": "Nexus Ventures, Sovereign Alpha",
                    "close_date": "2024-09-15",
                    "post_money_valuation_usd_bn": "2.1",
                },
            },
            {
                "id": "cross_border_settlement",
                "type": "financial_system",
                "properties": {
                    "content": "CrossBorder Settlement Engine — ISO 20022 compliant real-time FX settlement across 38 currencies",
                    "domain": "payments",
                    "supported_currencies": "38",
                    "daily_volume_usd_bn": "7.4",
                    "latency_ms": "120",
                    "protocol": "ISO_20022",
                },
            },
            {
                "id": "compliance_risk_matrix",
                "type": "risk_framework",
                "properties": {
                    "content": "Compliance & Risk Matrix — enterprise-wide regulatory risk scoring across APAC, EU, and US jurisdictions",
                    "domain": "regulatory_compliance",
                    "jurisdictions": "APAC,EU,US",
                    "risk_dimensions": "12",
                    "review_cycle": "quarterly",
                    "framework": "Basel_IV",
                },
            },
            {
                "id": "sovereign_alpha_fund",
                "type": "fund",
                "properties": {
                    "content": "Sovereign Alpha Fund — $4.8B sovereign wealth vehicle focused on digital infrastructure and fintech",
                    "domain": "asset_management",
                    "aum_usd_bn": "4.8",
                    "strategy": "digital_infrastructure",
                    "domicile": "Abu Dhabi",
                },
            },
            {
                "id": "nexus_kyc_platform",
                "type": "technology",
                "properties": {
                    "content": "Nexus KYC Platform — AI-driven identity verification and AML screening across 190 countries",
                    "domain": "regtech",
                    "countries_covered": "190",
                    "false_positive_rate_pct": "0.4",
                    "daily_screenings": "2200000",
                },
            },
            {
                "id": "apac_treasury_desk",
                "type": "business_unit",
                "properties": {
                    "content": "APAC Treasury Desk — regional liquidity management and hedging operations for Asia-Pacific markets",
                    "domain": "treasury_management",
                    "region": "APAC",
                    "managed_exposure_usd_bn": "18",
                    "instruments": "FX,IRS,CDS",
                },
            },
        ],
        "edges": [
            {
                "source": "corp_nexus_holdings",
                "target": "series_b_syndicate",
                "type": "raised_funding",
                "weight": 1.0,
                "properties": {"role": "lead_recipient", "equity_pct": "15.2"},
            },
            {
                "source": "series_b_syndicate",
                "target": "sovereign_alpha_fund",
                "type": "funded_by",
                "weight": 0.9,
                "properties": {"commitment_usd_m": "180", "tranche": "primary"},
            },
            {
                "source": "corp_nexus_holdings",
                "target": "cross_border_settlement",
                "type": "operates",
                "weight": 1.0,
                "properties": {"subsidiary": "NexusPay Ltd"},
            },
            {
                "source": "cross_border_settlement",
                "target": "compliance_risk_matrix",
                "type": "governed_by",
                "weight": 0.95,
                "properties": {"audit_cycle": "monthly"},
            },
            {
                "source": "corp_nexus_holdings",
                "target": "nexus_kyc_platform",
                "type": "owns",
                "weight": 0.9,
                "properties": {"ownership_pct": "100", "subsidiary": "NexusTech GmbH"},
            },
            {
                "source": "nexus_kyc_platform",
                "target": "compliance_risk_matrix",
                "type": "feeds_data_into",
                "weight": 0.85,
                "properties": {"feed_type": "aml_signals", "frequency": "real_time"},
            },
            {
                "source": "corp_nexus_holdings",
                "target": "apac_treasury_desk",
                "type": "manages",
                "weight": 1.0,
                "properties": {"reporting_line": "Group CFO"},
            },
            {
                "source": "apac_treasury_desk",
                "target": "cross_border_settlement",
                "type": "uses",
                "weight": 0.88,
                "properties": {"usage": "hedging_execution"},
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only, no requests dependency)
# ---------------------------------------------------------------------------


def _post_json(url: str, payload: dict, headers: dict = None) -> dict:
    """POST JSON payload, return parsed response dict."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_multipart_json_file(
    url: str, json_data: dict, filename: str, headers: dict = None
) -> dict:
    """
    POST a JSON file as multipart/form-data upload to /api/import.
    Uses stdlib only — constructs the boundary manually.
    """
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    body_parts = []
    file_bytes = json.dumps(json_data, indent=2).encode("utf-8")

    part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode("utf-8") + file_bytes + b"\r\n"
    body_parts.append(part)
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(body_parts)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return {"status_code": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        return {"status_code": exc.code, "body": body_text}


def login(base_url: str, username: str, password: str) -> str:
    """Authenticate and return Bearer token."""
    resp = _post_json(
        f"{base_url}/api/auth/login",
        {"username": username, "password": password, "login_type": "local"},
    )
    token = resp.get("access_token")
    if not token:
        raise RuntimeError(f"Login failed for {username!r}: {resp}")
    return token


def ingest_dataset(base_url: str, dataset: dict) -> dict:
    """
    Login as dataset user, POST graph JSON to /api/import with X-Workspace-ID.
    Returns result summary dict.
    """
    ws_id = dataset["workspace_id"]
    username = dataset["username"]
    print(f"\n{'='*60}")
    print(f"[{username}] Logging in...")
    token = login(base_url, username, dataset["password"])
    print(f"[{username}] Authenticated. Token prefix: {token[:20]}...")

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": ws_id,
    }

    graph_payload = dataset["graph"]
    node_count = len(graph_payload.get("nodes", []))
    edge_count = len(graph_payload.get("edges", []))
    print(
        f"[{username}] Ingesting {node_count} nodes + {edge_count} edges "
        f"into workspace '{ws_id}'..."
    )

    result = _post_multipart_json_file(
        url=f"{base_url}/api/import",
        json_data=graph_payload,
        filename=f"{ws_id}_graph.json",
        headers=headers,
    )

    status_code = result.get("status_code")
    body = result.get("body")

    if status_code not in (200, 201):
        print(f"[{username}] ERROR: HTTP {status_code}: {body}")
        return {"success": False, "username": username, "workspace": ws_id, "error": body}

    nodes_imported = body.get("nodes_imported", 0) if isinstance(body, dict) else 0
    edges_imported = body.get("edges_imported", 0) if isinstance(body, dict) else 0
    print(f"[{username}] ✅ Import successful: {nodes_imported} nodes, {edges_imported} edges imported.")
    return {
        "success": True,
        "username": username,
        "workspace": ws_id,
        "description": dataset["description"],
        "nodes_imported": nodes_imported,
        "edges_imported": edges_imported,
        "http_status": status_code,
    }


def verify_isolation(base_url: str, results: list) -> None:
    """Quick cross-tenant 403 isolation probe after ingestion."""
    print(f"\n{'='*60}")
    print("Cross-tenant isolation probe...")

    # Login as both users
    token_a = login(base_url, "user_a", "1")
    token_b = login(base_url, "user_b", "1")

    probes = [
        ("user_a", token_a, "ws_user_a", 200),
        ("user_a", token_a, "ws_user_b", 403),
        ("user_b", token_b, "ws_user_b", 200),
        ("user_b", token_b, "ws_user_a", 403),
    ]

    all_ok = True
    for username, token, workspace, expected in probes:
        req = urllib.request.Request(
            f"{base_url}/api/graph/nodes",
            method="GET",
        )
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("X-Workspace-ID", workspace)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                got = resp.status
        except urllib.error.HTTPError as exc:
            got = exc.code

        ok = got == expected
        all_ok = all_ok and ok
        icon = "✅" if ok else "❌"
        print(f"  {icon} {username} -> {workspace}: HTTP {got} (expected {expected})")

    if all_ok:
        print("Cross-tenant isolation: ALL OK ✅")
    else:
        print("Cross-tenant isolation: SOME FAILURES ❌")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Populate distinct tenant graph data")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the Semantica Explorer API (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print(f"Target: {base_url}")

    results = []
    for dataset in [DATASET_USER_A, DATASET_USER_B]:
        result = ingest_dataset(base_url, dataset)
        results.append(result)

    print(f"\n{'='*60}")
    print("INGESTION SUMMARY")
    print(f"{'='*60}")
    all_success = True
    for r in results:
        if r["success"]:
            print(
                f"  ✅ [{r['username']}] workspace={r['workspace']}: "
                f"{r['nodes_imported']} nodes, {r['edges_imported']} edges | "
                f"{r['description']}"
            )
        else:
            all_success = False
            print(f"  ❌ [{r['username']}] workspace={r['workspace']}: FAILED — {r.get('error')}")

    verify_isolation(base_url, results)

    print(f"\n{'='*60}")
    if all_success:
        print("All ingestion tasks completed successfully. ✅")
    else:
        print("One or more ingestion tasks FAILED. ❌")
        sys.exit(1)

    return results


if __name__ == "__main__":
    main()
