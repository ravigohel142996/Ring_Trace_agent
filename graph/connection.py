
"""
Thin, defensive FalkorDB connection manager for RingTrace.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse, unquote

from falkordb import FalkorDB

logger = logging.getLogger("ringtrace.graph.connection")

_lock = threading.RLock()
_db: Optional[FalkorDB] = None
_graphs: dict[str, Any] = {}


class GraphConnectionError(RuntimeError):
    """Raised when FalkorDB cannot be reached."""


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
        private_url = os.getenv("FALKORDB_PRIVATE_URL", "").strip()
        tls_value = os.getenv("FALKORDB_TLS", "0").strip()

        if tls_value not in {"0", "1"}:
            raise ValueError("FALKORDB_TLS must be 0 or 1.")

        host = os.getenv("FALKORDB_HOST", "localhost")
        port = int(os.getenv("FALKORDB_PORT", "6379"))
        username = os.getenv("FALKORDB_USERNAME") or None
        password = os.getenv("FALKORDB_PASSWORD") or None
        tls = tls_value == "1"

        if private_url:
            parsed = urlparse(private_url)
            if parsed.scheme not in {"redis", "rediss"}:
                raise ValueError(
                    "FALKORDB_PRIVATE_URL must use redis:// or rediss://."
                )
            if not parsed.hostname:
                raise ValueError("FALKORDB_PRIVATE_URL has no hostname.")

            host = parsed.hostname
            port = parsed.port or 6379
            username = unquote(parsed.username) if parsed.username else username
            password = unquote(parsed.password) if parsed.password else password
            tls = parsed.scheme == "rediss"

        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            graph_name=os.getenv("FALKORDB_GRAPH", "ringtrace"),
            tls=tls,
        )


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _enforce_transport_policy(settings: GraphSettings) -> None:
    host = settings.host.lower().rstrip(".")

    if host in _LOOPBACK_HOSTS:
        return

    if host.endswith(".railway.internal"):
        # Railway private-network traffic is encrypted by WireGuard.
        if not settings.username or not settings.password:
            raise GraphConnectionError(
                "Railway private FalkorDB connections require a username "
                "and password."
            )
        if settings.tls:
            # TLS can be enabled only if the database endpoint supports it.
            return
        return

    # Any other remote endpoint must use TLS and credentials.
    if not settings.tls:
        raise GraphConnectionError(
            "Refusing plaintext connection to a non-private remote host. "
            "Use a Railway private hostname or configure TLS."
        )

    if not settings.username or not settings.password:
        raise GraphConnectionError(
            "Remote FalkorDB endpoints require username and password."
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
            except Exception as exc:
                _db = None
                raise GraphConnectionError(
                    f"Could not connect to FalkorDB at "
                    f"{settings.host}:{settings.port}: {exc}"
                ) from exc
        return _db


def get_graph(graph_name: Optional[str] = None):
    name = graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace")
    with _lock:
        if name not in _graphs:
            db = get_db()
            try:
                _graphs[name] = db.select_graph(name)
            except Exception as exc:
                raise GraphConnectionError(
                    f"Could not select graph '{name}': {exc}"
                ) from exc
        return _graphs[name]


def health_check(
    graph_name: Optional[str] = None,
    retries: int = 1,
    retry_delay: float = 1.0,
) -> dict:
    last_error = None

    for attempt in range(retries + 1):
        try:
            graph = get_graph(graph_name)
            result = graph.query("RETURN 1 AS ok")
            ok = bool(result.result_set) and result.result_set[0][0] == 1

            return {
                "connected": ok,
                "host": os.getenv("FALKORDB_HOST", "configured URL"),
                "port": os.getenv("FALKORDB_PORT", "configured URL"),
                "graph": graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace"),
                "error": None,
            }
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "FalkorDB health check failed (attempt %s): %s",
                attempt + 1,
                last_error,
            )
            if attempt < retries:
                if retry_delay > 0:
                    time.sleep(retry_delay)
                try:
                    get_db(force_reconnect=True)
                except Exception as reconnect_exc:
                    last_error = str(reconnect_exc)
                    logger.warning("FalkorDB reconnect failed: %s", last_error)

    return {
        "connected": False,
        "host": os.getenv("FALKORDB_HOST", "configured URL"),
        "port": os.getenv("FALKORDB_PORT", "configured URL"),
        "graph": graph_name or os.getenv("FALKORDB_GRAPH", "ringtrace"),
        "error": last_error,
    }
