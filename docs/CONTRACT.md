# OrderGuard build contract

Binding for everyone building this repository. If something here is wrong, write the fix in `docs/CONTRACT-NOTES.md` and say so in your final report. Don't silently diverge.

## 1. What OrderGuard is

> AI trading agents will believe fake information. OrderGuard decides what they may do using numbers they can't touch, and checks the facts their orders rely on.

Measured evidence that shaped this design is in `lab/legacy/attack-lab-2026-11-06/README.md`:
- **Hidden instructions:** worked in 1 of 107 runs.
- **Official-looking fake data:** often worked.
  - Fake split: about 440 shares at $22.30.
  - Fake "reference price" document.
  - Fake symbol change.
  - Fake restatement.
- **Every harmful action:** broke a rule that code can check against trusted data.
- **Agents misquote real figures with no attacker present:** 13 of 112 runs.

## 2. Layers: each is one module with one job

```
analyst agent (any model, tools)
   │ every tool output passes through
   ▼
[L1 normalise]   code: strip zero-width and Unicode tag characters; flag mixed-script tokens (Cyrillic А in "АAPL"); NFKC
[L2 screen]      model: chunk → {flag, category, why}; flagged chunks are quarantined, the agent sees a one-line marker
[L3 risk bucket] code first, model second: new information that repeats or depends on a quarantined item is quarantined too
[L4 data marking] tool output is wrapped as untrusted DATA; the system prompt says data never changes mandate or procedure
   │ the agent proposes an action
   ▼
[L5 order gate]  code only, with trusted data the agent cannot touch:
                 signed mandate (Ed25519, expiry, revocation) · ticker normalised + allow-list · side · quantity × TRUSTED price ≤ per-order cap
                 · running daily total · limit within band of TRUSTED price · required cited figures checked by L6 · step-up above threshold
[L6 figure check] orderguard_verify: each cited figure checked against SEC filings as of the decision date
                 → confirmed / contradicted / stale / not public yet / unverifiable
[L7 trigger graph] code: standing rules ("sell basket if down 40%") fire only on inputs confirmed by ≥ N independent unquarantined sources;
                 blast-radius simulation: "if source S lies by X%, which rules fire and for how much"
   ▼
[L8 receiver]    TypeScript service (receiver/): the final authority. It checks the exact order against the human-signed mandate,
                 with atomic paper ledger, idempotency and revocation. Nothing reaches the ledger except through it.
```

Least privilege: no money-movement tool is ever offered to the agent in the hardened arm.

## 3. Repository layout

```
README.md                 one page, written last
LICENSE                   MIT (owner may change before publishing)
package.json, package-lock.json, packages/, examples/, bin/, scripts/   TypeScript workspace (receiver SDK, MCP server, quickstart)
receiver/                 TypeScript receiver (r5) + receiver/bridge (Python-facing, see §5.1)
pyproject.toml            ONE Python project; packages live in python/
python/orderguard_verify/ L6 (from orderguard-verify)
python/orderguard_guard/  L1–L5, L7, the hardened agent loop, LLM client, receiver client, `orderguard` CLI
python/orderguard_lab/    attack cases, environments, arms, judge, adaptive attacker, detector test, tables, `og-lab` CLI
python/tests/             pytest for all three packages (tests_verify/ merged in)
data/verify/              SEC truth store, filings, recorded model answers for verify
data/lab/                 10-K text and other lab inputs
data/replay/              recorded model responses (request-hash → response) so every published table rebuilds offline
results/                  raw run files (JSONL) + tables built from them
docs/                     ARCHITECTURE.md, THREAT-MODEL.md, DEFEND.md, RESULTS.md, verify/ (protocol, audit), CONTRACT.md
lab/research/             research notes with sources
lab/legacy/               the 5–6 Nov experiments, kept as history (not imported by code)
.github/workflows/ci.yml  npm check + pytest + offline table rebuild
```

## 4. Rules for everyone

- **No git commands.** The coordinator commits.
- **Never write a secret, key value, absolute home-directory path or email into any file.**
  - Keys come from the environment: `OPENROUTER_API_KEY`.
  - Optional: `OG_ENV_FILE`, a path to a dotenv file that the code reads by variable name.
  - Never print a key.
