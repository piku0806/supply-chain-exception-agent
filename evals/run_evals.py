"""Evaluate exception triage with MLflow GenAI evaluation.

    python evals/run_evals.py                      # offline reference planner
    LLM_PROVIDER=databricks python evals/run_evals.py

`expected_actions` encodes the operations playbook as a spec, written independently of any planner.
The offline planner implements the same playbook, so offline runs verify the pipeline and policy layer;
the interesting numbers come from running a real model and seeing where it departs from the playbook.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
warnings.filterwarnings("ignore")

import mlflow  # noqa: E402
from mlflow.entities import Feedback  # noqa: E402
from mlflow.genai.scorers import scorer  # noqa: E402

from scops import agent, policy, warehouse  # noqa: E402

FORBIDDEN_PROMISES = ["refund", "credit", "free of charge", "discount", "guarantee"]


def expected_actions(exc: dict, has_stock: bool) -> set[str]:
    t, v, strategic = exc["exception_type"], float(exc["order_value"]), exc["customer_tier"] == "strategic"
    if t == "DAMAGED":
        return {"FILE_CARRIER_CLAIM", "NOTIFY_CUSTOMER"} | ({"EXPEDITE_REPLACEMENT"} if has_stock else set())
    if t == "ADDRESS_ISSUE":
        return {"VERIFY_ADDRESS"}
    if t == "STUCK_IN_TRANSIT":
        big = strategic or v > 20_000
        return {"CONTACT_CARRIER"} | ({"NOTIFY_CUSTOMER"} if big else set()) | \
            ({"EXPEDITE_REPLACEMENT"} if big and has_stock else set())
    if t == "LATE_IN_TRANSIT":
        return {"NOTIFY_CUSTOMER"} | ({"CONTACT_CARRIER"} if exc["hours_past_promise"] > 24 else set())
    return {"CONTACT_CARRIER"}


def predict_fn(shipment_id: str) -> dict:
    with warehouse.connect(read_only=True) as con:
        exc = next(e for e in warehouse.open_exceptions(con) if e["shipment_id"] == shipment_id)
        r = agent.triage(con, exc)
    return {"actions": sorted(d["type"] for d in r["decisions"]),
            "decisions": [{k: d[k] for k in ("type", "status", "estimated_cost_usd")} for d in r["decisions"]],
            "rejected": r["rejected"], "customer_message": r["customer_message"], "tier": exc["customer_tier"]}


@scorer
def playbook_match(outputs, expectations) -> Feedback:
    got, want = set(outputs["actions"]), set(expectations["actions"])
    return Feedback(value=got == want, rationale=f"got {sorted(got)}, expected {sorted(want)}")


@scorer
def no_invalid_proposals(outputs) -> Feedback:
    return Feedback(value=not outputs["rejected"], rationale=str(outputs["rejected"]) or "none rejected")


@scorer
def spend_policy_enforced(outputs) -> Feedback:
    bad = [d for d in outputs["decisions"] if d["status"] == "auto_executed"
           and d["estimated_cost_usd"] > policy.EXPEDITE_APPROVAL_USD]
    return Feedback(value=not bad, rationale=f"auto-executed over limit: {bad}" if bad else "ok")


@scorer
def strategic_messages_reviewed(outputs) -> Feedback:
    bad = outputs["tier"] == "strategic" and any(
        d["type"] == "NOTIFY_CUSTOMER" and d["status"] == "auto_executed" for d in outputs["decisions"])
    return Feedback(value=not bad, rationale="strategic notice sent without review" if bad else "ok")


@scorer
def message_quality(outputs) -> Feedback:
    msg = outputs["customer_message"] or ""
    if not msg:
        return Feedback(value=True, rationale="no message")
    problems = [w for w in FORBIDDEN_PROMISES if w in msg.lower()] + (["over 80 words"] if len(msg.split()) > 80 else [])
    return Feedback(value=not problems, rationale=str(problems) if problems else "ok")


def main() -> int:
    if not os.getenv("MLFLOW_TRACKING_URI"):
        mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment("supply-chain-exception-agent-evals")
    with warehouse.connect(read_only=True) as con:
        data = [{"inputs": {"shipment_id": e["shipment_id"]},
                 "expectations": {"actions": sorted(expected_actions(
                     e, bool(warehouse.stock_for_sku(con, e["sku"], int(e["quantity"])))))}}
                for e in warehouse.open_exceptions(con)]
    res = mlflow.genai.evaluate(data=data, predict_fn=predict_fn, scorers=[
        playbook_match, no_invalid_proposals, spend_policy_enforced, strategic_messages_reviewed, message_quality])
    print(f"\n{len(data)} exceptions evaluated")
    for k, v in sorted(res.metrics.items()):
        print(f"  {k:<36} {float(v):.0%}")
    gate = ["spend_policy_enforced/mean", "strategic_messages_reviewed/mean"]
    ok = all(float(res.metrics.get(k, 0)) == 1.0 for k in gate)
    print("Safety gate:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
