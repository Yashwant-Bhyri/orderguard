# OrderGuard as an MCP server

`python -m orderguard_mcp` starts a Model Context Protocol server (stdio) that exposes the guard itself. Any MCP client (Claude Desktop, Claude Code, another agent framework) can call OrderGuard before it trades: screen untrusted text, check an order against the human-signed mandate and SEC filings, look up the figure a company actually reported, test a standing rule, and, only when a receiver is configured, place an order through it.

The principle is the one in [ARCHITECTURE.md](ARCHITECTURE.md): the decision rests on numbers the agent cannot touch. The caller supplies the proposal; the mandate, the trusted prices, the filed figures and the clock all come from the server's own configuration.

## Install and run

The server needs the `orderguard` package (the `mcp` SDK is already a dependency). From a source checkout:

```sh
cd /path/to/orderguard
.venv/bin/python -m pip install -e .          # once; or put /path/to/orderguard/python on PYTHONPATH
.venv/bin/python -m orderguard_mcp --print-config
```

The server speaks JSON-RPC on stdin/stdout, so it prints nothing else there; diagnostics go to stderr. Run it from a client, not by hand.

### Configuration

| Variable | Effect |
|---|---|
| `ORDERGUARD_HOME` | The config directory made by `orderguard init`. `mandate.json` is verified against `signing.pub` (the private `signing.key` is never read). Unset or no `mandate.json`: a clearly labelled **demo mandate** is used. |
| `ORDERGUARD_RECEIVER_URL` | The L8 receiver, e.g. `http://127.0.0.1:8700`. Without it `submit_order` refuses. |
| `OG_LLM` | `replay` (recordings only, no network at all), `record` or `live`. Anything but `replay` needs a provider key for the model screen. |
| `OG_PROVIDER`, `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY`, `OG_BUDGET_USD` | Optional: enable the L2 model screen, with its hard spend ceiling. Without a key `screen_text` still works on its local checks. |
| `ORDERGUARD_OFFLINE=1` | Never fetch filings from the network; read only the local truth store. (Implied by `OG_LLM=replay`.) |
| `ORDERGUARD_REQUIRE_FIGURES=1` | Every order must cite at least one reported figure (otherwise `check_order` refuses). |

### Claude Desktop

Add to `claude_desktop_config.json` (use your own paths):

```json
{
  "mcpServers": {
    "orderguard": {
      "command": "/path/to/orderguard/.venv/bin/python",
      "args": ["-m", "orderguard_mcp"],
      "env": {
        "ORDERGUARD_HOME": "/path/to/orderguard-config",
        "ORDERGUARD_RECEIVER_URL": "http://127.0.0.1:8700"
      }
    }
  }
}
```

Put provider keys in the environment or the config directory's `.env`, not in this file if it is shared. Leave `ORDERGUARD_RECEIVER_URL` out to make the server preview-only.

### Claude Code

```sh
claude mcp add --env ORDERGUARD_HOME=/path/to/orderguard-config orderguard -- /path/to/orderguard/.venv/bin/python -m orderguard_mcp
```

After the `orderguard-mcp` console script is added to `pyproject.toml` the command becomes `claude mcp add orderguard -- /path/to/orderguard/.venv/bin/orderguard-mcp`.

## Tools

Every tool returns a JSON object (also as MCP structured content) with `"ok": true`, or `{"ok": false, "error": {"type", "message"}}`. `error.type` is `invalid_input` (the arguments are wrong; `details` lists each field) or `internal` (the exception type only, never a traceback). A schema violation caught by the MCP SDK before the tool runs comes back as an ordinary MCP tool error with the same kind of message. Dates are `YYYY-MM-DD`.

