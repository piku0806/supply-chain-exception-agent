from scops import agent, policy, warehouse
from scops.loop import run


def test_gold_layer_has_exceptions(built_warehouse):
    with warehouse.connect(read_only=True) as con:
        excs = warehouse.open_exceptions(con)
        types = {e["exception_type"] for e in excs}
    assert len(excs) > 10 and {"DAMAGED", "STUCK_IN_TRANSIT", "ADDRESS_ISSUE"} <= types


def test_silver_layer_normalized_carriers(built_warehouse):
    with warehouse.connect(read_only=True) as con:
        carriers = {r["carrier"] for r in warehouse.rows(con, "select distinct carrier from silver.stg_shipments")}
    assert carriers == {"GlobalFreight", "SwiftHaul", "BlueLine Express", "Prairie Logistics"}


def test_approval_thresholds():
    exc = {"order_value": 20000, "customer_tier": "standard"}
    assert policy.approval_needed({"type": "EXPEDITE_REPLACEMENT", "params": {}}, exc)          # $1,050 > $500
    assert not policy.approval_needed({"type": "EXPEDITE_REPLACEMENT", "params": {}}, {**exc, "order_value": 5000})
    assert policy.approval_needed({"type": "FILE_CARRIER_CLAIM", "params": {"claim_value_usd": 15000}}, exc)
    assert policy.approval_needed({"type": "NOTIFY_CUSTOMER", "params": {}}, {**exc, "customer_tier": "strategic"})
    assert not policy.approval_needed({"type": "CONTACT_CARRIER", "params": {}}, exc)


def test_hallucinated_and_unsafe_proposals_are_rejected(built_warehouse):
    def rogue_planner(ctx):
        return {"root_cause": "x", "customer_message": None, "rationale": "x", "actions": [
            {"type": "ISSUE_REFUND", "params": {}},                                   # not in catalog
            {"type": "EXPEDITE_REPLACEMENT", "params": {"from_warehouse": "MARS"}},   # no stock there
            {"type": "FILE_CARRIER_CLAIM", "params": {"claim_value_usd": 10**9}},     # wrong type / too high
            {"type": "NOTIFY_CUSTOMER", "params": {}},                                # no message
            {"type": "CONTACT_CARRIER", "params": {}},                                # fine
        ]}
    with warehouse.connect(read_only=True) as con:
        exc = next(e for e in warehouse.open_exceptions(con) if e["exception_type"] == "STUCK_IN_TRANSIT")
        r = agent.triage(con, exc, planner=rogue_planner)
    assert [d["type"] for d in r["decisions"]] == ["CONTACT_CARRIER"]
    assert len(r["rejected"]) == 4


def test_loop_is_idempotent(built_warehouse):
    first = run(skip_dbt=True)
    second = run(skip_dbt=True)
    assert first["triaged"] > 0 and second["triaged"] == 0
    with warehouse.connect(read_only=True) as con:
        bad = warehouse.rows(con, f"""select * from ops.agent_actions where status = 'auto_executed'
                                       and estimated_cost_usd > {policy.EXPEDITE_APPROVAL_USD}""")
    assert not bad
