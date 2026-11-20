# G1. Self-hosted decision models as readers (lead experiment, 2026-11-20)

**Question.** Do the self-hosted decision models (Karpo 31B, Clef 27B, and their 9B siblings) read agent text as well as the hosted decision model did in T05? On the same actions, does size buy anything?

**Design.**
- `export.py` rebuilds T05's exact evaluation set with T05's own sampler: 1,440 actions, half of them shifted. It writes the state and the three questions, with **no labels**, to `items.jsonl`.
- `gpu_readers.py` runs each model through its own typed-decision API on the GPU host, in bf16, with nothing decoded:
  - the 9B models on one card;
  - the 31B and 27B models split across two cards.
- `score.py` scores on the Mac with T05's own targets, AUROC and episode bootstrap. On the shifted split, the dry run reproduces T05's published hosted and keyword numbers exactly.
- `host_run.sh` does everything end to end. It runs a smoke test on 8 actions before each full run.

**Not tuned.** The models are run zero-shot, with no threshold or prompt chosen on these items.