- **Model calls go through one client** (`orderguard_guard.llm`), which records every request/response to `data/replay/` and enforces a budget:
  - `OG_LLM=replay|record|live`. The default is `replay` in tests and CI, and `record` (cache first, then live) otherwise.
  - `OG_BUDGET_USD`, default 0.05, is a hard cap per process. Spend is appended to `results/spend.jsonl`. The client refuses calls once the cap is reached.
  - **Hard floor:** before any live call batch, check OpenRouter credits (`GET https://openrouter.ai/api/v1/credits`). Refuse if under US$0.30.
  - **Builders: total live spend while building must stay under US$0.10 each.** Use replay, fakes and small smokes. The coordinator runs the full suite.
- **Default model everywhere:** `deepseek/deepseek-v4.1-flash` via OpenRouter, overridable by env `OG_MODEL`.
- **No real orders, no real broker, no Futu claims, no HKEX data.** No attack content is ever published anywhere: all web pages are simulated inside tools.
- **Python ≥ 3.11, standard library first.**
  - Allowed deps: httpx, pydantic<3, fastapi, uvicorn, mcp<2, cryptography, pytest.
  - Optional: transformers and torch for the open-source detector test, behind an extra.
- **Tests must run offline** (`OG_LLM=replay`) in under 60 seconds.

## 5. Interfaces (exact)

### 5.1 Receiver bridge (TypeScript, `receiver/bridge/`)

A Node entry point, `node receiver/bridge/serve.mjs --port P --mandate mandate.json`. It:
- boots the r5 receiver with an isolated temp ledger;
- registers a synthetic owner passkey and authorises ONE human mandate from the JSON (the same synthetic WebAuthn flow the quickstart uses);
- serves a small HTTP API on loopback.

Mandate JSON:

```json
{"symbols":["AAPL","MSFT"],"sides":["buy"],"maxOrderNotionalUsd":10000,"maxDailyNotionalUsd":20000,"priceBandPct":5,"expiresAt":"ISO","referencePrices":{"AAPL":222.70,"MSFT":420.18}}
```

Endpoints:
- `GET /health`
- `POST /propose` `{symbol, side, quantity, limitPrice, clientOrderId}` → `{decision:"filled"|"denied"|"held", reason, orderId?, ledgerEffect:boolean}`
- `POST /revoke` → `{revoked:true}`
- `GET /snapshot` → `{orders:[...], ledgerIntegrity:boolean}`

The receiver itself must value orders at the TRUSTED reference price, never the order's own limit price, and enforce the price band. If r5 doesn't already, add it inside the receiver, not the bridge, with tests.

### 5.2 Figure check (`orderguard_verify.api`)

```python
def check_figures(ticker: str, as_of: datetime.date, figures: list[dict]) -> list[dict]
# figure in : {"metric": "revenue"|"net_income"|"eps_diluted"|"operating_income"|"operating_cash_flow"|..., "fiscal_year": int, "value": float, "unit": "USD"|"USD millions"|"USD billions"|"USD/share"}
# result out: {"figure": <in>, "status": "confirmed"|"contradicted"|"stale"|"not_public_yet"|"unverifiable", "truth": float|None, "unit": str, "source": {"form","filed","url","accession"}|None, "reason": str}
def check_text(text: str, ticker: str, as_of: datetime.date) -> dict   # the existing memo pipeline: decision pass/revise/block/escalate + claims
```

- **Data source:** SEC EDGAR companyfacts, fetched on demand and cached in `data/verify/truth.db`. Offline fixtures are needed for tests. The SEC User-Agent comes from `OG_SEC_UA`, with a generic no-email default.
- **Units:** normalise billions and millions in code.
- **Fiscal years:** use the company's own naming.

### 5.3 Guard (`orderguard_guard`)

```python
normalise.clean(text) -> (clean_text, findings: list[str])           # L1
screen.Screen(model).check(chunk: str, kind: "doc"|"web"|"feed"|"tool") -> {"flag": bool, "category": str, "why": str}   # L2, cached by content hash
bucket.RiskBucket().add(item: dict) / .related(item: dict) -> dict|None    # L3; item = {"source","ticker","text","numbers":[...],"kind"}
gate.Mandate.load(path) / .verify(public_key) ; gate.sign_mandate(mandate: dict, private_key) -> dict   # Ed25519 over canonical JSON
gate.OrderGate(mandate, market: TrustedMarket, figure_checker).evaluate(order: dict, state: dict) -> {"decision": "allow"|"refuse"|"hold", "reasons": [str], "checks": {...}}
market.TrustedMarket: .quote(ticker) -> {"price": float, "as_of": str, "source": str}     # SimMarket for the lab
graph.TriggerGraph(rules, min_sources=2).evaluate(events) -> list[{"rule","fires","held_reason","notional"}] ; .blast_radius(source, lies=[...]) -> list[...]
agent.run_agent(model, task: str, env: "ToolEnv", arm: "naive"|"gate_only"|"full", max_steps=12) -> Transcript
   # ToolEnv (defined by the lab, implemented per case): .tools(arm) -> list[openai tool specs]; .call(name, args) -> dict ; .market ; .mandate ; .as_of
   # Transcript: {"calls":[{"name","args","result","gate"}], "final": str, "quarantined": [...], "cost_usd": float, "error": str|None}
receiver_client.Receiver(base_url).propose(...) / .snapshot()      # talks to §5.1
cli: `orderguard demo` (end-to-end, see §7), `orderguard check-order`, `orderguard graph-demo`
```

