# Four independent blueprints, compared

On 2026-11-19, four models each wrote a System One blueprint, alone, from the same light brief (`SYSTEM-ONE.md`, `SCHEMA.md`, the founder's questions, the hardware and latency facts). None saw the lead's blueprint, ChatGPT's answers or each other's work.

| Writer | File | Length |
|---|---|---|
| Codex Luna (max) | [luna.md](luna.md) | 115 lines |
| DeepSeek V4.1 Flash (max) | [deepseek.md](deepseek.md) | 1,851 lines |
| GLM 5.3 | [glm.md](glm.md) | 776 lines |
| Claude Haiku (high) | [haiku.md](haiku.md) | 348 lines |

## Where all four agree

- **System One is a decision system, not a model.** Code decides everything that can be decided exactly. Learned parts handle only the semantic residue and owner preference.
- **The workhorse is a calibrated tabular model** (boosted trees or logistic) over code-computed graph features, plus a **small frozen encoder with heads** for text.
- **LLMs belong offline:** as teachers, data generators and escalation reviewers. Never as the per-order judge.
- **No layer surgery on large models.** Change the input contract and the output instead.
- **No RL in version 1.**
- **Owner adaptation is a regularised per-owner offset** over a population prior, not a per-owner fine-tune.
- **Synthetic cause labels must never stand in for real owner preference.**

## Ideas only one writer had, and what the lab did with them

| Idea | Writer | What the lab did |
|---|---|---|
| **A factorised endorsement model.** A noisy-AND over evidence, reasoning, objective, owner fit and an explicit unexplained residual. One model judges and attributes; each factor can only lower endorsement and is calibrated separately | GLM | Added to T04 as a combiner candidate against the EBM |
| **A messy variant of every synthetic family,** to break the circularity between generator rules and code rules | Haiku | T16 now requires 30% of episodes with no structured facts |
| **Will real inputs carry typed `facts`?** If not, fact extraction is a learned component with its own error rate | Haiku and GLM (both name it the biggest open question) | New task T24: quote-anchored fact extraction, scored with its downstream effect on the code checks |
| **Three clocks:** micro (order, code only), meso (thesis), macro (trajectory, swarm, book) | DeepSeek | Already the blueprint's tempo table; kept |
| **Distil verified labels, not teacher behaviour** | DeepSeek | Already the rule in T19 and T23 |
| **Effort split for version 1:** 35% harness and representation, 25% data and labels, 20% evaluation, 15% models, 5% serving | DeepSeek | Recorded as a useful check on where the lab spends effort |
| **A small graph neural network** as the one custom architecture worth funding | GLM | Not adopted yet. The other three say code-computed graph features first; a GNN only if topology adds held-out value |
| **RL only for the interruption policy,** never for the judge | GLM | Consistent with "no RL now"; recorded for later |

## Where they disagree with the founder's current direction, and how the lab settles it

All four argue for **small models**. The founder's priority, after they wrote, is **quality first**: find the ceiling with the strongest models before shrinking anything. Two things weaken the writers' case:
- their brief gave them the latency budgets as hard limits, and the founder has since made latency secondary;
- none of them knew about the 2026 wave of 27–31B decision models (Clef, Karpo).

But their other arguments do not depend on latency:
- calibration degrades under shift;
- a model that reads agent text is an attack surface;
- most failure causes are arithmetic over typed records.

**The lab doesn't pick a side by argument.** The stack race in [COMBOS.md](../COMBOS.md) runs both:
- S0 (the exact core) and S1 (the small encoder) are the four writers' design;
- S2 and S4 (the 27–31B decision models) are the founder's and ChatGPT's.

They are scored on the same unseen worlds, with the same primary metric. If the small stack matches the big one on quality, the writers were right and serving is cheap. If the big one wins clearly on unseen semantic failures, it earns its place.
