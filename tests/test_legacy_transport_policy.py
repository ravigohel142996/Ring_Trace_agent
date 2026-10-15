"""Offline regressions for the legacy graph transport-safety policy.

These tests verify that graph/connection.py refuses unencrypted connections
to non-loopback hosts before any network I/O occurs. No real database,
network, or subprocess is involved.
"""
from __future__ import annotations

import pytest

from graph.connection import GraphConnectionError, GraphSettings, _enforce_transport_policy


def test_loopback_plaintext_is_permitted():
    for host in ("127.0.0.1", "localhost", "::1"):
        settings = GraphSettings(
            host=host, port=6379, username=None, password=None,
            graph_name="ringtrace", tls=False,
        )
        _enforce_transport_policy(settings)  # must not raise


def test_remote_plaintext_is_refused():
    settings = GraphSettings(
        host="graph.example.com", port=6379, username=None, password=None,
        graph_name="ringtrace", tls=False,
    )
    with pytest.raises(GraphConnectionError, match="unencrypted"):
        _enforce_transport_policy(settings)


def test_remote_tls_without_credentials_is_refused():
    settings = GraphSettings(
        host="graph.example.com", port=16379, username=None, password=None,
        graph_name="ringtrace", tls=True,
    )
    with pytest.raises(GraphConnectionError, match="USERNAME"):
        _enforce_transport_policy(settings)


def test_remote_tls_with_credentials_is_permitted():
    settings = GraphSettings(
        host="graph.example.com", port=16379, username="demo", password="secret",
        graph_name="ringtrace", tls=True,
    )
    _enforce_transport_policy(settings)  # must not raise


def test_settings_from_env_parses_tls_flag(monkeypatch):
    monkeypatch.setenv("FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("FALKORDB_PORT", "6379")
    monkeypatch.setenv("FALKORDB_TLS", "1")
    monkeypatch.setenv("FALKORDB_USERNAME", "u")
    monkeypatch.setenv("FALKORDB_PASSWORD", "p")
    settings = GraphSettings.from_env()
    assert settings.tls is True


def test_settings_from_env_rejects_invalid_tls_value(monkeypatch):
    monkeypatch.setenv("FALKORDB_TLS", "maybe")
    with pytest.raises(ValueError, match="FALKORDB_TLS"):
        GraphSettings.from_env()
