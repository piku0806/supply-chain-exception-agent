from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = Path(os.getenv("SCOPS_WAREHOUSE", ROOT / "data" / "warehouse.duckdb"))
DIGEST_DIR = Path(os.getenv("SCOPS_DIGEST_DIR", ROOT / "data" / "digests"))
DBT_DIR = ROOT / "dbt"
AS_OF = os.getenv("SCOPS_AS_OF", "2026-09-30 08:00:00")
