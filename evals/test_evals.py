"""The evaluation scenarios, run with the mock provider on copies of the seeded warehouse."""

import pytest

from apps.api.agent.providers import MockProvider
from evals import runner


@pytest.mark.parametrize("scenario", runner.SCENARIOS, ids=lambda s: s["name"])
def test_scenario(scenario, warehouse):
    copy = warehouse.copy(f"eval_{scenario['name']}")
    assert runner.run(copy.url, scenario, MockProvider()) == []
