"""Suite-wide settings: never reach the network, and register the markers the safety and e2e suites use."""
import os

os.environ["OG_LLM"] = "replay"          # a recorded or scripted model only; a live call raises ReplayMiss


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: heavier test (a few seconds); still offline")
    config.addinivalue_line("markers", "e2e: starts the real TypeScript receiver bridge on a loopback port; skips if that is not possible")
