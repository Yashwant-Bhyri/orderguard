# L6: the figure check (`orderguard_verify`)

OrderGuard's sixth layer checks the figures an order relies on. A model reads a memo into claims; plain code compares each figure with SEC EDGAR filings that were public on the decision date and returns confirmed, contradicted, stale, not public yet, or unverifiable. Code, not a model, decides pass, revise, block or escalate.

## API (`python/orderguard_verify/api.py`, CONTRACT section 5.2)

```python
check_figures(ticker, as_of, figures, *, store=None, fetch=True) -> list[dict]
check_text(text, ticker, as_of, *, store=None, ask=ask_json, fetch=True) -> dict
```

A figure is `{"metric", "fiscal_year", "value", "unit"}` plus an optional `"period"` of `FY` (default) or `Q1` to `Q4`.

- **Metrics:** revenue, net_income, eps_diluted, eps_basic, operating_income, operating_cash_flow, gross_profit (aliases such as net_sales are accepted).
- **Units:** `USD`, `USD millions`, `USD billions`, `USD/share`, and model-style values such as `"$94.9B"`. `truth` in the result is in the figure's own normalised unit.
- **Fiscal years:** the company's own naming (NVIDIA's fiscal 2024 ended January 2024).
- **Tolerance:** half a unit of the last digit the figure states, never more than 2% of the filing's value.
- **Statuses:**
  - `confirmed`: matches the newest filing public on `as_of`.
  - `stale`: matches an older version that a later filing restated or superseded (for EPS the reason says if a stock split explains it).
  - `not_public_yet`: the period, or the matching revision, was filed after `as_of`.
  - `contradicted`: does not match. The reason names a quarterly figure cited as annual, a different year's figure (for example "matches FY2023"), or a unit slip of 1,000 or 1,000,000.
  - `unverifiable`: unknown metric, year, company or unit.
- `check_figures` never raises on bad input. `fetch=False` never touches the network.
- **Data:** SEC companyfacts, fetched on demand for any US-listed US-GAAP ticker and cached in the truth store (`data/verify/truth.db`; env `OG_TRUTH_DB` moves it). The SEC User-Agent comes from env `OG_SEC_UA` (default has no email). Requests are spaced at least 0.15 s apart (under 7 a second, SEC allows 10) with back-off on 429 and 5xx.

Offline tests: `python/tests/verify/test_api.py` with Apple and NVIDIA fixtures in `facts_fixtures.py`.

## Gateway and commands

`og check`, `og demo --no-wait`, `og eval`, `og native`, `og gate` and `og run` still work (`OG_LLM=replay` runs from recorded model answers, no model call). The gateway is an MCP server with `propose_order` and `check_memo`. The review page needs a per-boot random token, printed at startup, to approve or reject a held order.

Money-path fixes after the audit (tests in `python/tests/verify/test_money_path.py`): review token; ticker normalised (trim, NFKC, uppercase, ASCII only) and the order valued at the trusted quote with a price band (`price_band_pct`, default 5), never at its own limit price; the server sets `as_of` and the agent cannot; an empty memo is rejected, and a failed check is rejected instead of held; refresh and on-demand fetch work for tickers outside the shipped set.

## Honest limits

- The claim reader is a model. A claim it does not extract is not checked, and the result says how many checkable claims could be checked.
- Only US-GAAP annual and quarterly figures in the metric list are checked. Rumours, opinions, guidance, segments and non-US filers come back unverifiable. Quotes in the repository are synthetic.
- A figure rounded harder than the 2% cap allows is flagged. Later reclassifications count as restatements, so a truthful memo that quotes the original can be "stale".
- Labels in the benchmark were written by an agent and not human-reviewed (`docs/verify/SPOTCHECK.md` is blank). Hold-out numbers do not transfer to production; AUDIT.md section 5 lists why (base rate, no injected content, gross errors, one `as_of`).

## Evaluation results as corrected by the audit

Sources: `docs/verify/AUDIT.md`, `docs/verify/DEFEND.md`, `data/verify/results/`.

- **Flagged versus named.** On the hold-out (429 false claims), the engine flagged the wrong sentence on 377 (88%) and named the exact true figure on 365 (85%). The prompt-only judges flagged 376 and 343 but named only 217 and 215 (51% and 50%). The "named" win is partly an output-format effect (AUDIT section 3).
- **Honest-memo trade-off.** In 15 control memos with no false claim, every arm stopped 1 in the free run; in the paid rerun the engine stopped 4 of 15 and each judge 1 of 15. Of 62 true claims the engine flagged 6 (judges 9 and 15) excluding borderline claims, but 18 of 84 (judges 15 and 23) including them, so its edge disappears (DEFEND point 2). With n=15 a 25 to 30% false-stop rate cannot be ruled out.
- **Agent-labelled.** A second agent re-labelled 60 claims blind and agreed on 54 (90%); on the 50 where both gave true or false, 48 agreed. No human has reviewed the labels.
- **Regression gate (`og gate`):** baseline in `data/verify/results/gate_baseline.json`: 54 of 55 synthetic planted problems caught, 0 honest cases wrongly stopped.
