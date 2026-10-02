"""The operations playbook as code: what the agent may do, and what needs a human.

The LLM proposes a plan; this module validates every proposed action against the catalog
and live data, prices it, and decides whether it runs automatically or waits for approval.
"""
from __future__ import annotations

from scops import warehouse

ACTION_CATALOG = {
    "MONITOR": "Keep watching; no action yet",
    "CONTACT_CARRIER": "Open a trace request with the carrier",
    "VERIFY_ADDRESS": "Contact the customer to confirm the delivery address",
    "NOTIFY_CUSTOMER": "Send the customer a proactive notice (message required)",
    "FILE_CARRIER_CLAIM": "File a damage claim with the carrier (claim_value_usd required)",
    "EXPEDITE_REPLACEMENT": "Ship a replacement from another warehouse on the fastest lane (from_warehouse required)",
}

EXPEDITE_APPROVAL_USD = 500       # expedite spend above this needs an ops manager
CLAIM_APPROVAL_USD = 10_000       # claims above this need finance review


def estimate_cost(action: str, exc: dict) -> float:
    if action == "EXPEDITE_REPLACEMENT":
        return round(250 + 0.04 * float(exc["order_value"]), 2)   # premium freight + handling
    return 0.0


def validate(plan: dict, exc: dict, con) -> tuple[list[dict], list[dict]]:
    """Return (valid_actions, rejected_actions). Never trust the model's plan blindly."""
    valid, rejected, seen = [], [], set()
    for a in plan.get("actions", []):
        t, params = a.get("type"), a.get("params", {}) or {}
        reason = None
        if t not in ACTION_CATALOG:
            reason = f"unknown action {t!r}"
        elif t in seen:
            reason = "duplicate action"
        elif t == "NOTIFY_CUSTOMER" and not plan.get("customer_message"):
            reason = "customer notice proposed without a message"
        elif t == "FILE_CARRIER_CLAIM":
            if exc["exception_type"] != "DAMAGED":
                reason = "claims are only for damaged shipments"
            elif not params.get("claim_value_usd") or float(params["claim_value_usd"]) > float(exc["order_value"]):
                reason = "claim value missing or above the order value"
        elif t == "EXPEDITE_REPLACEMENT":
            stock = {s["warehouse"] for s in warehouse.stock_for_sku(con, exc["sku"], int(exc["quantity"]))}
            if params.get("from_warehouse") not in stock:
                reason = f"no replacement stock at {params.get('from_warehouse')!r} (available: {sorted(stock) or 'none'})"
        if reason:
            rejected.append({**a, "reason": reason})
        else:
            seen.add(t)
            valid.append({"type": t, "params": params})
    return valid, rejected


def approval_needed(action: dict, exc: dict) -> str | None:
    t, cost = action["type"], estimate_cost(action["type"], exc)
    if t == "EXPEDITE_REPLACEMENT" and cost > EXPEDITE_APPROVAL_USD:
        return f"expedite spend ${cost:,.0f} exceeds ${EXPEDITE_APPROVAL_USD} limit"
    if t == "FILE_CARRIER_CLAIM" and float(action["params"]["claim_value_usd"]) > CLAIM_APPROVAL_USD:
        return f"claim above ${CLAIM_APPROVAL_USD:,} needs finance review"
    if t == "NOTIFY_CUSTOMER" and exc["customer_tier"] == "strategic":
        return "strategic account: account manager reviews customer messages"
    return None
