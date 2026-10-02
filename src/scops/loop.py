"""The daily operations loop.

    dbt build (bronze -> silver -> gold)  ->  triage every new exception  ->  record actions  ->  write digest

Idempotent: shipments that already have recorded actions are skipped, so the loop can run
hourly or after every pipeline refresh without duplicating work.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone

import mlflow

from scops import agent, warehouse
from scops.config import AS_OF, DBT_DIR, DIGEST_DIR, WAREHOUSE


def run_dbt() -> None:
    subprocess.run(["dbt", "build", "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR), "--quiet",
                    "--vars", json.dumps({"as_of": AS_OF})], check=True,
                   env={**os.environ, "SCOPS_WAREHOUSE": str(WAREHOUSE.resolve())})


@mlflow.trace(name="daily_exception_loop")
def run(skip_dbt: bool = False, planner=None) -> dict:
    if not skip_dbt:
        run_dbt()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    with warehouse.connect() as con:
        con.execute(warehouse.ACTIONS_DDL)
        handled = {r["shipment_id"] for r in warehouse.rows(con, "select distinct shipment_id from ops.agent_actions")}
        results = [agent.triage(con, exc, planner) for exc in warehouse.open_exceptions(con)
                   if exc["shipment_id"] not in handled]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for r in results:
            exc = r["exception"]
            for d in r["decisions"]:
                con.execute("insert into ops.agent_actions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                    uuid.uuid4().hex[:8], run_id, r["shipment_id"], exc["customer_name"], exc["customer_tier"],
                    exc["exception_type"], d["type"], json.dumps(d["params"]), d["estimated_cost_usd"],
                    float(exc["order_value"]), d["status"], d["approval_reason"], r["rationale"],
                    r["customer_message"] if d["type"] == "NOTIFY_CUSTOMER" else None, "agent" if d["status"] == "auto_executed" else None,
                    now, now if d["status"] == "auto_executed" else None])
        digest = write_digest(con, run_id, results)
    return {"run_id": run_id, "triaged": len(results), "skipped_already_handled": len(handled), "digest": str(digest),
            "results": results}


def write_digest(con, run_id: str, results: list[dict]):
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    acts = warehouse.rows(con, "select * from ops.agent_actions where run_id = ? order by revenue_at_risk_usd desc", [run_id])
    pending = [a for a in acts if a["status"] == "pending_approval"]
    auto = [a for a in acts if a["status"] == "auto_executed"]
    at_risk = sum(float(r["exception"]["order_value"]) for r in results)
    rejected = sum(len(r["rejected"]) for r in results)
    lines = [f"# Shipment exceptions digest: {AS_OF[:10]}", "",
             f"- **{len(results)} new exceptions** triaged, **${at_risk:,.0f}** in order value at risk",
             f"- **{len(auto)} actions** executed automatically (carrier traces, address checks, standard-customer notices, small expedites)",
             f"- **{len(pending)} actions** waiting for approval",
             f"- {rejected} proposed actions rejected by policy validation", "",
             "## Waiting for approval", "", "| Action | Shipment | Customer | At risk | Est. cost | Why approval |",
             "|---|---|---|---:|---:|---|"]
    for a in pending:
        lines.append(f"| `{a['action_id']}` {a['action_type']} | {a['shipment_id']} | {a['customer_name']} ({a['customer_tier']}) "
                     f"| ${a['revenue_at_risk_usd']:,.0f} | ${a['estimated_cost_usd']:,.0f} | {a['approval_reason']} |")
    lines += ["", "Approve with `python -m scops approve <action_id> --by <name>`."]
    path = DIGEST_DIR / f"{AS_OF[:10]}_{run_id}.md"
    path.write_text("\n".join(lines) + "\n")
    return path
