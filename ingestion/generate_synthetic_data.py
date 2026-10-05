"""
ingestion/generate_synthetic_data.py
-------------------------------------
Configurable synthetic fraud-ring data generator for RingTrace.

*** ALL DATA PRODUCED BY THIS MODULE IS SYNTHETIC. *** It exists only to
demonstrate RingTrace's graph-reasoning pipeline. No real persons, accounts,
devices, IPs, or transactions are represented.

The generator produces two things:

1. A deterministic, hand-authored "demo scenario" (fixed IDs) that reproduces
   the exact investigation narrative described in the RingTrace brief:
      - Alert AL-1027 flags account A1027.
      - A1027 shares Device D77 with 7 other accounts (A1020-A1026).
      - 3 of those accounts (A1020-A1022) also share IP 185.44.12.7.
      - A 5-hop money trail runs A1027 -> A1023 -> A1024 -> A1025 -> A1026 -> A1001.
      - A1001 collects extra inbound transfers (highest PageRank => ring leader)
        and cashes out through a mixer-style Broker.
      - The whole thing forms ONE 9-account weakly-connected component.
   Plus two small reference accounts used by the dashboard's "graph changes
   the decision" demo (Case A = isolated/low-risk, Case B = medium-risk via
   shared identity only, no deep money trail).

2. A configurable, randomly generated population of legitimate background
   accounts/transactions and additional fraud rings following 5 known
   archetypes, controlled entirely by environment variables / CLI flags:
   RING_COUNT, ACCOUNTS_PER_RING, LEGIT_PERSON_COUNT, NORMAL_TRANSACTION_COUNT,
   NOISE_LEVEL, FRAUD_RATIO, RANDOM_SEED.

Ground-truth fraud labels are written ONLY to `data/processed/ground_truth.csv`
for evaluation / ML training. They are never written onto graph nodes, so the
agent can never "cheat" by reading a label — it must infer risk purely from
graph structure, exactly like a real investigator would.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _ts(days_ago: float = 0, hours_ago: float = 0, minutes_ago: float = 0) -> tuple[int, str]:
    dt = NOW - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
    return int(dt.timestamp()), dt.isoformat()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class GeneratorConfig:
    ring_count: int = 5
    accounts_per_ring: int = 8
    legit_person_count: int = 150
    normal_transaction_count: int = 900
    noise_level: float = 0.08
    fraud_ratio: float = 0.12
    random_seed: int = 42

    @classmethod
    def from_env(cls) -> "GeneratorConfig":
        return cls(
            ring_count=int(os.getenv("RING_COUNT", 5)),
            accounts_per_ring=int(os.getenv("ACCOUNTS_PER_RING", 8)),
            legit_person_count=int(os.getenv("LEGIT_PERSON_COUNT", 150)),
            normal_transaction_count=int(os.getenv("NORMAL_TRANSACTION_COUNT", 900)),
            noise_level=float(os.getenv("NOISE_LEVEL", 0.08)),
            fraud_ratio=float(os.getenv("FRAUD_RATIO", 0.12)),
            random_seed=int(os.getenv("RANDOM_SEED", 42)),
        )


# ---------------------------------------------------------------------------
# Dataset container
# ---------------------------------------------------------------------------
@dataclass
class SyntheticDataset:
    persons: list[dict] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    devices: list[dict] = field(default_factory=list)
    ips: list[dict] = field(default_factory=list)
    brokers: list[dict] = field(default_factory=list)
    merchants: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    person_account: list[dict] = field(default_factory=list)   # person_id, account_id
    account_device: list[dict] = field(default_factory=list)   # account_id, device_id
    account_ip: list[dict] = field(default_factory=list)       # account_id, ip_id
    account_broker: list[dict] = field(default_factory=list)   # account_id, broker_id
    alerts: list[dict] = field(default_factory=list)
    ground_truth: list[dict] = field(default_factory=list)      # account_id,is_fraud,ring_id,pattern

    _device_ids: set = field(default_factory=set)
    _ip_ids: set = field(default_factory=set)
    _broker_ids: set = field(default_factory=set)
    _merchant_ids: set = field(default_factory=set)
    _account_ids: set = field(default_factory=set)

    # -- helpers to avoid duplicate inserts ---------------------------------
    def add_device(self, device_id: str, device_type: str, days_ago: float):
        if device_id in self._device_ids:
            return
        self._device_ids.add(device_id)
        ts, iso = _ts(days_ago=days_ago)
        self.devices.append({"id": device_id, "device_type": device_type, "first_seen": ts, "first_seen_iso": iso})

    def add_ip(self, ip_id: str, address: str, geo: str, days_ago: float):
        if ip_id in self._ip_ids:
            return
        self._ip_ids.add(ip_id)
        ts, iso = _ts(days_ago=days_ago)
        self.ips.append({"id": ip_id, "address": address, "geo": geo, "first_seen": ts, "first_seen_iso": iso})

    def add_broker(self, broker_id: str, name: str, broker_type: str, risk_level: str):
        if broker_id in self._broker_ids:
            return
        self._broker_ids.add(broker_id)
        self.brokers.append({"id": broker_id, "name": name, "broker_type": broker_type, "risk_level": risk_level})

    def add_merchant(self, merchant_id: str, name: str, category: str):
        if merchant_id in self._merchant_ids:
            return
        self._merchant_ids.add(merchant_id)
        self.merchants.append({"id": merchant_id, "name": name, "category": category})

    def add_account(self, account_id: str, **props):
        if account_id in self._account_ids:
            return
        self._account_ids.add(account_id)
        row = {"id": account_id, **props}
        self.accounts.append(row)

    def link_device(self, account_id: str, device_id: str):
        self.account_device.append({"account_id": account_id, "device_id": device_id})

    def link_ip(self, account_id: str, ip_id: str):
        self.account_ip.append({"account_id": account_id, "ip_id": ip_id})

    def link_broker(self, account_id: str, broker_id: str):
        self.account_broker.append({"account_id": account_id, "broker_id": broker_id})

    def link_owner(self, person_id: str, account_id: str):
        self.person_account.append({"person_id": person_id, "account_id": account_id})

    def add_transaction(self, txn_id: str, src: str, dst: str, amount: float, days_ago: float,
                         hours_ago: float = 0, minutes_ago: float = 0, channel: str = "transfer",
                         broker_id: Optional[str] = None, merchant_id: Optional[str] = None):
        ts, iso = _ts(days_ago=days_ago, hours_ago=hours_ago, minutes_ago=minutes_ago)
        self.transactions.append({
            "id": txn_id, "from_account": src, "to_account": dst, "amount": round(amount, 2),
            "timestamp": ts, "timestamp_iso": iso, "channel": channel, "status": "COMPLETED",
            "broker_id": broker_id or "", "merchant_id": merchant_id or "",
        })

    def add_alert(self, alert_id: str, account_id: str, reason: str, severity: str, days_ago: float = 0):
        ts, iso = _ts(days_ago=days_ago)
        self.alerts.append({"id": alert_id, "account_id": account_id, "reason": reason,
                             "severity": severity, "created_at": ts, "created_at_iso": iso, "status": "OPEN"})

    def mark_ground_truth(self, account_id: str, is_fraud: bool, ring_id: str, pattern: str):
        self.ground_truth.append({"account_id": account_id, "is_fraud": int(is_fraud),
                                   "ring_id": ring_id, "pattern": pattern})

    # ------------------------------------------------------------------
    def to_csv(self, out_dir: Path = DATA_DIR, processed_dir: Path = PROCESSED_DIR) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

        def write(name: str, rows: list[dict]):
            path = out_dir / name
            if not rows:
                path.write_text("")
                return
            fieldnames = sorted({k for r in rows for k in r.keys()})
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        write("persons.csv", self.persons)
        write("accounts.csv", self.accounts)
        write("devices.csv", self.devices)
        write("ips.csv", self.ips)
        write("brokers.csv", self.brokers)
        write("merchants.csv", self.merchants)
        write("transactions.csv", self.transactions)
        write("person_account.csv", self.person_account)
        write("account_device.csv", self.account_device)
        write("account_ip.csv", self.account_ip)
        write("account_broker.csv", self.account_broker)
        write("alerts.csv", self.alerts)

        gt_path = processed_dir / "ground_truth.csv"
        with open(gt_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["account_id", "is_fraud", "ring_id", "pattern"])
            writer.writeheader()
            writer.writerows(self.ground_truth)


# ---------------------------------------------------------------------------
# 1) DETERMINISTIC DEMO SCENARIO  (always identical, regardless of seed)
# ---------------------------------------------------------------------------
def plant_demo_scenario(ds: SyntheticDataset) -> None:
    """Hand-crafted scenario matching the RingTrace brief's worked example.

    Component under investigation (account A1027) ends up with EXACTLY 9
    accounts: A1020-A1027 (sharing Device D77) + A1001 (the ring leader).
    """
    # --- ring leader + mixer -------------------------------------------------
    ds.add_account("A1001", account_type="checking", status="ACTIVE", country="PA",
                    created_at=_ts(days_ago=400)[0])
    ds.add_broker("BR-MX1", name="QuickSwap Crypto Exchange", broker_type="crypto_mixer", risk_level="HIGH")

    device_id = "D77"
    ds.add_device(device_id, device_type="rooted_android_emulator", days_ago=200)
    ip_id = "IP-185-44-12-7"
    ip_addr = "185.44.12.7"
    ds.add_ip(ip_id, address=ip_addr, geo="Unknown VPN exit (RO)", days_ago=200)

    ring_members = [f"A10{n}" for n in range(20, 28)]  # A1020..A1027
    for i, acc in enumerate(ring_members):
        person_id = f"P-MULE-{acc}"
        ds.persons.append({"id": person_id, "name": f"Synthetic Mule {i+1}", "created_at": _ts(days_ago=60)[0]})
        ds.add_account(acc, account_type="digital_wallet", status="ACTIVE", country="RO",
                        created_at=_ts(days_ago=45 - i)[0])
        ds.link_owner(person_id, acc)
        ds.link_device(acc, device_id)  # all 8 share Device D77
        ds.mark_ground_truth(acc, True, ring_id="RING-DEMO-1", pattern="shared_device_ring")

    # 3 of the 8 also share the same IP (tighter sub-cluster)
    for acc in ring_members[:3]:  # A1020, A1021, A1022
        ds.link_ip(acc, ip_id)

    # 5-hop money trail: A1027 -> A1023 -> A1024 -> A1025 -> A1026 -> A1001
    chain = ["A1027", "A1023", "A1024", "A1025", "A1026", "A1001"]
    base_amount = 9800.0
    for i in range(len(chain) - 1):
        src, dst = chain[i], chain[i + 1]
        txn_id = f"T-DEMO-{i+1:02d}"
        ds.add_transaction(txn_id, src, dst, amount=base_amount * (0.94 ** i), days_ago=2,
                            hours_ago=(len(chain) - i) * 3, channel="instant_transfer")

    # Extra inbound "ring dues" into the leader, boosting its centrality
    ds.add_transaction("T-DEMO-90", "A1020", "A1001", amount=1500.0, days_ago=3, hours_ago=1)
    ds.add_transaction("T-DEMO-91", "A1021", "A1001", amount=2200.0, days_ago=3, hours_ago=4)

    # Ring leader cashes out through the mixer
    ds.link_broker("A1001", "BR-MX1")
    ds.add_transaction("T-DEMO-99", "A1001", "A1001", amount=15000.0, days_ago=1, hours_ago=2,
                        channel="broker_payout", broker_id="BR-MX1")
    ds.mark_ground_truth("A1001", True, ring_id="RING-DEMO-1", pattern="central_mule_leader")

    # The alert that kicks off the canonical demo: "Alert A1027 has been flagged"
    ds.add_alert("AL-1027", "A1027", reason="High-velocity transfer pattern detected by rules engine",
                 severity="HIGH", days_ago=0)

    # ---- Case A: isolated, low-connectivity legit account -------------------
    ds.add_account("A1100", account_type="checking", status="ACTIVE", country="US", created_at=_ts(days_ago=900)[0])
    ds.persons.append({"id": "P-CASEA", "name": "Jordan Reyes (synthetic)", "created_at": _ts(days_ago=900)[0]})
    ds.link_owner("P-CASEA", "A1100")
    ds.add_device("D-CASEA", device_type="iphone", days_ago=900)
    ds.link_device("A1100", "D-CASEA")
    ds.add_ip("IP-CASEA", address="73.12.44.90", geo="Austin, US", days_ago=900)
    ds.link_ip("A1100", "IP-CASEA")
    ds.add_account("A1101", account_type="checking", status="ACTIVE", country="US", created_at=_ts(days_ago=800)[0])
    ds.add_transaction("T-CASEA-1", "A1100", "A1101", amount=42.50, days_ago=10, channel="transfer")
    ds.mark_ground_truth("A1100", False, ring_id="NONE", pattern="legit")

    # ---- Case B: medium risk — identity-linked only, no deep money trail ----
    ds.add_broker("BR-NONE", name="N/A", broker_type="n/a", risk_level="LOW")
    ip_b = "IP-CASEB"
    ds.add_ip(ip_b, address="91.203.44.18", geo="Unknown VPN exit (NL)", days_ago=120)
    case_b_members = [f"A120{n}" for n in range(0, 5)]  # A1200..A1204
    for i, acc in enumerate(case_b_members):
        pid = f"P-CASEB-{i}"
        ds.persons.append({"id": pid, "name": f"Synthetic Account {i}", "created_at": _ts(days_ago=120)[0]})
        ds.add_account(acc, account_type="digital_wallet", status="ACTIVE", country="NL",
                        created_at=_ts(days_ago=120 - i)[0])
        ds.link_owner(pid, acc)
        ds.link_ip(acc, ip_b)
        ds.mark_ground_truth(acc, True, ring_id="RING-DEMO-2", pattern="shared_ip_cluster")
    # only ONE small transaction exists in this cluster — identity link dominates, no layered flow
    ds.add_transaction("T-CASEB-1", "A1200", "A1201", amount=35.0, days_ago=15, channel="transfer")


# ---------------------------------------------------------------------------
# 2) CONFIGURABLE BACKGROUND POPULATION
# ---------------------------------------------------------------------------
FIRST_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Jamie", "Avery", "Quinn",
               "Drew", "Reese", "Skyler", "Rowan", "Elliot", "Hayden", "Parker", "Dakota", "Emerson", "Finley"]
LAST_NAMES = ["Smith", "Johnson", "Garcia", "Chen", "Patel", "Kim", "Nguyen", "Brown", "Davis", "Lopez",
              "Martin", "Walker", "Young", "Hall", "Allen", "King", "Wright", "Hill", "Baker", "Nelson"]
COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU", "IN", "SG"]


def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def generate_legit_population(ds: SyntheticDataset, cfg: GeneratorConfig, rng: random.Random,
                               id_start: int = 2000) -> list[str]:
    """Generates legitimate accounts grouped into small, realistic "social /
    commercial circles" (like real payment graphs: people mostly transact
    within their own circle of contacts, merchants, and family). This
    deliberately avoids an unrealistic single giant random graph where every
    legit account ends up in one huge connected component — which would make
    "small component size" a spuriously strong (and wrong) fraud signal.
    ~15% of accounts are "dormant" (almost no activity), to give the model
    real examples of low-connectivity accounts that are still legitimate."""
    account_ids = []
    for i in range(cfg.legit_person_count):
        pid = f"P{2000 + i}"
        aid = f"A{id_start + i}"
        ds.persons.append({"id": pid, "name": _rand_name(rng), "created_at": _ts(days_ago=rng.uniform(30, 1200))[0]})
        ds.add_account(aid, account_type=rng.choice(["checking", "savings", "digital_wallet"]),
                        status="ACTIVE", country=rng.choice(COUNTRIES),
                        created_at=_ts(days_ago=rng.uniform(30, 1200))[0])
        ds.link_owner(pid, aid)
        device_id = f"D-LEGIT-{i}"
        ds.add_device(device_id, device_type=rng.choice(["iphone", "android", "desktop_chrome"]),
                       days_ago=rng.uniform(30, 1200))
        ds.link_device(aid, device_id)
        ip_id = f"IP-LEGIT-{i}"
        ds.add_ip(ip_id, address=f"{rng.randint(20,220)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(1,254)}",
                   geo="residential", days_ago=rng.uniform(30, 1200))
        ds.link_ip(aid, ip_id)
        ds.mark_ground_truth(aid, False, ring_id="NONE", pattern="legit")
        account_ids.append(aid)

        # small realistic noise: occasionally share a device/ip with another legit account (family/household)
        if rng.random() < cfg.noise_level and account_ids:
            buddy = rng.choice(account_ids)
            if rng.random() < 0.5:
                ds.link_device(buddy, device_id)
            else:
                ds.link_ip(buddy, ip_id)
    return account_ids


def generate_normal_transactions(ds: SyntheticDataset, cfg: GeneratorConfig, rng: random.Random,
                                  legit_accounts: list[str]) -> None:
    if len(legit_accounts) < 2:
        return

    # ~15% of accounts are "dormant": 0-1 small transactions, kept mostly isolated.
    shuffled = legit_accounts[:]
    rng.shuffle(shuffled)
    n_dormant = max(0, int(len(shuffled) * 0.15))
    dormant = set(shuffled[:n_dormant])
    active = [a for a in legit_accounts if a not in dormant]

    for i, aid in enumerate(sorted(dormant)):
        if rng.random() < 0.6 and active:
            ds.add_transaction(f"T-DORM{i}", aid, rng.choice(active), amount=rng.uniform(5, 120),
                                days_ago=rng.uniform(0, 180), channel="transfer")

    # Split the remaining active legit accounts into small "circles" (contacts/merchants),
    # mirroring how real payment graphs are clustered rather than uniformly random.
    circle_size = 10
    circles = [active[i:i + circle_size] for i in range(0, len(active), circle_size)]
    circles = [c for c in circles if len(c) >= 2]

    txn_i = 0
    for _ in range(cfg.normal_transaction_count):
        if not circles:
            break
        circle = rng.choice(circles)
        if rng.random() < 0.85 or len(circles) == 1:
            src, dst = rng.sample(circle, 2)
        else:
            other_circle = rng.choice(circles)
            src = rng.choice(circle)
            dst = rng.choice(other_circle)
            if src == dst:
                continue
        amount = rng.uniform(5, 650)
        ds.add_transaction(f"T-N{txn_i}", src, dst, amount=amount, days_ago=rng.uniform(0, 90),
                            channel=rng.choice(["transfer", "bill_pay", "p2p"]))
        txn_i += 1


PATTERNS = ["dense_ring", "shared_device_ring", "shared_ip_cluster", "layered_movement", "central_mule_leader"]


def generate_fraud_ring(ds: SyntheticDataset, pattern: str, ring_index: int, cfg: GeneratorConfig,
                         rng: random.Random, id_base: int) -> None:
    n = max(3, cfg.accounts_per_ring)
    ring_id = f"RING-GEN-{ring_index}"
    accounts = []
    for i in range(n):
        aid = f"A{id_base + i}"
        pid = f"P-GEN-{ring_index}-{i}"
        ds.persons.append({"id": pid, "name": _rand_name(rng), "created_at": _ts(days_ago=rng.uniform(5, 90))[0]})
        ds.add_account(aid, account_type="digital_wallet", status="ACTIVE",
                        country=rng.choice(["RO", "NG", "VN", "RU", "PH"]),
                        created_at=_ts(days_ago=rng.uniform(5, 90))[0])
        ds.link_owner(pid, aid)
        ds.mark_ground_truth(aid, True, ring_id=ring_id, pattern=pattern)
        accounts.append(aid)

    if pattern == "dense_ring":
        for i in range(n):
            for _ in range(rng.randint(1, 3)):
                j = rng.randrange(n)
                if j == i:
                    continue
                ds.add_transaction(f"T-{ring_id}-{i}-{j}-{rng.randint(0,999)}", accounts[i], accounts[j],
                                    amount=rng.uniform(500, 5000), days_ago=rng.uniform(0, 5),
                                    hours_ago=rng.uniform(0, 12), channel="instant_transfer")

    elif pattern == "shared_device_ring":
        device_id = f"D-{ring_id}"
        ds.add_device(device_id, device_type="emulator", days_ago=rng.uniform(10, 60))
        for aid in accounts:
            ds.link_device(aid, device_id)
        # sparse incidental transfers
        for _ in range(n // 2):
            a, b = rng.sample(accounts, 2)
            ds.add_transaction(f"T-{ring_id}-{a}-{b}", a, b, amount=rng.uniform(20, 300),
                                days_ago=rng.uniform(0, 30))

    elif pattern == "shared_ip_cluster":
        ip_id = f"IP-{ring_id}"
        ds.add_ip(ip_id, address=f"{rng.randint(1,223)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(1,254)}",
                   geo="datacenter_proxy", days_ago=rng.uniform(10, 60))
        for aid in accounts:
            ds.link_ip(aid, ip_id)
        for _ in range(n // 2):
            a, b = rng.sample(accounts, 2)
            ds.add_transaction(f"T-{ring_id}-{a}-{b}", a, b, amount=rng.uniform(20, 300),
                                days_ago=rng.uniform(0, 30))

    elif pattern == "layered_movement":
        broker_id = f"BR-{ring_id}"
        ds.add_broker(broker_id, name=f"Shell Processor {ring_index}", broker_type="shell_company", risk_level="HIGH")
        amount = rng.uniform(8000, 20000)
        for i in range(n - 1):
            amount *= rng.uniform(0.85, 0.97)
            ds.add_transaction(f"T-{ring_id}-hop{i}", accounts[i], accounts[i + 1], amount=amount,
                                days_ago=1, hours_ago=(n - i) * 2, channel="instant_transfer")
        ds.link_broker(accounts[-1], broker_id)
        ds.add_transaction(f"T-{ring_id}-cashout", accounts[-1], accounts[-1], amount=amount * 0.9,
                            days_ago=0, hours_ago=1, channel="broker_payout", broker_id=broker_id)

    elif pattern == "central_mule_leader":
        leader = accounts[0]
        feeders = accounts[1:]
        broker_id = f"BR-{ring_id}"
        ds.add_broker(broker_id, name=f"Offshore Exchange {ring_index}", broker_type="crypto_mixer", risk_level="HIGH")
        total = 0.0
        for i, f_acc in enumerate(feeders):
            amt = rng.uniform(300, 1800)
            total += amt
            ds.add_transaction(f"T-{ring_id}-fanin{i}", f_acc, leader, amount=amt,
                                days_ago=rng.uniform(0, 4), hours_ago=rng.uniform(0, 20))
        ds.link_broker(leader, broker_id)
        ds.add_transaction(f"T-{ring_id}-cashout", leader, leader, amount=total * 0.92,
                            days_ago=0, hours_ago=1, channel="broker_payout", broker_id=broker_id)

    # cross-ring noise: occasionally a fraud-ring account transacts with a legit-looking account
    if rng.random() < cfg.noise_level:
        ds.add_transaction(f"T-{ring_id}-noise", rng.choice(accounts), f"A{2000 + rng.randint(0, 50)}",
                            amount=rng.uniform(10, 150), days_ago=rng.uniform(0, 60))


def generate(cfg: Optional[GeneratorConfig] = None) -> SyntheticDataset:
    cfg = cfg or GeneratorConfig.from_env()
    rng = random.Random(cfg.random_seed)
    ds = SyntheticDataset()

    plant_demo_scenario(ds)

    legit_accounts = generate_legit_population(ds, cfg, rng, id_start=2000)
    generate_normal_transactions(ds, cfg, rng, legit_accounts)

    for i in range(cfg.ring_count):
        pattern = PATTERNS[i % len(PATTERNS)]
        generate_fraud_ring(ds, pattern, ring_index=i, cfg=cfg, rng=rng, id_base=5000 + i * 100)

    return ds


def main():
    parser = argparse.ArgumentParser(description="Generate RingTrace synthetic fraud-ring data (SYNTHETIC ONLY).")
    parser.add_argument("--ring-count", type=int, default=None)
    parser.add_argument("--accounts-per-ring", type=int, default=None)
    parser.add_argument("--legit-person-count", type=int, default=None)
    parser.add_argument("--normal-transaction-count", type=int, default=None)
    parser.add_argument("--noise-level", type=float, default=None)
    parser.add_argument("--fraud-ratio", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out-dir", type=str, default=str(DATA_DIR))
    args = parser.parse_args()

    cfg = GeneratorConfig.from_env()
    if args.ring_count is not None:
        cfg.ring_count = args.ring_count
    if args.accounts_per_ring is not None:
        cfg.accounts_per_ring = args.accounts_per_ring
    if args.legit_person_count is not None:
        cfg.legit_person_count = args.legit_person_count
    if args.normal_transaction_count is not None:
        cfg.normal_transaction_count = args.normal_transaction_count
    if args.noise_level is not None:
        cfg.noise_level = args.noise_level
    if args.fraud_ratio is not None:
        cfg.fraud_ratio = args.fraud_ratio
    if args.seed is not None:
        cfg.random_seed = args.seed

    print(f"[RingTrace] Generating SYNTHETIC data with config: {cfg}")
    ds = generate(cfg)
    ds.to_csv(out_dir=Path(args.out_dir))
    print(f"[RingTrace] Wrote {len(ds.accounts)} accounts, {len(ds.persons)} persons, "
          f"{len(ds.transactions)} transactions, {len(ds.devices)} devices, {len(ds.ips)} IPs, "
          f"{len(ds.brokers)} brokers to {args.out_dir}")
    print(f"[RingTrace] Ground truth (SYNTHETIC, evaluation-only) -> {PROCESSED_DIR / 'ground_truth.csv'}")


if __name__ == "__main__":
    main()
