import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'simulator' / 'tests' / '_sim_test.db').as_posix()}")
os.environ.setdefault("EMBEDDED_SIM", "0")
os.environ.setdefault("MQTT_ENABLED", "0")

import random

import pytest


@pytest.fixture(autouse=True)
def _fixed_seed():
    """Le moteur ajoute du bruit gaussien : graine fixe pour des tests reproductibles."""
    random.seed(20261010)
    yield
