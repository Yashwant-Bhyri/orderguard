# Ledger

Append-only. Each line is one unit of work: when it happened, who did it, which question it serves, where the output is, and what came of it.

| Date | Who | Question | Work | Output | Outcome |
|---|---|---|---|---|---|
| 2026-11-19 | lab lead + 6 research agents | Q0 | Deep research on System One's state of the art | [reports/](../reports/), [research_notes/](../research_notes/) | Produced D1–D5 |
| 2026-11-19 | lab lead | Q0 | Exploration: endorsement, why-graph, purpose attribution, six levels | [SYSTEM-ONE.md](../SYSTEM-ONE.md) | Produced D1–D4 |
| 2026-11-19 | lab lead | all | Lab paradigm against drift | this folder | Produced D6 and D7 |
| 2026-11-19 | 5 Haiku scouts | Q1–Q5 | Wide scan: architectures, debuggability, datasets, one-GPU training, frontier pulse | [scan/2026-11-19/](../scan/2026-11-19/) | See [READOUT.md](READOUT.md) |
| 2026-11-19 | Codex (Luna), fork of the lab chat | Q6 | Read-only probe of the GPU machine (about 6.3M tokens, because the fork carried the whole chat) | [READOUT.md §5](READOUT.md) | Controller is robotics-only; a separate campaign, environment and staging need the founder's approval |
| 2026-11-19 | lab lead | Q1–Q5 | Readout: System One taken apart, four ideas, experiment order | [READOUT.md](READOUT.md) | Opened Q1–Q7, proposed E0–E5 |
| 2026-11-19 | lab lead | Q1–Q6 | Sprint S1 designed: claims C1–C6 with pass bars, 11 briefs, working policy, a disk-backed runner (DeepSeek works, Codex Luna reviews, Sol escalations) | [research/system_one/](../../../research/system_one/README.md) | Produced D8 and D9 |
- 2026-11-19T04:58:49Z lead: T03 reopened for round 4. All pass-bar items met; two real gaps remain (support checks skip claims without a number; an absent quote is not flagged). Codex quota out until 2026-11-21 20:12Z: DeepSeek max reviews, Haiku (lead-run) finished T16 and T02d fix rounds; a subagent hook blocked T02d's REPORT.md, left for Codex.
- 2026-11-19T07:30:36Z lead answered T05 escalation: authority met only via the generic decision-model question vs the registered floor; ref-selected NLI and extended list are sensitivities; freeze all readers for unseen-world scoring. Disk: removed a duplicate SEC zip from /tmp and pruned unused uv cache (8.0 GB free).
