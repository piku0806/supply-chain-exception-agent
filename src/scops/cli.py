"""Supply chain exception agent.

    python -m scops run [--skip-dbt]      # pipeline + triage + digest
    python -m scops approvals             # pending actions
    python -m scops approve <id> --by sam
    python -m scops reject  <id> --by sam
"""
from __future__ import annotations

import argparse
import os
import warnings
from datetime import datetime

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
warnings.filterwarnings("ignore")

import mlflow  # noqa: E402

from scops import warehouse  # noqa: E402


def _tracing() -> None:
    if not os.getenv("MLFLOW_TRACKING_URI"):
        mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment("supply-chain-exception-agent")


def cmd_run(a) -> None:
    from scops.loop import run
    _tracing()
    res = run(skip_dbt=a.skip_dbt)
    print(f"Run {res['run_id']}: triaged {res['triaged']} new exceptions "
          f"({res['skipped_already_handled']} already handled)\nDigest: {res['digest']}\n")
    print(open(res["digest"]).read())


def cmd_approvals(_a) -> None:
    with warehouse.connect(read_only=True) as con:
        for r in warehouse.rows(con, "select * from ops.agent_actions where status = 'pending_approval' order by revenue_at_risk_usd desc"):
            print(f"{r['action_id']}  {r['action_type']:<21} {r['shipment_id']}  {r['customer_name']:<22} "
                  f"${r['estimated_cost_usd']:>7,.0f}  {r['approval_reason']}")
            if r["customer_message"]:
                print(f"           message: {r['customer_message']}")


def _decide(a, status: str) -> None:
    with warehouse.connect() as con:
        n = con.execute("update ops.agent_actions set status = ?, decided_by = ?, decided_at = ? "
                        "where action_id = ? and status = 'pending_approval' returning action_id",
                        [status, a.by, datetime.now(), a.id]).fetchall()
    print(f"{a.id}: {status}" if n else f"{a.id}: not pending")


def main() -> None:
    p = argparse.ArgumentParser(prog="scops")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--skip-dbt", action="store_true"); r.set_defaults(fn=cmd_run)
    sub.add_parser("approvals").set_defaults(fn=cmd_approvals)
    for name, status in (("approve", "approved_executed"), ("reject", "rejected")):
        x = sub.add_parser(name); x.add_argument("id"); x.add_argument("--by", required=True)
        x.set_defaults(fn=lambda a, s=status: _decide(a, s))
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
