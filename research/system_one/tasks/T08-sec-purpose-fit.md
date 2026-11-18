---
id: T08
title: Real-world purpose fit - SEC N-PORT holdings against fund names (the 80% names rule)
depends:
worker: opencode-go/deepseek-v4.1-flash
isolate: false
check: bash run.sh
timeout_min: 150
max_rounds: 3
---

# T08. Purpose fit on real funds

Read `research/system_one/POLICY.md` first. Your task folder is `research/system_one/work/T08/`. Raw data goes in `research/system_one/data/sec/`, which git ignores. Keep it under 2 GB.

## Problem

System One judges whether a book still serves its stated purpose. Before any owner reviews anything, we want proof that "purpose against actual holdings" can be scored on **real** data. US registered funds give us exactly that:

- **Form N-PORT:** each fund files its full holdings. The SEC publishes structured quarterly data sets of these filings ("Form N-PORT Data Sets" on sec.gov).
- **The names rule** (Investment Company Act rule 35d-1, amended in 2023): a fund whose name suggests a focus (an asset class, sector, region or style, such as "Treasury", "Municipal", "Technology", "Small Cap", "Emerging Markets", "High Yield", "Dividend" or "ESG") must have a policy of investing at least 80% of its assets in line with that name.

So each fund gives us a stated purpose (its name) and an actual book (its holdings), with a legal line between the two.

## Build

1. **Download one recent quarter** of the N-PORT data sets. Read sec.gov's description of the tables first.
   - **Network etiquette:** send at most 10 requests per second, and use a User-Agent taken from the environment variable `SEC_USER_AGENT` if it is set. If it is not set, use `OrderGuard-Lab research`.
   - If the SEC refuses that agent, write BLOCKED.md saying that a contact User-Agent is needed. **Never invent an email address.**
2. **A names-rule classifier, `name_to_test`**, which maps a fund or series name to zero or more testable categories. Each category comes with a holdings predicate built from N-PORT fields: asset category, issuer category, investment country, maturity, fair-value level, and the issuer's industry where the data has it. Cover at least 8 categories:
   - US Treasury or government;
   - municipal;
   - high yield;
   - emerging markets;
   - a named sector;
   - small or mid cap, only if testable from the data, or else documented as not testable;
   - international or global;
   - equity or bond.

   Categories you cannot test from N-PORT fields alone must be documented as such, not guessed.
3. **The in-scope share for each fund:** the share of net assets in holdings that satisfy the predicate. Flag a fund when the share is below 80%. Note that the rule allows for derivatives and cash, and that some funds are exempt or have different policies. Report these as gray areas, and do not claim legal violations: say "below the 80% line by our test".
4. **Outputs:**
   - `work/T08/results.json`: the number of funds scored per category, the distribution of shares, and the number flagged;
   - `work/T08/flagged_sample.csv`: 30 random flagged funds with their series id, name, category, share and accession number;
   - `work/T08/clean_sample.csv`: 30 random unflagged funds;
   - a short `FINDINGS.md`: the five most interesting real cases, each with a link to the filing.
5. **The reviewer check (C5).** The reviewer checks the flagged sample against the actual filings on EDGAR. Make that easy: give a direct link per row.

## run.sh

1. Download, or reuse the cached data.
2. Parse it.
3. Score the funds.
4. Print the summary.
5. Run the tests: the name classifier on 30 hand-written names, including tricky ones like "Treasury Inflation-Protected" and "Global Technology"; and the share computation on a toy fund.

## Pass bar

- At least 1,000 real funds scored.
- The classifier is tested.
- Every flag carries a link.
- The gray areas are documented.
- The data stays under 2 GB.
- No email addresses or personal data anywhere.
