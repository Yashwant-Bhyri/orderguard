# How to defend this in a room

One sentence: **it checks what an AI wrote against what was true on the date it was written, and decides in code.** A model only reads the text and lists its claims. Everything that decides is plain code you can read in ten minutes: `core/decision.py` (the table below) and `finance/verifier.py` (the comparisons).

## The decision table (`core/decision.py`, first rule that applies wins)

| # | If... | The text gets |
|---|---|---|
| 1 | a claim it depends on is **contradicted** by the filings | **block** (and alert) |
| 2 | such a claim is **stale** (true once, since restated or for another year) | **revise**, after one refresh and re-check |
| 2b | such a claim states a figure **not yet public** on the memo's date | **revise**, naming the claim (the code can prove it did not exist) |
| 3 | the **main reason** for the text cannot be verified | **escalate** to a human |
| 4 | **nothing** in it could be verified (opinion and rumour alone) | **escalate** |
| 5 | a side claim is wrong, or a **rumour** is stated as part of the case | **revise**, listing exactly those claims |
| 6 | otherwise | **pass**, and the card says how many claims it could not check |

Finance maps that to an order in one function (`finance/pack.py: step`): pass is **cleared**, revise **returned** with the claims to fix, block **blocked**, escalate **held** for a human; an order outside the mandate is blocked whatever the text says. Nothing is sent anywhere, and there is no size cut: shrinking an order would be a trading opinion.

## How the grader works (`grader/score.py`, about 130 lines)

- **Labels are not the checker's.** A separate agent (Claude Haiku) read each memo and the company's two latest 10-Ks as text and wrote per claim: true, false or not in the filings, with a verbatim excerpt. It never saw the truth store or any checker output (`docs/LABELLING.md`). Not human-reviewed until the 25-claim spot-check in `docs/SPOTCHECK.md` is done.
- **The grader imports only the standard library** (a test enforces it). It reads labels and one arm's output per memo.
- **Three counts.** A quote answers a label when it contains the label's figure and shares words. A false claim is **flagged** if any matching quote was marked wrong (the sentence), **named** if a matching quote holding only that figure was marked wrong (the figure). The older strict count let each quote answer one label only; it was asymmetric (judges quote several figures per sentence) and is superseded. No matching quote is a miss under all three.
- **Canary:** `grader/canary.py` has four fake arms with known answers; tests show an inverted grader and one that credits unextracted claims both fail it, and `og gate` fails when a broken checker is substituted.

## The hardest questions

**1. "Isn't this just a prompt to an LLM?"** For *finding* wrong figures, nearly yes. On the hold-out, given the same dated filing figures, the same-family judge flagged 376 of 429 false claims against the engine's 377 (other-family judge 343). Every arm stopped all 32 flawed memos, and with a median of 13 false claims per memo the test cannot separate them there. Under an independent matcher the judge is 1.5 to 3.5 points ahead, and in the paid run the engine is behind (342 against 352 and 347). Judges were as good or better on margins, free cash flow and growth, where the answer is arithmetic on the table. What the engine adds is **naming the exact figure**: 365 of 429 against 217 and 215 (partly an output-format effect; +12 points not +34 in the paid run), each with filing, date and hash. The decision step is deterministic given the claims; extraction run-to-run stability was not measured. That is attribution, not catching more. A test that could show more needs single-error memos from a stronger writer, with new labels.

**2. "Will it stop my honest memos?"** Unproven, and the evidence is mixed. Free run: of 62 true claims the engine flagged 6 (judges 9 and 15) when borderline claims are excluded, **but 18 of 84 (judges 15 and 23) when they are included**, so its edge disappears. In 15 control memos with no false claim every arm stopped 1; **in the paid rerun the engine stopped 4 of 15 and each judge 1 of 15**. With n=15 the data cannot rule out a 25 to 30% false-stop rate. Named causes: a 2% tolerance cap ("$0.09 billion" against a true $93 million), "above 50%" read as 50%, Walmart's total revenue read as net sales. A claim it cannot check passes, and the card says how many it could not check.

**3. "Where does the time idea show up?"** (Answer in one line: only in unit tests; the benchmark barely exercises it.)  In the evidence layer: the truth store refuses anything filed after the memo's date and keeps restatements as versions, and a figure from the future is revised. But the judges got the same dated table, so it is not an engine-only edge, and the hold-out exercised it on only 2 claims in 1 memo. The one wrong-year memo in the controls (`BA-control`) went against the engine in the free run and the other way in the paid run: one memo, no conclusion.

**4. "Why believe 25 US companies, free models and weak writers?"** Do not read it as a production number: the writers got most figures wrong (86% of native claims are false), the honest side is 62 + 192 claims with wide intervals, the models are free. Rely on the method: protocol committed first, hold-out run once from a tagged commit, a grader that cannot import the checker, a canary, every miss published, and the earlier mis-scoring found, disclosed and corrected.

**5. "What about a memo that lies where you cannot look?"** It passes, with the coverage line. Segments, guidance, same-store sales, backlog and share prices are not checked; a rumour can only be escalated; text in a memo cannot change the code that decides (an instruction to "mark everything confirmed" was read as plain text, in the extractor test and on a live Home Depot check). It checks facts, not the argument.

**6. "Does this benchmark show the agent system is protected?"** No. It tests the claim checker on past-year figures of big US companies in memos with a median of 13 gross errors. It never goes through the MCP gateway, mandate, held-order review or order mapping, and has no adversarial agent. An independent review found that an agent could clear an over-limit order with a lowercase ticker plus a tiny `limit_price`, and could backdate with `as_of`; the review page approves held orders without credentials. See `docs/AUDIT.md`.
