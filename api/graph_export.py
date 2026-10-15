"""Build a render-ready graph from the actual RingTrace tool outputs."""
from __future__ import annotations

from typing import Any


def build_graph_export(account_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add_node(node_id: Any, node_type: str, label: Any = None, **properties: Any) -> str | None:
        if node_id is None or str(node_id) == "":
            return None
        key = str(node_id)
        current = nodes.get(key, {"id": key, "type": node_type, "label": str(label or key), "properties": {}})
        # Preserve more specific classifications (target/leader) when later
        # evidence adds a generic account reference.
        priority = {"account": 0, "ring_member": 1, "ring_leader": 2, "target": 3}
        if priority.get(node_type, 0) > priority.get(current["type"], 0):
            current["type"] = node_type
        if label:
            current["label"] = str(label)
        current["properties"].update({k: v for k, v in properties.items() if v is not None})
        nodes[key] = current
        return key

    def add_edge(source: Any, target: Any, edge_type: str, label: str | None = None, **properties: Any) -> None:
        source_id = add_node(source, "account")
        target_id = add_node(target, "account")
        if source_id is None or target_id is None:
            return
        edge_label = label or edge_type.replace("_", " ").lower()
        key = (source_id, target_id, edge_type, edge_label)
        edge = edges.get(key, {
            "id": f"{source_id}|{target_id}|{edge_type}|{edge_label}",
            "source": source_id,
            "target": target_id,
            "type": edge_type,
            "label": edge_label,
            "properties": {},
        })
        edge["properties"].update({k: v for k, v in properties.items() if v is not None})
        edges[key] = edge

    add_node(account_id, "target", is_target=True)
    by_tool = {step.get("tool"): step.get("data") or {} for step in steps if step.get("ok")}
    context = by_tool.get("get_account_context", {})
    account = context.get("account") or {}
    account_key = add_node(account.get("id") or account_id, "target", account.get("id") or account_id, **account)

    owner = context.get("owner")
    if isinstance(owner, dict) and owner.get("id"):
        owner_id = add_node(owner["id"], "person", owner.get("name") or owner["id"], **owner)
        add_edge(owner_id, account_key, "OWNS", "owns")

    for row in context.get("devices") or []:
        if not isinstance(row, dict):
            continue
        device_id = add_node(row.get("id"), "device", row.get("id"), **row)
        add_edge(account_key, device_id, "USES_DEVICE", "device")
    for row in context.get("ips") or []:
        if not isinstance(row, dict):
            continue
        ip_id = add_node(row.get("id"), "ip", row.get("address") or row.get("id"), **row)
        add_edge(account_key, ip_id, "LOGGED_FROM", "IP")
    for row in context.get("brokers") or []:
        if not isinstance(row, dict):
            continue
        broker_id = add_node(row.get("id"), "broker", row.get("name") or row.get("id"), **row)
        add_edge(account_key, broker_id, "ROUTED_THROUGH", "broker")
    for row in context.get("alerts") or []:
        if not isinstance(row, dict):
            continue
        alert_id = add_node(row.get("id"), "alert", row.get("reason") or row.get("id"), **row)
        add_edge(alert_id, account_key, "FLAGS", "alert")

    for item in context.get("outgoing_transfers") or []:
        if isinstance(item, dict) and item.get("to"):
            add_edge(account_key, item["to"], "TRANSFERRED_TO", "transfer", amount=item.get("amount"), timestamp=item.get("timestamp"))
    for item in context.get("incoming_transfers") or []:
        if isinstance(item, dict) and item.get("from"):
            add_edge(item["from"], account_key, "TRANSFERRED_TO", "transfer", amount=item.get("amount"), timestamp=item.get("timestamp"))
    for item in context.get("merchant_purchases") or []:
        if not isinstance(item, dict) or not item.get("merchant_id"):
            continue
        merchant_id = add_node(item["merchant_id"], "merchant", item.get("merchant_name") or item["merchant_id"], **item)
        add_edge(account_key, merchant_id, "PURCHASED_AT", "merchant purchase", amount=item.get("amount"), timestamp=item.get("timestamp"))

    ring = by_tool.get("find_fraud_ring", {})
    for member in ring.get("members") or []:
        add_node(member, "ring_member", member, component_id=ring.get("component_id"))
    for item in ring.get("member_summary") or []:
        if isinstance(item, dict):
            add_node(item.get("id"), "ring_member", item.get("id"), status=item.get("status"), account_type=item.get("account_type"), country=item.get("country"), alert_count=item.get("alert_count"))
    for item in ring.get("edges") or []:
        if isinstance(item, dict):
            add_edge(item.get("source"), item.get("target"), "LINKED_TO", item.get("via") or "identity link", via=item.get("via"), ref=item.get("ref"), weight=item.get("weight"), is_ring=True)

    ranking = by_tool.get("rank_ring_leaders", {})
    leader_id = ranking.get("ring_leader")
    for row in ranking.get("ranking") or []:
        if not isinstance(row, dict):
            continue
        node_id = row.get("account_id")
        node_type = "ring_leader" if node_id == leader_id else "ring_member"
        add_node(node_id, node_type, node_id, pagerank_money=row.get("pagerank_money"), pagerank_identity=row.get("pagerank_identity"))

    for path in (by_tool.get("trace_money_path", {}).get("paths") or []):
        if not isinstance(path, dict):
            continue
        accounts = path.get("accounts") or []
        transfers = path.get("transfers") or []
        for node_id in accounts:
            add_node(node_id, "ring_member", node_id)
        for index, (source, target) in enumerate(zip(accounts, accounts[1:])):
            detail = transfers[index] if index < len(transfers) and isinstance(transfers[index], dict) else {}
            add_edge(source, target, "TRANSFERRED_TO", "money path", amount=detail.get("amount"), timestamp=detail.get("timestamp"), txn_id=detail.get("txn_id"), is_path=True, hops=path.get("hops"))
        if path.get("broker_id"):
            broker_id = add_node(path["broker_id"], "broker", path["broker_id"])
            if accounts:
                add_edge(accounts[-1], broker_id, "ROUTED_THROUGH", "broker cash-out", is_path=True)

    identity = by_tool.get("find_identity_links", {})
    link_groups = (
        ("shared_devices", "device_id", "device_type", "device", "USES_DEVICE"),
        ("shared_ips", "ip_id", "address", "ip", "LOGGED_FROM"),
        ("shared_owners", "person_id", "person_name", "person", "OWNS"),
        ("shared_brokers", "broker_id", "broker_name", "broker", "ROUTED_THROUGH"),
    )
    for group_key, id_key, label_key, node_type, rel_type in link_groups:
        for row in identity.get(group_key) or []:
            if not isinstance(row, dict):
                continue
            link_id = row.get(id_key)
            label = row.get(label_key) or link_id
            link_node = add_node(link_id, node_type, label, **{k: v for k, v in row.items() if k != "other_accounts"})
            linked_accounts = set(row.get("other_accounts") or [])
            for linked in linked_accounts:
                add_node(linked, "ring_member", linked)
                if node_type == "person":
                    add_edge(link_node, linked, rel_type, "shared owner", is_identity_link=True)
                else:
                    add_edge(linked, link_node, rel_type, f"shared {node_type}", is_identity_link=True)

    if leader_id:
        add_node(leader_id, "ring_leader", leader_id)
    return {
        "account_id": account_id,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "stats": {"nodes": len(nodes), "edges": len(edges)},
        "source": "FalkorDB-backed RingTrace investigation tool outputs",
    }
