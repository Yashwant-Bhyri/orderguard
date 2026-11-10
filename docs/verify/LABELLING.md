# Labelling instructions (given verbatim to the labelling agent)

You are labelling research memos about ONE company. Work only from the folder you are given. It contains:

- `memos.txt`: one or more memos, each starting with a line `=== MEMO <memo_id> ===`.
- `10-K_<date>.txt`: the company's two most recent annual reports (10-K), converted to plain text. Table rows appear as lines with ` | ` between cells.

Do not look at any other file or folder, do not run any code from elsewhere, and do not use your memory of the company's figures: **the filings are the only truth**. (A model wrote each memo from memory; it may contain mistakes. Finding them is the job.)

## What to list

Every statement in a memo of a **reported company figure for a named fiscal year** that the filings could settle: revenue or net sales, gross profit, operating income, net income, earnings per share, operating cash flow, capital expenditure, R&D or other expense lines, cash, debt, share counts, dividends, buybacks, employee counts, segment revenue, and growth rates or margins built from them.

Do **not** list: share prices, market value, valuation multiples, forecasts, guidance, opinions or ratings, quarterly figures, anything about the future, or statements with no number.

If a memo says "latest" or "most recent" fiscal year, that means the newest 10-K in the folder. A figure given with no year and no "latest" is judged as if for the most recent fiscal year.

## What to write for each claim

- `quote`: the exact words from the memo (copy; do not paraphrase), as short as possible but containing the figure.
- `figure`: the number as written in the memo, copied from the quote (for example `$391 billion`, `2%`, `$6.13`).
- `verdict`: `true`, `false` or `not_in_filings` (the folder does not contain what is needed to decide).
- `borderline`: `true` if the call depends on rounding or interpretation (see below), else `false`.
- `error_class` (only for `false`): `wrong_figure` (the number matches no year in the filings), `wrong_period` (a real figure from a different fiscal year than the memo says), `wrong_growth` (a growth rate that does not follow from the filings), `wrong_derived` (a margin or ratio that does not follow), or `other`.
- `filing_value`: what the filing says, with the fiscal year, for example `FY2024 revenue 391,035 million`.
- `evidence`: the file name and a short verbatim excerpt (at most 200 characters) from the filing showing the number you relied on.

## How to decide true or false

- `true`: the memo's figure equals the filing's figure when the filing figure is rounded the way the memo rounded it ("$391 billion" is true for 391,035 million; "$391.0 billion" is true; "$390 billion" is false).
- If the memo hedges ("about", "roughly", "approximately", "~") and the difference is under 1%, call it `true`.
- `false`: clearly different. Borderline (set `borderline` true, and still give your best verdict): a difference between about 1% and 3% that rounding does not explain, or a fiscal-year name that is ambiguous for this company.
- Growth rates and margins: compute them yourself from the filing figures, show the arithmetic in `filing_value`, and judge against the percent the memo states.

## Output

Write `labels.json` in your folder:

```json
{"labeller": "claude-haiku subagent", "company": "<TICKER>",
 "memos": [{"memo_id": "...", "claims": [{"quote": "...", "figure": "...", "verdict": "true", "borderline": false,
            "error_class": null, "filing_value": "...", "evidence": "10-K_2024-11-01.txt: ..."}]}]}
```

Include every memo, even one with no claims (`"claims": []`). Report back only: the number of claims per memo and how many are false.
