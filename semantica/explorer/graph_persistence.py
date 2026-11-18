"""
Durable multi-workspace graph persistence for Semantica Explorer.

Provides two complementary, zero-external-dependency persistence layers:
1. ``WorkspaceGraphStore``: Embedded SQLite WAL database (``/data/semantica_graphs.db``)
   offering ACID durability across container restarts and recreations for all
   tenant workspaces (``default``, ``ws_user_a``, ``ws_user_b``, ``ws_<id>``).
2. ``FalkorDBSyncBridge``: Pure-stdlib ``socket`` RESP2 client mirroring
   per-workspace graphs into isolated physical FalkorDB graphs
   (``graph:default``, ``graph:ws_<id>``) via ``GRAPH.QUERY`` when
   ``FALKORDB_HOST`` is configured.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..context.context_graph import ContextEdge, ContextGraph, ContextNode

logger = logging.getLogger(__name__)

_NODE_ENVELOPE_KEY = "__semantica_node_envelope__"
_EDGE_ENVELOPE_KEY = "__semantica_edge_envelope__"
_SAFE_CYPHER_LABEL_RE = re.compile(r"[^A-Za-z0-9_]")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def graph_db_path_from_env() -> Optional[str]:
    """Return configured SQLite graph database path from environment, or ``None``."""
    raw = os.environ.get("SEMANTICA_GRAPH_DB_PATH")
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _cypher_str(value: Any) -> str:
    """Escape an arbitrary value as a single-quoted Cypher string literal."""
    text = "" if value is None else str(value)
    escaped = (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"'{escaped}'"


def _sanitize_cypher_rel_type(edge_type: str) -> str:
    """Convert an arbitrary edge_type string into a valid Cypher relationship identifier."""
    cleaned = _SAFE_CYPHER_LABEL_RE.sub("_", str(edge_type or "related_to").strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "related_to"
    if cleaned[0].isdigit():
        return f"REL_{cleaned}"
    return cleaned


def _serialize_node_properties(node: ContextNode) -> str:
    props = dict(node.properties or {})
    meta = dict(node.metadata or {})
    if props == meta:
        return json.dumps(props, default=str, ensure_ascii=False, sort_keys=True)
    return json.dumps(
        {
            _NODE_ENVELOPE_KEY: 1,
            "properties": props,
            "metadata": meta,
        },
        default=str,
        ensure_ascii=False,
        sort_keys=True,
    )


def _deserialize_node_properties(raw_json: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        parsed = json.loads(raw_json) if raw_json else {}
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, {}
    if _NODE_ENVELOPE_KEY in parsed:
        props = parsed.get("properties")
        meta = parsed.get("metadata")
        return (
            dict(props) if isinstance(props, dict) else {},
            dict(meta) if isinstance(meta, dict) else {},
        )
    return dict(parsed), dict(parsed)


def _serialize_edge_properties(edge: ContextEdge) -> str:
    meta = dict(edge.metadata or {})
    has_extra = (
        edge.valid_from is not None
        or edge.valid_until is not None
        or (edge.family_id is not None and edge.family_id != edge.edge_id)
    )
    if not has_extra:
        return json.dumps(meta, default=str, ensure_ascii=False, sort_keys=True)
    return json.dumps(
        {
            _EDGE_ENVELOPE_KEY: 1,
            "metadata": meta,
            "family_id": edge.family_id,
            "valid_from": edge.valid_from,
            "valid_until": edge.valid_until,
        },
        default=str,
        ensure_ascii=False,
        sort_keys=True,
    )


def _deserialize_edge_properties(
    raw_json: str, edge_key: str
) -> Tuple[Dict[str, Any], str, Optional[str], Optional[str]]:
    try:
        parsed = json.loads(raw_json) if raw_json else {}
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, edge_key, None, None
    if _EDGE_ENVELOPE_KEY in parsed:
        meta = parsed.get("metadata")
        family_id = parsed.get("family_id") or edge_key
        valid_from = parsed.get("valid_from")
        valid_until = parsed.get("valid_until")
        return (
            dict(meta) if isinstance(meta, dict) else {},
            str(family_id),
            str(valid_from) if valid_from is not None else None,
            str(valid_until) if valid_until is not None else None,
        )
    return dict(parsed), edge_key, None, None


class WorkspaceGraphStore:
    """Thread-safe SQLite WAL store for multi-workspace ContextGraph persistence."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._closed = False

        if self.db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_meta (
                    workspace_id TEXT PRIMARY KEY,
                    graph_key TEXT NOT NULL,
                    seeded INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_nodes (
                    workspace_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, node_id)
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_edges (
                    workspace_id TEXT NOT NULL,
                    edge_key TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    properties_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, edge_key)
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_nodes_ws ON workspace_nodes(workspace_id);"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_edges_ws ON workspace_edges(workspace_id);"
            )

    def close(self) -> None:
        """Flush WAL and close the SQLite connection."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self.db_path != ":memory:":
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except Exception:
                pass
            self._conn.close()

    def is_initialized(self, ws_id: str) -> bool:
        """Return ``True`` if *ws_id* has an initialized record in ``workspace_meta``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM workspace_meta WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            return row is not None

    def get_workspace_meta(self, ws_id: str) -> Optional[Dict[str, Any]]:
        """Return metadata dictionary for *ws_id*, or ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT workspace_id, graph_key, seeded, created_at, updated_at "
                "FROM workspace_meta WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_workspaces(self) -> List[str]:
        """Return all persisted workspace IDs sorted alphabetically."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT workspace_id FROM workspace_meta ORDER BY workspace_id"
            ).fetchall()
            return [str(row["workspace_id"]) for row in rows]

    def count_entities(self, ws_id: str) -> Tuple[int, int]:
        """Return ``(node_count, edge_count)`` stored in SQLite for *ws_id*."""
        with self._lock:
            n_row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM workspace_nodes WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            e_row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM workspace_edges WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            return int(n_row["cnt"] if n_row else 0), int(e_row["cnt"] if e_row else 0)

    def ensure_workspace_meta(
        self, ws_id: str, graph_key: str, seeded: Optional[bool] = None
    ) -> None:
        now = _utc_now_iso()
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT seeded FROM workspace_meta WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO workspace_meta (workspace_id, graph_key, seeded, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ws_id, graph_key, 1 if seeded else 0, now, now),
                )
            else:
                seeded_val = int(existing["seeded"]) if seeded is None else (1 if seeded else 0)
                self._conn.execute(
                    """
                    UPDATE workspace_meta
                    SET graph_key = ?, seeded = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (graph_key, seeded_val, now, ws_id),
                )

    def load_into_context_graph(self, ws_id: str, graph: ContextGraph) -> Tuple[int, int]:
        """Hydrate *graph* with all persisted nodes and edges for *ws_id*."""
        with self._lock:
            node_rows = self._conn.execute(
                """
                SELECT node_id, node_type, content, properties_json, valid_from, valid_until
                FROM workspace_nodes
                WHERE workspace_id = ?
                ORDER BY node_id
                """,
                (ws_id,),
            ).fetchall()
            edge_rows = self._conn.execute(
                """
                SELECT edge_key, source_id, target_id, edge_type, weight, properties_json
                FROM workspace_edges
                WHERE workspace_id = ?
                ORDER BY edge_key
                """,
                (ws_id,),
            ).fetchall()

        prev_suspend = getattr(graph, "_suspend_mutation_callback", False)
        graph._suspend_mutation_callback = True
        try:
            graph.clear()
            nodes_loaded = 0
            for row in node_rows:
                props, meta = _deserialize_node_properties(row["properties_json"])
                node = ContextNode(
                    node_id=str(row["node_id"]),
                    node_type=str(row["node_type"] or "entity"),
                    content=str(row["content"] or ""),
                    properties=props,
                    metadata=meta,
                    valid_from=row["valid_from"],
                    valid_until=row["valid_until"],
                )
                if graph._add_internal_node(node):
                    nodes_loaded += 1
                    if node.node_type.lower() == "decision" and hasattr(
                        graph, "_sync_decision_from_node"
                    ):
                        try:
                            graph._sync_decision_from_node(node.node_id)
                        except Exception:
                            logger.debug(
                                "Skipping decision index sync on restore for node %s",
                                node.node_id,
                            )

            edges_loaded = 0
            for row in edge_rows:
                edge_key = str(row["edge_key"])
                meta, family_id, valid_from, valid_until = _deserialize_edge_properties(
                    row["properties_json"], edge_key
                )
                edge = ContextEdge(
                    source_id=str(row["source_id"]),
                    target_id=str(row["target_id"]),
                    edge_type=str(row["edge_type"] or "related_to"),
                    edge_id=edge_key,
                    family_id=family_id,
                    weight=float(row["weight"] if row["weight"] is not None else 1.0),
                    metadata=meta,
                    valid_from=valid_from,
                    valid_until=valid_until,
                )
                if graph._add_internal_edge(edge):
                    edges_loaded += 1
        finally:
            graph._suspend_mutation_callback = prev_suspend

        return nodes_loaded, edges_loaded

    def save_context_graph(
        self,
        ws_id: str,
        graph_key: str,
        graph: ContextGraph,
        seeded: Optional[bool] = None,
    ) -> Tuple[int, int]:
        """Atomically synchronize all nodes and edges of *graph* into SQLite."""
        now = _utc_now_iso()
        with graph._lock:
            raw_nodes = [n for n in graph.nodes.values() if n is not None]
            raw_edges = [e for e in graph.edges if e is not None]

        node_params = [
            (
                ws_id,
                str(node.node_id),
                str(node.node_type or "entity"),
                str(node.content if node.content is not None else ""),
                _serialize_node_properties(node),
                node.valid_from,
                node.valid_until,
                now,
            )
            for node in raw_nodes
        ]

        seen_edge_keys = set()
        edge_params = []
        for edge in raw_edges:
            edge_key = str(edge.edge_id)
            if edge_key in seen_edge_keys:
                continue
            seen_edge_keys.add(edge_key)
            edge_params.append(
                (
                    ws_id,
                    edge_key,
                    str(edge.source_id),
                    str(edge.target_id),
                    str(edge.edge_type or "related_to"),
                    float(edge.weight if edge.weight is not None else 1.0),
                    _serialize_edge_properties(edge),
                    now,
                )
            )

        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT seeded FROM workspace_meta WHERE workspace_id = ?",
                (ws_id,),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO workspace_meta (workspace_id, graph_key, seeded, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ws_id, graph_key, 1 if seeded else 0, now, now),
                )
            else:
                seeded_val = int(existing["seeded"]) if seeded is None else (1 if seeded else 0)
                self._conn.execute(
                    """
                    UPDATE workspace_meta
                    SET graph_key = ?, seeded = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (graph_key, seeded_val, now, ws_id),
                )

            self._conn.execute(
                "DELETE FROM workspace_nodes WHERE workspace_id = ?",
                (ws_id,),
            )
            self._conn.execute(
                "DELETE FROM workspace_edges WHERE workspace_id = ?",
                (ws_id,),
            )

            if node_params:
                self._conn.executemany(
                    """
                    INSERT INTO workspace_nodes (
                        workspace_id, node_id, node_type, content,
                        properties_json, valid_from, valid_until, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    node_params,
                )
            if edge_params:
                self._conn.executemany(
                    """
                    INSERT INTO workspace_edges (
                        workspace_id, edge_key, source_id, target_id,
                        edge_type, weight, properties_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    edge_params,
                )

        return len(node_params), len(edge_params)

    def upsert_node(self, ws_id: str, graph_key: str, node: ContextNode) -> None:
        """Insert or update a single node in SQLite."""
        now = _utc_now_iso()
        props_json = _serialize_node_properties(node)
        with self._lock, self._conn:
            self.ensure_workspace_meta(ws_id, graph_key)
            self._conn.execute(
                """
                INSERT INTO workspace_nodes (
                    workspace_id, node_id, node_type, content,
                    properties_json, valid_from, valid_until, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, node_id) DO UPDATE SET
                    node_type = excluded.node_type,
                    content = excluded.content,
                    properties_json = excluded.properties_json,
                    valid_from = excluded.valid_from,
                    valid_until = excluded.valid_until,
                    updated_at = excluded.updated_at
                """,
                (
                    ws_id,
                    str(node.node_id),
                    str(node.node_type or "entity"),
                    str(node.content if node.content is not None else ""),
                    props_json,
                    node.valid_from,
                    node.valid_until,
                    now,
                ),
            )

    def delete_node(self, ws_id: str, node_id: str) -> None:
        """Delete a node and any incident edges from SQLite."""
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM workspace_edges WHERE workspace_id = ? AND (source_id = ? OR target_id = ?)",
                (ws_id, node_id, node_id),
            )
            self._conn.execute(
                "DELETE FROM workspace_nodes WHERE workspace_id = ? AND node_id = ?",
                (ws_id, node_id),
            )
            self._conn.execute(
                "UPDATE workspace_meta SET updated_at = ? WHERE workspace_id = ?",
                (now, ws_id),
            )

    def upsert_edge(self, ws_id: str, graph_key: str, edge: ContextEdge) -> None:
        """Insert or update a single edge in SQLite."""
        now = _utc_now_iso()
        props_json = _serialize_edge_properties(edge)
        with self._lock, self._conn:
            self.ensure_workspace_meta(ws_id, graph_key)
            self._conn.execute(
                """
                INSERT INTO workspace_edges (
                    workspace_id, edge_key, source_id, target_id,
                    edge_type, weight, properties_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, edge_key) DO UPDATE SET
                    source_id = excluded.source_id,
                    target_id = excluded.target_id,
                    edge_type = excluded.edge_type,
                    weight = excluded.weight,
                    properties_json = excluded.properties_json,
                    updated_at = excluded.updated_at
                """,
                (
                    ws_id,
                    str(edge.edge_id),
                    str(edge.source_id),
                    str(edge.target_id),
                    str(edge.edge_type or "related_to"),
                    float(edge.weight if edge.weight is not None else 1.0),
                    props_json,
                    now,
                ),
            )

    def delete_edge(self, ws_id: str, edge_key: str) -> None:
        """Delete a single edge from SQLite."""
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM workspace_edges WHERE workspace_id = ? AND edge_key = ?",
                (ws_id, edge_key),
            )
            self._conn.execute(
                "UPDATE workspace_meta SET updated_at = ? WHERE workspace_id = ?",
                (now, ws_id),
            )