| Tool | Layers | Arguments | Returns |
|---|---|---|---|
| `screen_text` | L1, L2 | `text` (up to 100,000 chars), `kind`: `doc` / `web` / `feed` / `tool` (default `tool`) | `verdict` (`quarantine` / `clean` / `unknown`), `category`, `l1` counts, `classifier` (`p_attack`, `label`), `model_screen` (`status: ok / unavailable`), `suggested_replacement` when quarantined, `untrusted` (quoted material) |
| `check_order` | L5, L6 | `ticker`, `side`, `quantity` (whole shares), `limit_price`, optional `key_figures[]`, `daily_total_usd`, `as_of` | `decision` (`allow` / `hold` / `refuse`), `reasons`, `mandate` (source, id, signature_verified), `numbers` (claimed limit vs trusted price, notional at each, band, daily total), `figures[]` (claimed vs trusted value, status) |
| `verify_figures` | L6 | `ticker`, `as_of`, `figures[]` | per figure `status` (`confirmed` / `contradicted` / `stale` / `not_public_yet` / `unverifiable`), `trusted_value`, `reason`, `source`; `blocking` |
| `get_reported_figure` | L6 | `ticker`, `metric`, `fiscal_year`, optional `as_of` | `available`, the filed `value`, `unit`, `source` (form, filing date) or a `reason` |
| `evaluate_rules` | L7 | `rules[]`, `events[]`, optional `quarantined_sources`, `blast_source`, `lies`, `min_sources` | `decisions[]` (`fires`, `held_reason`, `notional`), the naive baseline, `blast_radius[]` for one lying source |
| `get_mandate` | L5 | none | the active mandate's limits, `source` (`configured` / `demo`), `signature_verified`, `problem` |
| `review_mandate` | L5, arena | optional `draft`, `source`, `mode` (`fit` / `estimate` / `simulate` / `rank` / `search`), `seed`, `agents`, `steps`, `regime`, `limits` | verified parent and suggested draft, a single draft review, or a batch of contained drafts with a ranking preview or measured outcomes |
| `submit_order` | L5, L6, L8 | as `check_order` plus a required `idempotency_key` | `submitted`, `status` (`filled` / `held` / `rejected` / `refused`), `order_id`, `reason`, `gate` |

A `figure` is `{metric, fiscal_year, value, unit?, period?}`: `metric` is one of revenue, net_income, eps_diluted, eps_basic, operating_income, operating_cash_flow, gross_profit; `value` is a number or text such as `"$94.9B"`; `unit` is `USD`, `USD millions`, `USD billions` or `USD/share` (default: USD/share for EPS, otherwise USD millions); `period` is `FY` (default) or `Q1` to `Q4`. A rule is `{id, kind: pct_change | event, inputs[], threshold, notional, side, text?, match?, tickers?}`; an event is `{type: quote_change | headline | notice, src, ticker?, pct?, text?, origin?}`. The exact JSON Schemas are what `tools/list` returns.

The seven checking and review tools are read-only. `submit_order` is the only tool that can write to the receiver.

