# Walkthrough

How OrderGuard Verify works, in the order you would explain it. One small Python package, `orderguard_verify/`, in four parts: `core/` (domain-neutral: knows nothing about orders, filings or prices; a test enforces that), `finance/` (the first domain pack), `grader/` (the independent scorer, standard library only) and `native/` (the test on memos nobody prepared).

## The one rule

**LLMs read and interpret. Code decides.**

A model is used in two places, and in both it only *reads*:

1. `core/extractor.py` (with the finance prompt in `finance/extraction.py`) turns a memo into a list of claims ("FY2024 revenue was $412.4 billion", "sources say X is in talks to buy Y").
2. `finance/verifier.resolve_metric` looks up a definition when a claim uses an unfamiliar word ("net sales" means `revenue`). Common wordings ("gross margin", "free cash flow") are matched by a plain word list first; the model is only the fallback.

Everything that decides is plain code: comparing numbers, labelling claims, choosing pass / revise / block / escalate, applying the mandate.

## The path of one memo

```
text + (ticker, date)
   ├─ finance/sources.ensure         fetch the company's filings from SEC EDGAR the first time it is asked for (cached, polite about rate limits)
   ├─ core/extractor.extract         LLM reads the memo into claims; code drops any claim whose quote is not really in the memo
   ├─ finance/verifier.verify        code: look up the figure as of the memo's date, compare, label it
   │      confirmed / contradicted / stale / unverifiable
   ├─ core/decision.decide           code only: pass / revise / block / escalate   (the table in DEFEND.md)
   └─ core/gateway                   saves it to the decision log; if an order came with it, finance/pack.step maps the decision to the order
```

`core/pipeline.check()` is the first four lines in about 60. It never raises on bad input: an unknown ticker, an empty memo, a missing key or a model that is down each give **escalate** with the reason, and the result says how many of the checkable claims could be checked (**coverage**).

## The truth store (`finance/truth_store.py`, `finance/edgar.py`)

A SQLite table of dated facts: company, measure, period, value, **when it became public** (`as_of`), source URL, a hash of the source record. Fundamentals come from SEC EDGAR "company facts": revenue, net income, operating income, gross profit, diluted EPS, operating cash flow, capex, R&D. 30 companies ship in the repo; any other US-GAAP filer is fetched on demand.

The design choice that matters most: **lookups take a decision date and never return anything filed after it.** If a company restated 2022 revenue in 2024, a 2023 memo is judged against the 2023 number and a 2025 memo against the restated one. The restated version is kept as a separate row, so "true once, stale now" is something the verifier can say.

Fiscal-year labels come from the period-end date, plus each company's own naming read from its 10-Ks (Lululemon calls the year ending January 2024 "fiscal 2023"; SEC's `fy` field in the filing says so). Margins and free cash flow are not stored; they are worked out in code from two stored figures of the same period.

## The verifier (`finance/verifier.py`)

| Label | Meaning |
|---|---|
| confirmed | the filings agree (within the rounding the memo implies: one unit of the last digit it states, 0.1% to 2%; EPS to the cent; growth within 1.5 points; margins within a point) |
| contradicted | the filings disagree |
| stale | the claim matched an older version (restated since) or an older period |
| unverifiable | no source can settle it: rumours, opinions, measures not stored, data not public on the memo's date |

When a memo names a fiscal year and also gives a period-end date that disagrees, the year's name wins (memos get dates wrong more often than years).

## The decision table (`core/decision.py`, about 40 lines)

See [`DEFEND.md`](DEFEND.md). A figure the source proves was not yet public on the memo's date (a memo dated before the filing it quotes) is revised, not passed. Two choices worth defending: facts about the company, and every rumour, are forced to "key" by code, so a model cannot hide a false number by calling it unimportant; and sentiment can never carry a memo by itself.

## What happens to an order (`finance/pack.py: step`, `finance/mandate.py`)

The text decision maps to an order status in a four-line table: pass is cleared, revise is returned with the claims to fix, block is blocked, escalate is held for a human (approve or reject on the review page). The mandate is what the human signed (allowed tickers, sides, order size, notional); it is checked in code, fails closed, is never shown to the agent, and an order outside it is blocked whatever the memo says. Nothing is sent anywhere: "cleared" is a line in the decision log (`og log`). There is no order code, and a test fails if one appears. There is no size cut: shrinking an order would be a trading opinion.

## Three processes

* **Gateway** (`core/mcp_server.py`): an MCP server with the tools `propose_order`, `check_memo` and `order_status`.
* **Review page** (`core/review_ui.py`): shows an evidence card per decision, takes a pasted memo, and sends approvals to the gateway with a local token (the page itself cannot clear anything).
* **Eval runner** (`og native`, `og eval`, `og gate`).

`finance/agent.py` is a small *outside* research agent that talks to the gateway over MCP like any other client.

## How it is tested

Two tests, kept apart on purpose.

1. **The development set** (`data/eval/`, `og eval`): 80 synthetic memos written by me from the truth store, with planted false figures, stale figures, rumours, sentiment and out-of-mandate orders, plus honest twins. It is a development set: I tuned against it. It can show that rules fire; it cannot show how the checker does on text nobody prepared.
2. **The native-error test** (`docs/PROTOCOL.md`, `native/`): models draft memos from memory with no documents, so every figure is a natural truth or a natural mistake. A separate labelling agent labels each claim from the filing documents. Companies are split by name: tuned on 9, run once on 16. Four arms are scored by an independent grader: no checker, a prompt-only judge from the same model family, a prompt-only judge from another family (both shown the same filing figures the engine reads), and the engine.

The grader (`grader/score.py`) imports only the standard library, a test enforces it, and a canary test shows an inverted grader fails. It counts a false claim as *flagged* (the sentence was marked wrong) and as *named* (the figure itself was); an earlier one-quote-answers-one-label count favoured the engine and is superseded (see the protocol history). On this test the arms tie at memo level and nearly at sentence level; the engine's difference is naming the exact figure with evidence.

## What it deliberately does not do

* It cannot tell whether an idea is *good*; it checks facts.
* It does not verify rumours. It escalates when they carry the memo and asks for them to be removed otherwise.
* It does not check segments, guidance, share prices, quarterly figures or non-US-GAAP filers; it says so and escalates when nothing could be checked.
* No Hong Kong data: HKEX's terms restrict scripted access and data mining.
* No real orders, no Futu trading. Unaffiliated with Futu or any broker.
