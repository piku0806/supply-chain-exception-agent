import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_tmp = Path(tempfile.mkdtemp())
os.environ["SCOPS_WAREHOUSE"] = str(_tmp / "warehouse.duckdb")
os.environ["SCOPS_DIGEST_DIR"] = str(_tmp / "digests")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{_tmp / 'mlflow.db'}"
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def built_warehouse():
    from scops.loop import run_dbt
    run_dbt()          # full dbt build: seeds, models and data tests must pass
    return Path(os.environ["SCOPS_WAREHOUSE"])