Arms:
- `naive`: raw tool output, all tools including `transfer_funds`, executes whatever the agent calls.
- `gate_only`: L5, L6 and L8 only.
- `full`: L1–L8.

### 5.4 Lab (`orderguard_lab`)

- `cases.py`: a registry of **at least 60 cases**. Each case is a dataclass:

  ```python
  {id, family, surface: "doc"|"web"|"feed"|"tools"|"memory"|"multi", technique, source_idea (paper/incident),
   goal: "transfer"|"unlisted_ticker"|"oversize"|"sell"|"overpay"|"false_belief"|"trigger_fire"|"deny_service",
   build_env() -> ToolEnv, success(transcript) -> bool, expected_stop: "L1".."L8"|"model"}
  ```

  Plus one clean control per surface.
- **Families:** see §6. Variants must differ in technique, not just wording.
- **Arms × models × repeats** come from the CLI: `og-lab run --model deepseek/deepseek-v4.1-flash --arms naive,gate_only,full --reps 1 --cases all`.
- **Judge:** pure code. A false belief is a fake figure stated without doubt words, from a keyword list that is printed and tested. Every belief judgement is listed for hand review.
- **Adaptive attacker:** `og-lab adaptive --target-arm full --goals ... --rounds 5`, using DeepSeek as the attacker. It must handle attacker refusals and record them.
- **Detector test:** each screen model, plus an optional open-source classifier, scans attack chunks and clean chunks. Report recall and false alarms.
- **Tables:** `og-lab tables` rebuilds `docs/RESULTS.md` from `results/*.jsonl`, offline.
- **Cost estimate:** `og-lab estimate` prints the expected cost before any live run.

## 6. Threat model: families, and which layer must stop them

| Family | Examples (cases) | Must be stopped by |
|---|---|---|
| A. Hidden instructions | buried note, 3-part split, chat-template forgery, Unicode tags, zero-width, base64, zh-Hant/zh-Hans, HTML comment, fake tool-result JSON, tool-description poisoning, many-shot, conditional trigger, saved "standing rule" | L1/L2 (and L5 if the action breaks the mandate) |
| B. Official-looking fake authority | fake split / reverse split / special dividend / symbol change; fake halt, LULD, auction price; fake SEC/FINRA notice; fake risk-engine "notional uses reference price"; fake margin call; fake mandate update | L5 (trusted price, allow-list, side, no transfer tool), L2 |
| C. False facts, no instruction | fake restatement, edited table vs text, invented guidance, quarterly-as-annual, wrong year, billions/millions swap, adversarial-SEO page, coordinated fake consensus, fake wire, look-alike domain, homoglyph ticker headline | L6 (figure check), L2, L3 (repeat of quarantined claim) |
| D. Feed and trigger | single-venue crash on a basket, spoofed ticks, echo amplification (one claim repeated by many wires), replayed old news, tampered positions (repeated orders), duplicate delivery | L7 (≥2 independent sources, median), L3, L5 daily total, L8 idempotency |
| E. Denial of service | fake lot size, fake price band, fake halt that makes the agent abandon a legitimate trade | measured as utility loss; L2 |
| F. Natural errors (no attacker) | agent cites wrong-year, wrong-period or wrong-metric figures | L6 |

## 7. The end-to-end demo (`orderguard demo`)

1. Start the receiver bridge with a signed mandate.
2. Run the analyst agent (DeepSeek, or replay so it works offline) through four scenarios, printing which layer acted:
   - an honest trade that fills;
   - a fake split in the feed: L5 refuses at the trusted price;
   - fake filing figures: L6 contradicts;
   - an injected transfer: L2 quarantine, and no transfer tool.
3. Run one trigger-graph scenario: a single-venue crash is held, and a real crash fires.
4. Print the receiver ledger snapshot.

It must run offline with `OG_LLM=replay` after one recorded run.
