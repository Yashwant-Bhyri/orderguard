# Excluded sweep runs

`20261110T224017.jsonl`: the first live sandbox sweep (DeepSeek V4.1 Flash, 23 techniques x 1 seed, naive and full arms).
It is kept for the record but left out of docs/RESULTS.md, because two faults make its benign-twin (utility) numbers invalid:

1. The run's network sandbox allowed only the model API, so SEC EDGAR was unreachable. L6 could not verify any cited
   figure for tickers missing from the local truth store (Home Depot) and, failing closed, held those orders.
2. The world generator labelled fiscal years by the calendar year of the period end. Home Depot calls the year ending
   2024-01-28 fiscal 2023, so its "clean" twin worlds stated fiscal-2023 figures as fiscal 2024, and the L2 screen
   correctly quarantined them. Fixed in `sandbox/world.py` (`fiscal_year_name`), with a regression test.

What it still shows: no attack produced a harmful order in the full arm ($0 executed at trusted prices), and the bare
model executed none either. A clean live sweep needs to be rerun once there is credit.
