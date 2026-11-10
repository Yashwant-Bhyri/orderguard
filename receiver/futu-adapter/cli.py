"""Entry point for the OrderGuard OpenD SIMULATE adapter.

The ledger and dispatch implementation remains shared with the mesh's existing
paper-order bridge. This package owns its routing config and the supported CLI
entrypoint; it never adds a REAL or unlock path.
"""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
MESH_ROOT = PACKAGE_DIR.parent
os.environ.setdefault("ORDERGUARD_FUTU_CONFIG", str(PACKAGE_DIR / "config.json"))
sys.path.insert(0, str(MESH_ROOT))

import futu_simulate_adapter  # noqa: E402


def preflight() -> int:
    """Read only: verify exactly one active HK SIMULATE stock account."""
    core = futu_simulate_adapter
    gateway = None
    quote_context = None
    try:
        core._assert_environment_gate()
        gateway = core.FutuOpenDGateway("HK")
        account = core._account_for_market(gateway, "HK")
        quote_context = gateway.sdk.OpenQuoteContext(host=core.HOST, port=core.PORT)
        state_ret, global_state = quote_context.get_global_state()
        if state_ret != gateway.sdk.RET_OK or not isinstance(global_state, dict):
            raise core.AdapterError("opend_status_unavailable", "OpenD did not return its read-only global status.")
        result = {
            "ok": True,
            "state": "ready",
            "endpoint": f"{core.HOST}:{core.PORT}",
            "opend_server_version": global_state.get("server_ver"),
            "opend_program_status": global_state.get("program_status_type"),
            "market_hk": global_state.get("market_hk"),
            "quote_logged_in": global_state.get("qot_logined"),
            "trading_logged_in": global_state.get("trd_logined"),
            "market": "HK",
            "trd_env": core.TRD_ENV,
            "account_type": "STOCK",
            "paper_account": account["masked"],
            "unlock_called": False,
        }
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    except core.AdapterError as error:
        sys.stdout.write(json.dumps({"ok": False, "state": "refused", "code": error.code}, separators=(",", ":")) + "\n")
        return 2
    except Exception:
        # Do not emit SDK exceptions; they may contain account/session details.
        sys.stdout.write('{"ok":false,"state":"unknown","code":"adapter_internal_error"}\n')
        return 2
    finally:
        if quote_context is not None:
            try:
                quote_context.close()
            except Exception:
                pass
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass


def inventory() -> int:
    """Read the recent full HK SIMULATE order list for replay delta evidence."""
    core = futu_simulate_adapter
    try:
        result = core.read_live_order_inventory()
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    except core.AdapterError as error:
        sys.stdout.write(json.dumps({"ok": False, "state": "refused", "code": error.code}, separators=(",", ":")) + "\n")
        return 2
    except Exception:
        sys.stdout.write('{"ok":false,"state":"unknown","code":"adapter_internal_error"}\n')
        return 2


if __name__ == "__main__":
    if sys.argv[1:] == ["preflight"]:
        raise SystemExit(preflight())
    if sys.argv[1:] == ["inventory"]:
        raise SystemExit(inventory())
    raise SystemExit(futu_simulate_adapter.main())
