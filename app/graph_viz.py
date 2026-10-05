"""
app/graph_viz.py
------------------
Builds an interactive Pyvis network visualization of one investigation:
the fraud-ring component, the shared devices/IPs that link its members, and
the traced money path — all pulled directly from the agent's own tool
outputs (not re-queried), so what you see on screen is exactly the evidence
the agent reasoned over.

NetworkX is used here ONLY to compute a force-directed layout before handing
nodes/edges to Pyvis — it plays no role in any investigative decision.
"""
from __future__ import annotations

from typing import Any, Optional

import networkx as nx
from pyvis.network import Network

COLOR_TARGET = "#2563eb"      # blue — the account under investigation
COLOR_LEADER = "#f59e0b"      # gold — likely ring leader
COLOR_MEMBER = "#93c5fd"      # light blue — other ring members
COLOR_ALERTED = "#ef4444"     # red border — has an open alert
COLOR_DEVICE = "#f97316"      # orange — Device node
COLOR_IP = "#8b5cf6"          # purple — IP node
COLOR_BROKER = "#6b7280"      # gray — Broker node
COLOR_LEGIT = "#10b981"       # green — low-risk / legit account


def _find_step(steps: list[dict], tool_name: str) -> Optional[dict]:
    for s in reversed(steps):
        if s.get("tool") == tool_name and s.get("ok"):
            return s
    return None


def build_investigation_network(account_id: str, steps: list[dict], verdict: dict) -> str:
    """Returns a self-contained HTML string for the investigation graph."""
    ring_step = _find_step(steps, "find_fraud_ring")
    identity_step = _find_step(steps, "find_identity_links")
    context_step = _find_step(steps, "get_account_context")
    money_steps = [s for s in steps if s.get("tool") == "trace_money_path" and s.get("ok")]

    ring_data = (ring_step or {}).get("data") or {}
    members = ring_data.get("members", [account_id])
    ring_edges = ring_data.get("edges", [])
    ring_leader = verdict.get("ring_leader")

    has_own_alert = bool((context_step or {}).get("data", {}).get("alerts"))

    g = nx.DiGraph()
    for m in members:
        g.add_node(m, kind="account")

    for e in ring_edges:
        g.add_edge(e["source"], e["target"], via=e.get("via", ""), kind="linked")

    identity_data = (identity_step or {}).get("data") or {}
    for d in identity_data.get("shared_devices", []):
        dev_id = f"DEV::{d['device_id']}"
        g.add_node(dev_id, kind="device", label=d["device_id"])
        g.add_edge(account_id, dev_id, kind="identity")
        for other in d.get("other_accounts", []):
            g.add_node(other, kind="account")
            g.add_edge(other, dev_id, kind="identity")

    for ip in identity_data.get("shared_ips", []):
        ip_id = f"IP::{ip['ip_id']}"
        g.add_node(ip_id, kind="ip", label=ip["ip_id"])
        g.add_edge(account_id, ip_id, kind="identity")
        for other in ip.get("other_accounts", []):
            g.add_node(other, kind="account")
            g.add_edge(other, ip_id, kind="identity")

    money_path_edges: set[tuple[str, str]] = set()
    money_path_amounts: dict[tuple[str, str], float] = {}
    for ms in money_steps:
        for p in (ms.get("data") or {}).get("paths", []):
            accs = p["accounts"]
            transfers = p.get("transfers", [])
            for i in range(len(accs) - 1):
                a, b = accs[i], accs[i + 1]
                g.add_node(a, kind="account")
                g.add_node(b, kind="account")
                money_path_edges.add((a, b))
                if i < len(transfers):
                    money_path_amounts[(a, b)] = transfers[i].get("amount")

    net = Network(height="560px", width="100%", directed=True, bgcolor="#0f172a", font_color="#e2e8f0")
    net.barnes_hut(gravity=-4000, central_gravity=0.3, spring_length=140, spring_strength=0.02, damping=0.9)

    for node, attrs in g.nodes(data=True):
        kind = attrs.get("kind", "account")
        if kind == "device":
            net.add_node(node, label=attrs.get("label", node), shape="diamond", color=COLOR_DEVICE, size=18)
        elif kind == "ip":
            net.add_node(node, label=attrs.get("label", node), shape="square", color=COLOR_IP, size=18)
        else:
            if node == account_id:
                color = COLOR_TARGET
                size = 30
            elif node == ring_leader:
                color = COLOR_LEADER
                size = 28
            elif node in members:
                color = COLOR_MEMBER
                size = 20
            else:
                color = COLOR_LEGIT
                size = 16
            border = COLOR_ALERTED if (node == account_id and has_own_alert) else color
            net.add_node(node, label=node, shape="dot", color={"background": color, "border": border},
                         borderWidth=3 if border != color else 1, size=size)

    for u, v, attrs in g.edges(data=True):
        if (u, v) in money_path_edges:
            amt = money_path_amounts.get((u, v))
            label = f"${amt:,.0f}" if amt else "money"
            net.add_edge(u, v, color="#ef4444", width=4, label=label, arrows="to", title="Money transfer")
        elif attrs.get("kind") == "identity":
            net.add_edge(u, v, color="#64748b", width=1, dashes=True, arrows="")
        else:
            label = attrs.get("via", "")
            net.add_edge(u, v, color="#334155", width=1.5, label=label, arrows="")

    net.set_options("""
    {
      "interaction": {"hover": true, "navigationButtons": true},
      "edges": {"smooth": {"type": "dynamic"}}
    }
    """)
    return net.generate_html(notebook=False)
