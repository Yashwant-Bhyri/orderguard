"""Composition root: wire the domain-neutral core to the finance pack and run one of the processes.

    python -m orderguard_verify.serve gateway     # MCP gateway on :8765, the only process that carries anything out
    python -m orderguard_verify.serve ui          # review page on :8766
"""
from __future__ import annotations

import logging
import sys

import uvicorn

from .core.gateway import Gateway
from .core.mcp_server import build
from .core.review_ui import UI_PORT, make_app
from .finance.pack import FinancePack, make_pack
from .paths import DB

INSTRUCTIONS = ("Check a research memo against SEC filings (check_memo), or propose an order with the memo it rests on (propose_order). "
                "The memo gets pass, revise, block or escalate; an order is then cleared, returned for fixes, held for a human or blocked.")


def gateway_main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.CRITICAL)   # benign "stream closed" noise when a client disconnects
    build(Gateway(make_pack(refresh=True, on_demand=True), db_path=DB), INSTRUCTIONS).run(transport="streamable-http")


def ui_main() -> None:
    app = make_app(DB, FinancePack.form_fields, FinancePack.form_hint)
    print(f"review page: http://127.0.0.1:{UI_PORT}\nreview token (needed to approve or reject; new every start): {app.state.token}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=UI_PORT, log_level="warning")


if __name__ == "__main__":
    {"gateway": gateway_main, "ui": ui_main}[sys.argv[1]]()
