"""Generate a deterministic, fictional supply chain dataset as dbt seeds (the bronze layer).

    python scripts/generate_data.py

Writes raw_orders, raw_shipments, raw_carrier_events, raw_inventory and raw_carrier_lanes CSVs.
Data quality issues are injected on purpose (duplicate events, inconsistent carrier names,
mixed-case statuses) so the silver layer has real cleaning work to do.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEEDS = Path(__file__).resolve().parents[1] / "dbt" / "seeds"
AS_OF = datetime(2026, 9, 30, 8, 0)          # "today" for the pipeline
rng = random.Random(42)

CUSTOMERS = [("C001", "Contoso Retail", "strategic"), ("C002", "Fabrikam Industrial", "strategic"),
             ("C003", "Litware Outdoor", "standard"), ("C004", "Adventure Works", "standard"),
             ("C005", "Tailspin Toys", "standard"), ("C006", "Wide World Importers", "strategic"),
             ("C007", "Proseware Medical", "strategic"), ("C008", "Coho Vineyard", "standard")]
CARRIERS = {"GlobalFreight": ["GlobalFreight", "GLOBALFREIGHT", "Global Freight"],
            "SwiftHaul": ["SwiftHaul", "Swift Haul"], "BlueLine Express": ["BlueLine Express", "Blueline"],
            "Prairie Logistics": ["Prairie Logistics"]}
CARRIER_RELIABILITY = {"GlobalFreight": 0.88, "SwiftHaul": 0.68, "BlueLine Express": 0.94, "Prairie Logistics": 0.78}
LANES = [("ATL", "CHI"), ("ATL", "DAL"), ("CHI", "NYC"), ("DAL", "LAX"), ("NYC", "BOS"), ("CHI", "DEN")]
SKUS = [("SKU-100", "Pallet racking kit", 180), ("SKU-200", "Industrial sensor", 420), ("SKU-300", "Safety gloves (case)", 60),
        ("SKU-400", "Medical cold-chain box", 950), ("SKU-500", "Forklift battery", 2600)]
WAREHOUSES = ["ATL", "CHI", "DAL", "NYC"]


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (SEEDS / f"{name}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    SEEDS.mkdir(parents=True, exist_ok=True)
    orders, shipments, events = [], [], []
    for i in range(1, 241):
        cust = rng.choice(CUSTOMERS)
        sku, desc, unit = rng.choice(SKUS)
        qty = rng.randint(2, 40)
        origin, dest = rng.choice(LANES)
        carrier = rng.choice(list(CARRIERS))
        ship_at = AS_OF - timedelta(days=rng.uniform(0.5, 9))
        transit_days = rng.choice([2, 3, 3, 4])
        promised = ship_at + timedelta(days=transit_days)
        oid, sid = f"O{i:04d}", f"S{i:04d}"
        orders.append([oid, cust[0], cust[1], cust[2], sku, qty, round(qty * unit, 2), promised.strftime("%Y-%m-%d %H:%M:%S")])

        # Outcome simulation
        roll = rng.random()
        reliable = rng.random() < CARRIER_RELIABILITY[carrier]
        ev = [("PICKED_UP", ship_at), ("IN_TRANSIT", ship_at + timedelta(hours=rng.uniform(3, 10)))]
        if roll < 0.04:
            ev.append(("DAMAGED", ship_at + timedelta(days=1.2)))
        elif roll < 0.07:
            ev.append(("ADDRESS_EXCEPTION", ship_at + timedelta(days=1.5)))
        else:
            delay = timedelta(0) if reliable else timedelta(days=rng.uniform(1, 3))
            delivered = promised + delay - timedelta(hours=rng.uniform(0, 12))
            if delivered <= AS_OF:
                ev.append(("DELIVERED", delivered))
            elif not reliable and rng.random() < 0.5:
                pass  # no further scans: shipment goes dark ("stuck")
            else:
                ev.append(("IN_TRANSIT", AS_OF - timedelta(hours=rng.uniform(2, 20))))
        shipments.append([sid, oid, rng.choice(CARRIERS[carrier]), origin, dest,
                          ship_at.strftime("%Y-%m-%d %H:%M:%S"), f"TRK{rng.randint(10**8, 10**9)}"])
        for status, ts in ev:
            if ts <= AS_OF:
                status_raw = status.lower() if rng.random() < 0.2 else status
                events.append([sid, status_raw, ts.strftime("%Y-%m-%d %H:%M:%S"), dest if status == "DELIVERED" else origin])
                if rng.random() < 0.05:  # duplicate event from carrier API retries
                    events.append([sid, status_raw, ts.strftime("%Y-%m-%d %H:%M:%S"), dest if status == "DELIVERED" else origin])

    inventory = []
    for wh in WAREHOUSES:
        for sku, _, _ in SKUS:
            on_hand = rng.randint(0, 120)
            if (wh, sku) in {("CHI", "SKU-400"), ("DAL", "SKU-500")}:
                on_hand = rng.randint(0, 3)  # deliberately low stock
            inventory.append([wh, sku, on_hand, rng.randint(10, 30), AS_OF.strftime("%Y-%m-%d %H:%M:%S")])

    lanes = []
    for o, d in LANES:
        for c in CARRIERS:
            lanes.append([o, d, c, round(rng.uniform(1.8, 3.6), 2), rng.choice([1, 2, 2, 3])])

    write("raw_orders", ["order_id", "customer_id", "customer_name", "customer_tier", "sku", "quantity", "order_value", "promised_delivery_at"], orders)
    write("raw_shipments", ["shipment_id", "order_id", "carrier_name", "origin", "destination", "shipped_at", "tracking_number"], shipments)
    write("raw_carrier_events", ["shipment_id", "event_status", "event_at", "location"], events)
    write("raw_inventory", ["warehouse", "sku", "on_hand", "reorder_point", "snapshot_at"], inventory)
    write("raw_carrier_lanes", ["origin", "destination", "carrier", "cost_per_mile_usd", "expedite_days"], lanes)
    print(f"orders={len(orders)} shipments={len(shipments)} events={len(events)} inventory={len(inventory)} lanes={len(lanes)}")


if __name__ == "__main__":
    main()