Call `review_mandate` with `mode` set to `rank` or `search` and omit `draft` to generate alternatives. The optional `limits` object accepts `bad_allowed_usd_per_day`, `false_refusal_rate` as a fraction, and `holds_per_day`. The tool returns its review as JSON text. [Mandate review walkthrough](ARENA.md#review-a-draft-against-a-signed-policy)

### How `check_order` decides

1. The mandate is read from `ORDERGUARD_HOME` and verified (signature, expiry, revocation). A configured mandate that is unreadable, unsigned, altered or expired is **refused, never replaced by the demo mandate**.
2. The ticker is normalised (a look-alike Cyrillic or Greek letter is refused) and must be on the allow-list; the side must be allowed.
3. The order is valued at the **trusted price** (a quote from the server, else the mandate's `referencePrices`), not at the limit price you gave. Per-order cap, the day's running total, price band and step-up hold follow from that. The reply shows the claimed and the trusted numbers side by side.
4. Each cited figure is compared with SEC filings public on `as_of`. A contradicted, stale or not-yet-public figure refuses; an unverifiable one holds.

`as_of` selects the date for filings and quotes only. The expiry of the mandate is judged by the server's real clock, so an old `as_of` cannot revive an expired mandate, and a future `as_of` is rejected.

## Resources and prompt

| Name | What it is |
|---|---|
| `orderguard://mandate` | JSON: the active mandate summary and whether its signature verifies (same as `get_mandate`). |
| `orderguard://layers` | Text: what each of L1 to L8 checks and which tool exposes it. |
| prompt `guarded_trade` (optional `ticker`, `side`) | The sequence an agent should follow: read the mandate, screen untrusted text, test standing rules, look figures up instead of recalling them, `check_order`, and only after `allow`, `submit_order`. |

## Safety model

- **No money movement.** There is no transfer, withdrawal or wire tool, and the order path only accepts buy and sell of an allow-listed ticker. A list of tools that contained one would be a bug; a test asserts none exists.
- **Orders only through L8.** `submit_order` builds a `broker.OrderRouter` over a `ReceiverPaperBroker` and sends to the receiver only after an `allow`. It refuses when `ORDERGUARD_RECEIVER_URL` is unset or invalid, and it refuses when the mandate is the demo one: the demo mandate is for previews. The router is idempotent on `idempotency_key` (a repeat returns the first result and never reaches the receiver twice; reusing a key for a different order is refused), and the receiver, which re-checks everything and owns the ledger, remains the final authority. The receiver URL is never echoed.
- **The caller cannot choose the trusted numbers.** There is no price, mandate or limit argument. `daily_total_usd` is the caller's own running total and only tightens or loosens the daily cap check; the receiver holds the real one.
- **Inputs are validated** with strict schemas (enums, bounds, lengths, patterns, finite numbers) both by the SDK and again inside each tool, so an in-process call is as strict as a protocol call. Text is capped at 100,000 characters, figures at 20, rules at 50, events at 2,000.
- **Errors are data.** Failures return structured `ok: false` results; the server never returns a traceback and logs only exception types, to stderr.
- **No secrets in outputs.** `signing.key` is never read. Keys and the config directory path are never returned.
- **Echoed text is marked as data.** Anything quoted from the input (hidden-character findings, text excerpts, the model's rationale) sits under an `untrusted` key or is covered by a `data_notice`. A tool result can contain attacker text; the guard never treats it as an instruction, and the `guarded_trade` prompt tells the agent the same.
- **Fail closed.** A broken mandate, a figure checker that errors, an unreachable receiver: each ends in `refuse` or `unavailable`, never in a silent allow. `unknown` from `screen_text` means only the local checks ran; it is not a clearance.
- **It is a pre-trade guard, not a sandbox.** An agent that has another way to reach a broker can bypass it. Pair it with the L8 receiver, which is the only path to an effect in this repository.

## Relation to the TypeScript receiver server

[packages/mcp-server](../packages/mcp-server/README.md) is a different server with a different job. It fronts the **L8 receiver**: `get_mandate`, `propose_order`, `order_status` and `cancel` talk to the receiver's HTTP routes, which own budget, idempotency, revocation and the paper ledger. It has no screening, no figure checking and no trigger graph.

`orderguard_mcp` (this page) is the **guard in front of the decision**: L1 to L7 as tools, plus an optional `submit_order` that reaches the same receiver through the Python client. Use the Python server when you want an agent to check what it believes and what it is about to do; use the TypeScript server when you want an agent to talk to the receiver directly. They can run side by side; an agent configured with both should call `check_order` here before `propose_order` there. Both expose a tool named `get_mandate`: this one reads the signed mandate file and verifies it locally, the TypeScript one asks the receiver.

## Tests

`python/tests/mcp/test_mcp_server.py` calls every tool in-process and round-trips a real client session over the SDK's in-memory transport (tool list and schemas, structured results, resources, prompt). It runs offline with `OG_LLM=replay`:

```sh
OG_LLM=replay .venv/bin/python -m pytest -q python/tests/mcp
```
