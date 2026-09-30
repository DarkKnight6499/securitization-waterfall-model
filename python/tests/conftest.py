import pytest

from waterfall.config import BASE_SCENARIO, SCENARIOS, Deal
from waterfall.waterfall import run_waterfall


@pytest.fixture(scope="session")
def deal():
    return Deal()


@pytest.fixture(scope="session")
def runs(deal):
    return {s.name: run_waterfall(deal, s) for s in SCENARIOS}


@pytest.fixture(scope="session")
def base(runs):
    return runs[BASE_SCENARIO.name]
