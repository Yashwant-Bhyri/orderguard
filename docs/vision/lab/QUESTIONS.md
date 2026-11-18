# Questions

The tree under the one question in [LAB.md](LAB.md). Every piece of work cites one of these numbers. A question closes with a decision number, or with "dropped" and the reason.

**Q0.** Can a small model tell, quickly and with honest confidence, whether an owner would endorse what their agent is doing, and which part of the purpose it serves?

| # | Question | Status | How it gets answered | Kill criterion (written before the test) |
|---|---|---|---|---|
| Q1 | Can the scorer itself be the explanation? An additive, monotone glass box whose terms are the purpose attribution | open, first to test | E0: glass box against boosted trees against a tabular foundation model, on simulator labels | Dropped if the glass box is more than 3 AUROC points behind the best model under shift, or cannot reach ECE under 0.05 in distribution after recalibration |
| Q2 | Can text be given a bounded blast radius, so that no text can raise approval and can lower it only by a known amount? | open | E4: design proof plus an injection test set | Dropped if bounding the text features costs more than 5 AUROC points on the cases text was needed for |
| Q3 | Where do labels come from at scale? | open | E1 (public purpose corpus pilot) and E5 (independently written generator) | See the experiments |
| Q3a | Do public funds give a real "stated purpose versus actual book" signal? (N-1A objectives, N-PORT holdings, the 80% names rule, Form ADV against 13F) | open | E1: pilot on 200 funds | Dropped if automatic purpose-fit labels agree with a hand check less than 80% of the time |
| Q3b | Does the simulator teach judgement, or only teach the generator? In JUDGEMENT.md the 0.97 in distribution was the features matching the generator | open | E5: a generator family written independently of the features, kept fully held out | If the model trained on our generator scores under 0.70 AUROC on the independent one, the label factory needs redesign before anything else |
| Q4 | Can calibration survive shift? (Targets in D5) | open | E2 and E3 on GPU, plus conformal risk control per action class | ECE above 0.15 under shift after the best method means System One holds every shifted case instead of scoring it |
| Q5 | Which checkpoint reads the text: one with interpretability tooling (Gemma 3 with Gemma Scope 2) or the stronger raw model (Qwen3)? | open | E2: shift stress test with no training, plus measured throughput on the A6000 | Pick on calibration under shift first, then speed. Tooling breaks a tie only |
| Q6 | Can the university GPU run our campaign alongside the robotics one? | probing | Codex read-only probe | Blocked until the founder approves a campaign file |
| Q7 | What is System One's public name? | open | Trademark search before the vision page | n/a |
