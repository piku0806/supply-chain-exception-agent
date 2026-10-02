"""Exception triage agent: gather context with read-only tools, propose a plan, validate it, apply policy."""
from __future__ import annotations

import json

import mlflow
from mlflow.entities import SpanType

from scops import llm, policy, warehouse

SYSTEM = f"""You are a supply chain operations analyst triaging one shipment exception.
Choose actions ONLY from this catalog: {json.dumps(policy.ACTION_CATALOG)}.
Playbook: damaged -> file a claim for the order value, expedite a replacement if a warehouse has stock, notify the customer;
address issue -> verify address; stuck in transit -> contact carrier, and for strategic customers or orders over $20,000
also expedite a replacement if stock exists and notify the customer; late in transit -> notify the customer, and contact
the carrier if more than 24 hours late; at risk -> contact the carrier.
Never propose a replacement from a warehouse that is not listed as having stock. Customer messages must be factual,
apologetic, under 80 words, and must not promise refunds or credits.
Return ONLY JSON: {{"root_cause": str, "actions": [{{"type": str, "params": {{}}}}], "customer_message": str|null, "rationale": str}}"""


def _gather(con, exc: dict) -> dict:
    lane = warehouse.fastest_lane(con, exc["origin"], exc["destination"])
    return {
        "exception": {k: (str(v) if k.endswith("_at") else v) for k, v in exc.items()},
        "carrier_performance": warehouse.carrier_performance(con, exc["carrier"]),
        "replacement_stock": warehouse.stock_for_sku(con, exc["sku"], int(exc["quantity"])),
        "fastest_lane": lane,
    }


def _message(exc: dict, issue: str) -> str:
    return (f"Hello {exc['customer_name']} team, we're sorry: your order {exc['order_id']} ({exc['quantity']} x {exc['sku']}) "
            f"{issue}. We are working with the carrier and will send an updated delivery date within 24 hours. "
            "Your account team is available if you need anything in the meantime.")


def mock_plan(ctx: dict) -> dict:
    """Offline reference implementation of the playbook (mirrors the system prompt)."""
    exc, stock = ctx["exception"], ctx["replacement_stock"]
    t, value, strategic = exc["exception_type"], float(exc["order_value"]), exc["customer_tier"] == "strategic"
    src = stock[0]["warehouse"] if stock else None
    actions, msg = [], None
    if t == "DAMAGED":
        actions.append({"type": "FILE_CARRIER_CLAIM", "params": {"claim_value_usd": value}})
        if src:
            actions.append({"type": "EXPEDITE_REPLACEMENT", "params": {"from_warehouse": src}})
        actions.append({"type": "NOTIFY_CUSTOMER", "params": {}})
        msg, cause = _message(exc, "was damaged in transit"), f"Damage reported by {exc['carrier']} in transit."
    elif t == "ADDRESS_ISSUE":
        actions.append({"type": "VERIFY_ADDRESS", "params": {}})
        cause = "Carrier could not deliver to the address on file."
    elif t == "STUCK_IN_TRANSIT":
        actions.append({"type": "CONTACT_CARRIER", "params": {}})
        if (strategic or value > 20_000) and src:
            actions.append({"type": "EXPEDITE_REPLACEMENT", "params": {"from_warehouse": src}})
        if strategic or value > 20_000:
            actions.append({"type": "NOTIFY_CUSTOMER", "params": {}})
            msg = _message(exc, "has not had a carrier scan for over two days")
        cause = f"No carrier scan for {exc['hours_since_last_scan']} hours ({exc['carrier']} on-time rate " \
                f"{ctx['carrier_performance'].get('on_time_rate')})."
    elif t == "LATE_IN_TRANSIT":
        actions.append({"type": "NOTIFY_CUSTOMER", "params": {}})
        if exc["hours_past_promise"] > 24:
            actions.append({"type": "CONTACT_CARRIER", "params": {}})
        msg, cause = _message(exc, "is running behind its promised delivery date"), \
            f"{exc['hours_past_promise']} hours past the promised delivery time."
    else:  # AT_RISK
        actions.append({"type": "CONTACT_CARRIER", "params": {}})
        cause = "Promise date is within 24 hours and the last scan is over a day old."
    return {"root_cause": cause, "actions": actions, "customer_message": msg,
            "rationale": f"Playbook for {t.lower().replace('_', ' ')} ({exc['customer_tier']} customer, ${value:,.0f})."}


@mlflow.trace(name="triage_exception", span_type=SpanType.AGENT)
def triage(con, exc: dict, planner=None) -> dict:
    ctx = _gather(con, exc)
    if planner is not None:
        plan = planner(ctx)
    elif llm.provider() == "mock":
        plan = mock_plan(ctx)
    else:
        plan = llm.complete_json(SYSTEM, json.dumps(ctx, default=str))
    valid, rejected = policy.validate(plan, exc, con)
    decisions = []
    for a in valid:
        reason = policy.approval_needed(a, exc)
        decisions.append({**a, "estimated_cost_usd": policy.estimate_cost(a["type"], exc),
                          "status": "pending_approval" if reason else "auto_executed", "approval_reason": reason})
    return {"shipment_id": exc["shipment_id"], "exception": exc, "root_cause": plan.get("root_cause", ""),
            "rationale": plan.get("rationale", ""), "customer_message": plan.get("customer_message"),
            "decisions": decisions, "rejected": rejected}
