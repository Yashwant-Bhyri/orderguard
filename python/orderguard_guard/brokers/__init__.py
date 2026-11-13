"""Optional broker adapters behind the `orderguard_guard.broker.Broker` protocol. None is wired in by default and none sends anything unless
it is explicitly constructed with dry_run=False AND reached through its router after an `allow`."""
from .binance_testnet import BinanceTestnetBroker, NotConfigured, NotRouted, TESTNET_BASE_URL, TestnetRouter
from .futu_sim import FutuSimBroker

__all__ = ["BinanceTestnetBroker", "TestnetRouter", "NotConfigured", "NotRouted", "TESTNET_BASE_URL", "FutuSimBroker"]