class FalkorDBSyncBridge:
    """Zero-dependency RESP2 TCP client mirroring workspace graphs into FalkorDB.

    Active when ``host`` is explicitly supplied or ``FALKORDB_HOST`` is set in
    the environment. Socket failures are non-fatal and guarded by a short retry
    cooldown so offline environments (e.g. unit tests) never stall.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: float = 1.5,
        cooldown_seconds: float = 5.0,
    ) -> None:
        raw_host = host if host is not None else os.environ.get("FALKORDB_HOST")
        cleaned_host = raw_host.strip() if isinstance(raw_host, str) else ""
        self.enabled: bool = bool(cleaned_host)
        self.host: str = cleaned_host

        if port is not None:
            resolved_port = int(port)
        else:
            env_port = os.environ.get("FALKORDB_PORT", "6379")
            try:
                resolved_port = int(env_port)
            except (TypeError, ValueError):
                resolved_port = 6379
        self.port: int = resolved_port
        self.timeout: float = timeout
        self.cooldown_seconds: float = cooldown_seconds
        self._lock = threading.RLock()
        self._cooldown_until: float = 0.0
        self._last_error: Optional[str] = None

    @staticmethod
    def encode_resp_command(args: Sequence[str]) -> bytes:
        """Serialize a command list as a RESP2 bulk-string array."""
        parts: List[bytes] = [f"*{len(args)}\r\n".encode("ascii")]
        for arg in args:
            encoded = str(arg).encode("utf-8")
            parts.append(f"${len(encoded)}\r\n".encode("ascii"))
            parts.append(encoded)
            parts.append(b"\r\n")
        return b"".join(parts)

    @classmethod
    def read_resp_reply(cls, fp: Any) -> Any:
        """Read and decode a single framed RESP2 reply from buffered binary stream *fp*."""
        header = fp.readline()
        if not header:
            raise ConnectionError("Unexpected EOF reading RESP2 reply from FalkorDB")
        prefix = header[:1]
        payload = header[1:].rstrip(b"\r\n")

        if prefix == b"+":
            return payload.decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RuntimeError(payload.decode("utf-8", errors="replace"))
        if prefix == b":":
            return int(payload)
        if prefix == b"$":
            length = int(payload)
            if length < 0:
                return None
            data = fp.read(length)
            if len(data) < length:
                raise ConnectionError("Truncated bulk string in RESP2 reply")
            # Consume trailing CRLF
            fp.read(2)
            return data.decode("utf-8", errors="replace")
        if prefix == b"*":
            count = int(payload)
            if count < 0:
                return None
            return [cls.read_resp_reply(fp) for _ in range(count)]
        raise ValueError(f"Unsupported RESP2 prefix byte: {prefix!r}")

    def execute_commands(
        self,
        commands: Sequence[Sequence[str]],
        *,
        bypass_cooldown: bool = False,
    ) -> Optional[List[Any]]:
        """Execute a sequence of RESP2 commands over one socket connection."""
        if not self.enabled or not commands:
            return None

        with self._lock:
            now = time.monotonic()
            if not bypass_cooldown and now < self._cooldown_until:
                return None

            try:
                with socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                ) as sock:
                    sock.settimeout(self.timeout)
                    with sock.makefile("rb") as reader:
                        replies: List[Any] = []
                        for cmd in commands:
                            sock.sendall(self.encode_resp_command(cmd))
                            replies.append(self.read_resp_reply(reader))
                        self._cooldown_until = 0.0
                        self._last_error = None
                        return replies
            except (OSError, TimeoutError, ConnectionError) as exc:
                self._last_error = str(exc)
                self._cooldown_until = time.monotonic() + self.cooldown_seconds
                logger.warning(
                    "FalkorDB sync skipped (%s:%s unreachable: %s)",
                    self.host,
                    self.port,
                    exc,
                )
                return None
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning(
                    "FalkorDB command failed on %s:%s: %s",
                    self.host,
                    self.port,
                    exc,
                )
                return None

    def ping(self) -> bool:
        """Return ``True`` if FalkorDB is enabled and answers ``PING``."""
        if not self.enabled:
            return False
        replies = self.execute_commands([["PING"]], bypass_cooldown=True)
        return bool(replies and replies[0] == "PONG")

    def query(self, graph_key: str, cypher: str) -> Optional[Any]:
        """Run a single ``GRAPH.QUERY <graph_key> <cypher>`` command."""
        replies = self.execute_commands([["GRAPH.QUERY", graph_key, cypher]])
        return replies[0] if replies else None

    def sync_full_graph(self, graph_key: str, graph: ContextGraph) -> bool:
        """Mirror the entire *graph* into the physical FalkorDB graph *graph_key*."""
        if not self.enabled:
            return False

        with graph._lock:
            nodes = [n for n in graph.nodes.values() if n is not None]
            edges = [e for e in graph.edges if e is not None]

        commands: List[List[str]] = [
            ["GRAPH.QUERY", graph_key, "MATCH (n) DETACH DELETE n"]
        ]

        chunk_size = 100
        for idx in range(0, len(nodes), chunk_size):
            chunk = nodes[idx : idx + chunk_size]
            items = []
            for node in chunk:
                props_json = _serialize_node_properties(node)
                items.append(
                    "{"
                    f"id: {_cypher_str(node.node_id)}, "
                    f"type: {_cypher_str(node.node_type or 'entity')}, "
                    f"content: {_cypher_str(node.content or '')}, "
                    f"properties_json: {_cypher_str(props_json)}, "
                    f"valid_from: {_cypher_str(node.valid_from or '')}, "
                    f"valid_until: {_cypher_str(node.valid_until or '')}"
                    "}"
                )
            cypher = (
                f"UNWIND [{', '.join(items)}] AS row "
                "MERGE (n:Entity {id: row.id}) "
                "SET n.type = row.type, "
                "n.content = row.content, "
                "n.properties_json = row.properties_json, "
                "n.valid_from = row.valid_from, "
                "n.valid_until = row.valid_until"
            )
            commands.append(["GRAPH.QUERY", graph_key, cypher])

        edges_by_label: Dict[str, List[ContextEdge]] = defaultdict(list)
        seen_edge_ids = set()
        for edge in edges:
            if edge.edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge.edge_id)
            edges_by_label[_sanitize_cypher_rel_type(edge.edge_type)].append(edge)

        for rel_label, rel_edges in edges_by_label.items():
            for idx in range(0, len(rel_edges), chunk_size):
                chunk = rel_edges[idx : idx + chunk_size]
                items = []
                for edge in chunk:
                    props_json = _serialize_edge_properties(edge)
                    weight_val = float(edge.weight if edge.weight is not None else 1.0)
                    items.append(
                        "{"
                        f"id: {_cypher_str(edge.edge_id)}, "
                        f"source: {_cypher_str(edge.source_id)}, "
                        f"target: {_cypher_str(edge.target_id)}, "
                        f"type: {_cypher_str(edge.edge_type or 'related_to')}, "
                        f"weight: {weight_val}, "
                        f"properties_json: {_cypher_str(props_json)}"
                        "}"
                    )
                cypher = (
                    f"UNWIND [{', '.join(items)}] AS row "
                    "MATCH (s:Entity {id: row.source}), (t:Entity {id: row.target}) "
                    f"MERGE (s)-[r:{rel_label} {{id: row.id}}]->(t) "
                    "SET r.type = row.type, "
                    "r.weight = row.weight, "
                    "r.properties_json = row.properties_json"
                )
                commands.append(["GRAPH.QUERY", graph_key, cypher])

        return self.execute_commands(commands) is not None

    def upsert_node(self, graph_key: str, node: ContextNode) -> bool:
        if not self.enabled:
            return False
        props_json = _serialize_node_properties(node)
        cypher = (
            f"MERGE (n:Entity {{id: {_cypher_str(node.node_id)}}}) "
            f"SET n.type = {_cypher_str(node.node_type or 'entity')}, "
            f"n.content = {_cypher_str(node.content or '')}, "
            f"n.properties_json = {_cypher_str(props_json)}, "
            f"n.valid_from = {_cypher_str(node.valid_from or '')}, "
            f"n.valid_until = {_cypher_str(node.valid_until or '')}"
        )
        return self.query(graph_key, cypher) is not None

    def delete_node(self, graph_key: str, node_id: str) -> bool:
        if not self.enabled:
            return False
        cypher = f"MATCH (n:Entity {{id: {_cypher_str(node_id)}}}) DETACH DELETE n"
        return self.query(graph_key, cypher) is not None

    def upsert_edge(self, graph_key: str, edge: ContextEdge) -> bool:
        if not self.enabled:
            return False
        rel_label = _sanitize_cypher_rel_type(edge.edge_type)
        props_json = _serialize_edge_properties(edge)
        weight_val = float(edge.weight if edge.weight is not None else 1.0)
        cypher = (
            f"MERGE (s:Entity {{id: {_cypher_str(edge.source_id)}}}) "
            f"MERGE (t:Entity {{id: {_cypher_str(edge.target_id)}}}) "
            f"MERGE (s)-[r:{rel_label} {{id: {_cypher_str(edge.edge_id)}}}]->(t) "
            f"SET r.type = {_cypher_str(edge.edge_type or 'related_to')}, "
            f"r.weight = {weight_val}, "
            f"r.properties_json = {_cypher_str(props_json)}"
        )
        return self.query(graph_key, cypher) is not None

    def delete_edge(self, graph_key: str, edge_key: str) -> bool:
        if not self.enabled:
            return False
        cypher = f"MATCH ()-[r {{id: {_cypher_str(edge_key)}}}]->() DELETE r"
        return self.query(graph_key, cypher) is not None


class WorkspacePersistenceAdapter:
    """Per-workspace persistence coordinator bound to a ``GraphSession``."""

    def __init__(
        self,
        ws_id: str,
        graph_key: str,
        store: Optional[WorkspaceGraphStore] = None,
        falkor_bridge: Optional[FalkorDBSyncBridge] = None,
    ) -> None:
        self.ws_id = ws_id
        self.graph_key = graph_key
        self.store = store
        self.falkor_bridge = falkor_bridge

    def sync_graph(self, graph: ContextGraph, seeded: Optional[bool] = None) -> None:
        """Persist the full *graph* state to SQLite and FalkorDB."""
        if self.store is not None:
            self.store.save_context_graph(
                self.ws_id, self.graph_key, graph, seeded=seeded
            )
        if self.falkor_bridge is not None and self.falkor_bridge.enabled:
            self.falkor_bridge.sync_full_graph(self.graph_key, graph)

    def on_mutation(
        self,
        graph: ContextGraph,
        event_type: str,
        entity_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Persist a single incremental ``ContextGraph`` mutation."""
        normalized = str(event_type or "").upper()

        if normalized in {"ADD_NODE", "UPDATE_NODE"}:
            with graph._lock:
                node = graph.nodes.get(entity_id)
            if node is not None:
                if self.store is not None:
                    self.store.upsert_node(self.ws_id, self.graph_key, node)
                if self.falkor_bridge is not None and self.falkor_bridge.enabled:
                    self.falkor_bridge.upsert_node(self.graph_key, node)
        elif normalized in {"REMOVE_NODE", "DELETE_NODE"}:
            if self.store is not None:
                self.store.delete_node(self.ws_id, entity_id)
            if self.falkor_bridge is not None and self.falkor_bridge.enabled:
                self.falkor_bridge.delete_node(self.graph_key, entity_id)
        elif normalized in {"ADD_EDGE", "UPDATE_EDGE"}:
            with graph._lock:
                edge = graph._edge_index.get(entity_id)
                src_node = graph.nodes.get(edge.source_id) if edge is not None else None
                tgt_node = graph.nodes.get(edge.target_id) if edge is not None else None
            if edge is not None:
                if self.store is not None:
                    if src_node is not None:
                        self.store.upsert_node(self.ws_id, self.graph_key, src_node)
                    if tgt_node is not None:
                        self.store.upsert_node(self.ws_id, self.graph_key, tgt_node)
                    self.store.upsert_edge(self.ws_id, self.graph_key, edge)
                if self.falkor_bridge is not None and self.falkor_bridge.enabled:
                    if src_node is not None:
                        self.falkor_bridge.upsert_node(self.graph_key, src_node)
                    if tgt_node is not None:
                        self.falkor_bridge.upsert_node(self.graph_key, tgt_node)
                    self.falkor_bridge.upsert_edge(self.graph_key, edge)
        elif normalized in {"REMOVE_EDGE", "DELETE_EDGE"}:
            if self.store is not None:
                self.store.delete_edge(self.ws_id, entity_id)
            if self.falkor_bridge is not None and self.falkor_bridge.enabled:
                self.falkor_bridge.delete_edge(self.graph_key, entity_id)
        elif normalized in {"RELOAD_GRAPH", "RESET_GRAPH"}:
            self.sync_graph(graph)
