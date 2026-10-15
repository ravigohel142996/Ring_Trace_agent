"""Event-day temporal payment-corridor investigation implementation.

This package is intentionally separate from RingTrace's pre-event account/ring
engine so the new graph model and query path have a visible, auditable boundary.
"""

__all__ = ["engine", "graph", "seed"]
