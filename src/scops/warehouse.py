"""Data access over the gold layer. DuckDB locally; on Databricks, point these queries at Unity Catalog
through the Databricks SQL connector (same SQL, same table names)."""
from __future__ import annotations

from contextlib import contextmanager

import duckdb
import mlflow
from mlflow.entities import SpanType

from scops.config import WAREHOUSE

ACTIONS_DDL = """
create schema if not exists ops;
create table if not exists ops.agent_actions (
    action_id varchar primary key, run_id varchar, shipment_id varchar, customer_name varchar,
    customer_tier varchar, exception_type varchar, action_type varchar, params varchar,
    estimated_cost_usd double, revenue_at_risk_usd double, status varchar, approval_reason varchar,
    rationale varchar, customer_message varchar, decided_by varchar, created_at timestamp, decided_at timestamp
);
"""


@contextmanager
def connect(read_only: bool = False):
    con = duckdb.connect(str(WAREHOUSE), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ------------------------------------------------------------------ tools the agent can call (all read-only)
@mlflow.trace(span_type=SpanType.TOOL)
def open_exceptions(con) -> list[dict]:
    return rows(con, "select * from gold.fct_shipment_exceptions order by priority_score desc")


@mlflow.trace(span_type=SpanType.TOOL)
def carrier_performance(con, carrier: str) -> dict:
    r = rows(con, "select * from gold.dim_carrier_performance where carrier = ?", [carrier])
    return r[0] if r else {"carrier": carrier, "on_time_rate": None}


@mlflow.trace(span_type=SpanType.TOOL)
def stock_for_sku(con, sku: str, quantity: int) -> list[dict]:
    """Warehouses that can ship a full replacement without dropping below their reorder point."""
    return rows(con, """select warehouse, on_hand, reorder_point from gold.fct_inventory_position
                        where sku = ? and on_hand - ? >= reorder_point order by on_hand desc""", [sku, quantity])


@mlflow.trace(span_type=SpanType.TOOL)
def fastest_lane(con, origin: str, destination: str) -> dict | None:
    r = rows(con, """select * from gold.dim_carrier_lanes l join gold.dim_carrier_performance p using (carrier)
                     where l.origin = ? and l.destination = ?
                     order by l.expedite_days, p.on_time_rate desc limit 1""", [origin, destination])
    return r[0] if r else None
