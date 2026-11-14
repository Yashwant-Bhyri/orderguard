# Quickstart: from clone to a refused order

Goal: your agent proposes an order the signed mandate does not allow, and you see it refused with a plain-language reason. Pick the section for the language you use: [Python](#python), [HTTP](#http), [Node](#node) or [MCP](#mcp). Each one runs offline, with no API key, no model and no money: orders are checked and, at most, written to a paper ledger.

## Set up once

You need Python 3.11+ and, for the Node and MCP-over-Node parts, Node 22.13+ (the receiver uses Node's built-in SQLite). From a clone:

```sh
sh scripts/quickstart.sh --no-serve --skip-tests     # venv, install, npm ci, signing key and signed mandate
```

Add `--skip-node` if you only need Python and HTTP. The script is safe to re-run and never overwrites your signing key. If it stops, it prints `ERROR:` and `How to fix:`.

What the examples enforce: a **mandate** is a JSON file of limits (symbols, sides, per-order and daily caps, price band, a size above which a human must approve) signed with the owner's key. Orders are valued at a **trusted price** the agent cannot set. The decision is `allow`, `hold` (a human decides) or `refuse`, always with reasons.

| You use | Run | Takes (measured, after setup) |
|---|---|---|
| Python | `.venv/bin/python examples/python/guarded_agent.py` | 0.2 s |
| HTTP | `.venv/bin/orderguard serve`, then `sh examples/http/check_order.sh` | 0.1 s after the server is up (0.2 s to start) |
| Node | `node examples/node/check-order.mjs` | 1 s |
| MCP | `.venv/bin/python examples/mcp/list_tools.py` | 0.7 s |

## Python

```sh
.venv/bin/python examples/python/guarded_agent.py
```

A scripted toy agent (no model) places three orders through `run_agent` with the signed mandate in force. The second is sized from a forged "10-for-1 split" notice:

```
1. buy 10 AAPL @ 222.70   ALLOW   -> filled on the paper ledger as P-00001
2. buy 440 AAPL @ 22.30   REFUSE
     The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000.
     ...
3. buy 43 AAPL @ 222.70   HOLD
     The order is worth $9,576, above the $9,500 step-up threshold, so a human must approve it.
```

The refused and held orders never reach the broker object; read `main` in the file, it is about thirty lines. To put the guard in front of your own broker call, you need only the gate:

```python
import datetime as dt, json
from pathlib import Path
from orderguard_guard import gate as G
from orderguard_guard.market import SimMarket

home = Path("var/orderguard")                                   # what `orderguard init` made
mandate = json.loads((home / "mandate.json").read_text())
owner_pub = G.public_key_from_b64((home / "signing.pub").read_text().strip())   # the owner's key, never a key inside the mandate
today = dt.date.today().isoformat()
market = SimMarket({"AAPL": 200.00}, as_of=f"{today}T15:00:00Z")               # your trusted quote source goes here
guard = G.OrderGate(mandate, market, public_key=owner_pub)

verdict = guard.evaluate({"ticker": "AAPL", "side": "buy", "quantity": 440, "limit_price": 20.00},
                         {"daily_total_usd": 0, "as_of": today})
print(verdict["decision"], verdict["reasons"])                 # refuse, with reasons; place the order only on "allow"
```

`evaluate` never raises: anything it cannot read becomes a refusal with a reason. Pass your running daily total in `daily_total_usd`. To run your own agent loop under `run_agent`, give it a model object with `.chat(messages, tools=...)` and a broker object with `tools(arm)`, `call(name, args)`, `market`, `mandate` and `as_of` (the `ToyBroker` in the example is exactly that). Try your own mandate with `--mandate var/orderguard/mandate.json`; the example checks its signature first and says what to fix if it is missing or edited.

## HTTP

Terminal 1:

```sh
.venv/bin/orderguard serve                      # http://127.0.0.1:8600; --port N if 8600 is taken
```

Terminal 2:

```sh
sh examples/http/check_order.sh                 # or: sh examples/http/check_order.sh http://127.0.0.1:9000
```

It sends three orders to `POST /api/check-order` with curl and prints `allow`, `refuse` and `hold`, each with its reasons. It needs only curl and exits 0 when the three decisions are as expected, so it also works as a smoke test. One request by hand:

```sh
curl -s http://127.0.0.1:8600/api/check-order -H "Content-Type: application/json" \
  -d '{"order":{"ticker":"AAPL","side":"buy","quantity":440,"limit_price":22.30}}'
```

- **Token.** If the server was started with `ORDERGUARD_APP_TOKEN`, every request needs `-H "Authorization: Bearer $ORDERGUARD_APP_TOKEN"`; the script adds it when the variable is set and tells you when it is missing. Set a token before binding anything but loopback.
- **Your mandate.** With no `mandate` field the server uses a built-in demo mandate (AAPL and MSFT, buy only, $10,000 per order) and demo prices. To use yours, add `"mandate": {"mandate": <the contents of mandate.json>, "public_key": "<signing.pub>"}` and `"prices": {"AAPL": 200}` to the body; the signature is checked against `public_key`. Fields are listed in [API.md](API.md#post-apicheck-order).
- **Mistakes.** A body sent without `Content-Type: application/json` (curl's default is form data) gets a 422 with a `hint`. A server that is not running makes the script print how to start it.

## Node

```sh
node examples/node/check-order.mjs
```

The example starts a throwaway LocalSim paper receiver on a free loopback port, has a synthetic owner sign a mandate (buy AAPL, up to 10 shares), then uses the SDK in `packages/sdk` the way an agent would:

```
allowed  buy 1 AAPL -> filled (paper:run-<id>)
refused  sell 1 AAPL -> HTTP 409: The distributed risk engine did not approve this paper proposal: mandate_action_out_of_scope
refused  buy 500 AAPL -> order-notional: Estimated notional is $109210.00 USD equivalent, above the $12,500 illustrative limit.
```

It removes everything on exit. Needs Node 22.13+ and `npm ci` (the setup script ran it); a too-old Node or a missing `node_modules` gets a one-line fix instead of a stack trace. If it says it cannot listen on a port (EPERM), your environment forbids local servers; run outside the sandbox.

The SDK is a small client with no signing key, written in plain JavaScript with types in `packages/sdk/src/index.d.ts`:

```js
import { OrderGuardClient } from "@orderguard/sdk";             // or ../../packages/sdk/src/index.js from this repository

const orderguard = new OrderGuardClient({ baseUrl: process.env.ORDERGUARD_URL, token: process.env.ORDERGUARD_BEARER_TOKEN });
const { mandates } = await orderguard.getMandate();
const result = await orderguard.proposeOrder({ mandateId: mandates.find((m) => m.active).mandateId, symbol: "AAPL", side: "sell", quantity: 1 });
if (result.state === "denied" || result.state === "proposal_denied") console.log(result.reason);   // never dispatched: venueDispatchAttempted is false
```

Two things to know before pointing it at your own receiver. The SDK speaks the mesh receiver's routes (`/api/human-mandate/status`, `/api/chat`, `/api/paper-orders`, `/api/snapshot`), which `receiver/r5/server.ts` serves on `http://127.0.0.1:4173` by default (`ORDERGUARD_LEDGER_DB=var/r5.sqlite node --import tsx receiver/r5/server.ts`; it prints a one-time owner pairing code). The bridge on port 8700 (`node receiver/bridge/serve.mjs`) is a different, Python-facing API and does not serve these routes. And the mandate there is created by the owner's passkey ceremony, not by `orderguard init`; the SDK only reads it, so an agent cannot widen its own authority. A refusal at preview carries the receiver's reason in `result.reason` and `result.findings`.

## MCP

Check that the server starts and lists its tools, with no client and no network:

```sh
.venv/bin/python -m orderguard_mcp --list-tools                  # 10 tools, then exit
.venv/bin/python examples/mcp/list_tools.py                      # a tiny client: spawns the server over stdio, lists tools, gets a refusal
node examples/mcp/list-tools.mjs                                 # the same for the Node receiver server (4 tools)
```

The client output ends with the refusal an agent would see:

```
check_order buy 440 AAPL @ 22.30 -> REFUSE
  The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000.
```

Then give the server to your client. `orderguard-mcp --print-config` prints a block with this checkout's absolute paths, ready to paste.

**Claude Desktop.** Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`; Windows: `%APPDATA%\Claude\`), replacing `/path/to/orderguard`, then restart Claude Desktop ([examples/mcp/claude_desktop_config.json](../examples/mcp/claude_desktop_config.json)):

```json
{
  "mcpServers": {
    "orderguard": {
      "command": "/path/to/orderguard/.venv/bin/python",
      "args": ["-m", "orderguard_mcp"],
      "env": { "OG_LLM": "replay" }
    }
  }
}
```

**Claude Code.**

```sh
claude mcp add --env OG_LLM=replay orderguard -- /path/to/orderguard/.venv/bin/python -m orderguard_mcp
```

**Any other MCP client.** Register a stdio server: command `/path/to/orderguard/.venv/bin/python`, arguments `-m orderguard_mcp`, optional environment variables as above. With the official Python SDK that is `StdioServerParameters(command=..., args=["-m", "orderguard_mcp"])` and `stdio_client(...)`, exactly as in `examples/mcp/list_tools.py`.

Ask the agent to buy 440 AAPL at 22.30 and it should call `check_order` and report the refusal. By default the server uses a labelled **demo mandate**, and `get_mandate` and every `check_order` result say so. To use yours, add `"ORDERGUARD_HOME": "/absolute/path/to/var/orderguard"` to `env` (the directory `orderguard init` made); if that directory has no `mandate.json` the label says so instead of silently falling back. `submit_order` places nothing unless `ORDERGUARD_RECEIVER_URL` is set and a configured mandate is in use. Tool details: [MCP.md](MCP.md).

The Node receiver server ([examples/mcp/receiver-server.json](../examples/mcp/receiver-server.json), `node /path/to/orderguard/bin/orderguard-mcp.js`) is the thin adapter over the receiver described in the Node section; use it when the agent should talk to the receiver directly, and `orderguard` above when it should check before it acts.

## If something goes wrong

| You see | Do this |
|---|---|
| `orderguard is not installed in this Python` | Run the setup script, then use `.venv/bin/python`, not the system `python3`. |
| `Node 20.x is too old ... needs Node 22.13` | `nvm install 22 && nvm use 22`, then run it again. The Python and HTTP parts do not need Node. |
| `The Node dependencies are not installed` | `npm ci` in the repository root. |
| `No mandate at ...` / `No owner public key at ...` | `.venv/bin/orderguard init` makes `var/orderguard/mandate.json` and `signing.pub`. |
| `the mandate's signature does not match its contents` | You edited `mandate.json`: `.venv/bin/orderguard init --resign`. |
| `cannot listen on 127.0.0.1:8600 (Address already in use)` | `orderguard serve --port 8601`, and pass that address to the script. |
| `could not reach http://127.0.0.1:8600` | Start `orderguard serve` first, in another terminal. |
| `the server wants a token` | `export ORDERGUARD_APP_TOKEN=...` with the value the server was started with. |
| `listen EPERM` / `does not allow listening on a local port` | A sandbox forbids local servers. Run outside it, or allow local binding. |
| `ORDERGUARD_HOME is set, but that directory has no mandate.json` | Fix the path, or run `orderguard init --dir <path>`. |
| `no DEEPSEEK_API_KEY in the environment` | Only for live model calls. Use `OG_LLM=replay`, or `OG_ENV_FILE=var/orderguard/.env` with the key filled in. |
| `OG_LLM=replay and no recorded response` | Replay serves only recorded runs. Give `run_agent` your own model object, or record with a key and a low `OG_BUDGET_USD`. |

More: [GUIDE.md](GUIDE.md#troubleshooting). What this does not prove: the mandate check allows any order that fits inside the signed limits, so choose limits you would accept being used in full ([README, Honest limits](../README.md#honest-limits)).
