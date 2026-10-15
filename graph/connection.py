"""
graph/connection.py
--------------------
Thin, defensive connection manager around the official `falkordb` Python
client. FalkorDB is the single source of truth for RingTrace — this module
centralizes connection/retry/timeout handling so every tool call fails
gracefully instead of crashing the agent or the dashboard.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from falkordb import FalkorDB

logger = logging.getLogger("ringtrace.graph.connection")

_lock = threading.RLock()
_db: Optional[FalkorDB] = None
_graphs: dict[str, Any] = {}


class GraphConnectionError(RuntimeError):
    """Raised when FalkorDB cannot be reached. Callers should handle this
    gracefully (the agent reports it as a tool failure, never a crash)."""


@dataclass
class GraphSettings:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    graph_name: str
    tls: bool = False
    connect_timeout: float = 5.0
    socket_timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "GraphSettings":
        host = os.getenv("FALKORDB_HOST", "localhost")
        port = int(os.getenv("FALKORDB_PORT", "6379"))
        username = os.getenv("FALKORDB_USERNAME") or None
        password = os.getenv("FALKORDB_PASSWORD") or None
        graph_name = os.getenv("FALKORDB_GRAPH", "ringtrace")
        tls_value = os.getenv("FALKORDB_TLS", "0").strip()
        if tls_value not in {"0", "1"}:
            raise ValueError("FALKORDB_TLS must be 0 or 1.")
        tls = tls_value == "1"
        return cls(
            host=host, port=port, username=username, password=password,
            graph_name=graph_name, tls=tls,
        )


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Temporary exception for hackathon submission - FalkorDB Cloud free tier
# does not support TLS. REMOVE AFTER HACKATHON and enable TLS.
_HACKATHON_ALLOWED_HOSTS = {
    "r-6jissuruar.instance-llgbmbk00.hc-7up0crkyn.ap-south-1.aws.f2e0a955bb84.cloud"
}


def _enforce_transport_policy(settings: "GraphSettings") -> None:
    """Refuse unencrypted connections to non-loopback hosts.

    The legacy graph path historically defaulted to plaintext on any host.
    Remote endpoints now require TLS plus configured credentials; loopback
    retains its existing local-development behaviour.
    
    TEMPORARY: Specific hackathon demo hosts are allowed without TLS.
    This exception must be removed after the hackathon.
    """
    if settings.host in _LOOPBACK_HOSTS:
        return
    if settings.host in _HACKATHON_ALLOWED_HOSTS:
        # Temporary exception for hackathon - credentials still required
        if not settings.username or not settings.password:
            raise GraphConnectionError(
                f"Remote graph endpoint '{settings.host}' requires configured "
                f"FALKORDB_USERNAME and FALKORDB_PASSWORD."
            )
        return
    if not settings.tls:
        raise GraphConnectionError(
            f"Refusing an unencrypted connection to non-loopback host "
            f"'{settings.host}'. Set FALKORDB_TLS=1 for remote endpoints "
            f"or use a loopback address for local development."
        )
    if not settings.username or not settings.password:
        raise GraphConnectionError(
            f"Remote graph endpoint '{settings.host}' requires configured "
            f"FALKORDB_USERNAME and FALKORDB_PASSWORD."
        )


def _connect(settings: GraphSettings) -> FalkorDB:
    _enforce_transport_policy(settings)
    kwargs: dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "socket_connect_timeout": settings.connect_timeout,
        "socket_timeout": settings.socket_timeout,
    }
    if settings.username:
        kwargs["username"] = settings.username
    if settings.password:
        kwargs["password"] = settings.password
    if settings.tls:
        # FalkorDB delegates these supported options to redis-py. Keep
        # certificate and hostname verification enabled for remote endpoints.
        kwargs["ssl"] = True
        kwargs["ssl_check_hostname"] = True
    return FalkorDB(**kwargs)


def get_db(force_reconnect: bool = False) -> FalkorDB:
    global _db
    with _lock:
        if _db is None or force_reconnect:
            settings = GraphSettings.from_env()
            logger.info(
                "Connecting to FalkorDB at %s:%s (graph=%s)",
                settings.host,
                settings.port,
                settings.graph_name,
            )
            try:
                _db = _connect(settings)
            except Exception as exc:  # pragma: no cover - network failure path
                raise GraphConnectionError(
                    f"Could not connect to FalkorDB at {settings.host}:{settings.port}: {exc}"
                ) from exc
        return _db


def get_graph(graph_name: Optional[str] = None):
    """Return a FalkorDB `Graph` handle (select_graph), cached per name.

    This is the ONLY object the rest of RingTrace uses to reach the graph —
    all Cypher execution flows through `graph.query(...)` on the object
    returned here.
    """
    name = graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace")
    with _lock:
        if name not in _graphs:
            db = get_db()
            try:
                _graphs[name] = db.select_graph(name)
            except Exception as exc:  # pragma: no cover
                raise GraphConnectionError(f"Could not select graph '{name}': {exc}") from exc
        return _graphs[name]


def health_check(graph_name: Optional[str] = None, retries: int = 1, retry_delay: float = 1.0) -> dict:
    """Lightweight health probe used by the dashboard + agent startup.

    Returns a structured dict instead of raising, so the UI can show a clear
    "FalkorDB unreachable" banner rather than crashing.
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            g = get_graph(graph_name)
            result = g.query("RETURN 1 AS ok")
            ok = bool(result.result_set) and result.result_set[0][0] == 1
            return {
                "connected": ok,
                "host": os.getenv("FALKORDB_HOST", "localhost"),
                "port": os.getenv("FALKORDB_PORT", "6379"),
                "graph": graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace"),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.warning("FalkorDB health check failed (attempt %s): %s", attempt + 1, last_error)
            if attempt < retries:
                if retry_delay > 0:
                    time.sleep(retry_delay)
                try:
                    get_db(force_reconnect=True)
                except Exception as reconnect_exc:  # connection can remain down during the retry
                    last_error = str(reconnect_exc)
                    logger.warning("FalkorDB reconnect failed: %s", last_error)
    return {
        "connected": False,
        "host": os.getenv("FALKORDB_HOST", "localhost"),
        "port": os.getenv("FALKORDB_PORT", "6379"),
        "graph": graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace"),
        "error": last_error,
    }
