import pytest

from orderguard_arena.arena import ArenaConfig, run_arena


@pytest.fixture(scope="module")
def small_run():
    """One small seeded arena run shared by the tests in a module (agents 150, 400 steps, 4 days)."""
    return run_arena(ArenaConfig(seed=7, agents=150, steps=400, steps_per_day=100))
