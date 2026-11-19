# The System One lab: how we work without drifting

Started 2026-11-19. These are the rules for every session, agent and GPU job that works on System One. They are short on purpose. Read this file, [DECISIONS.md](DECISIONS.md) and [QUESTIONS.md](QUESTIONS.md) before starting any work. The end-to-end plan is [BLUEPRINT.md](BLUEPRINT.md).

## The one question

> **Can a small model tell, quickly and with honest confidence, whether an owner would endorse what their trading agent is doing, and which part of the owner's purpose it serves?**

Work that does not help answer this question, or one of its branches in QUESTIONS.md, is out of scope. That includes good ideas. A good idea goes into QUESTIONS.md as a new branch, and only then gets worked on.

## Why we drift

Long autonomous projects drift for the same reasons a trading agent does. This lab was designed against those failures.

| How an agent drifts | How a project drifts | The rule here |
|---|---|---|
| A summary keeps the position and drops the exit condition | A decision survives, but the reason it was made is forgotten | Every decision records **what would reverse it** |
| It optimises whatever metric it can see | Work fills pages because volume is visible | We measure answered questions, not files written |
| It trusts context it inherited | A new session trusts a summary of a summary | The truth is in these files, which are dated and linked, and not in anyone's memory |
| It justifies a choice after making it | Research is quoted to support a choice already made | Research is input to exploration, never proof. Each claim is marked as evidence or claim |
| Many agents follow one source | All workers follow the same brief and make the same mistake | Briefs ask for options and for "beyond what we asked", not for confirmation |

This is the why-graph from [SYSTEM-ONE.md](../SYSTEM-ONE.md), applied to our own work. Every artefact traces to a question. Every decision traces to evidence. Drift is work that traces to nothing.

## Who decides

- **The founder** sets direction and can overrule anything. They also approve anything that reaches outside: GPU campaigns, pushes, publishing and spend.
- **The lab lead** (the Claude session that owns this folder) turns evidence into decisions, keeps these files current and writes every brief. There is one lab lead at a time.
- **Workers** (cheap scouts, Codex on the GPU, subagents) return evidence and options. They never make decisions and never edit DECISIONS.md. They do not run git.

## The loop

1. **Scout.** Go wide: papers, code, vendors, X/Twitter, datasets. Collect options with dates and sources, and mark each one as evidence or claim.
2. **Ideate.** The lab lead reads the options against our own problem. It keeps what fits, discards what doesn't and says why. It adds what nobody has published.
3. **Hypothesise.** Each idea worth testing becomes a branch in QUESTIONS.md with a kill criterion written *before* the test.
4. **Test.** Run the smallest experiment that could kill it: a notebook, a simulator run or one GPU job. Each one gets a line in [LEDGER.md](LEDGER.md).
5. **Decide.** The result becomes a decision, or a question gets closed. A decision is never quietly edited. A new decision supersedes the old one by number.

## Checkpoints

At the start of every session, and after every batch of worker results, the lab lead does the following:

- re-reads the one question, the open decisions and the open questions;
- checks every new piece of work against a question number;
- writes the ledger line before reporting to the founder.

If two weeks pass without a question closing, that is drift. Stop and re-scope.

## Compute

We have one A6000 GPU at a time on a university machine, reached through the founder's Codex lab chat. That chat already runs a job controller for another campaign. Jobs there are network-isolated and serialised, and they need a protected approval file before they will run. So:

- System One jobs run as their own campaign. They never touch the other campaign's files.
- Weights and datasets are staged before a job, because jobs cannot download.
- The founder approves each campaign and its GPU-hour cap. Codex executes. The lab lead plans and reads the results.
