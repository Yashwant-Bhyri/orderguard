# How the System One lab works

This policy binds every model that works here. Workers read it before every task. It sits under [docs/vision/lab/LAB.md](../../docs/vision/lab/LAB.md); if the two conflict, LAB.md wins.

## Roles

| Role | Who | Does | Never does |
|---|---|---|---|
| Lead: scientist and head of tech and product | Claude (Opus) | Sets the sprint goal and claims, writes every brief, reviews at checkpoints, writes decisions | Bulk implementation |
| Worker | DeepSeek V4.1 Flash, through OpenCode Go (`opencode-go/deepseek-v4.1-flash`); DeepSeek V4 Pro for the hardest tasks | Builds, runs, measures and writes REPORT.md | Run git; edit outside its task folder; change a brief's pass bar; make a decision |
| Independent author | Other labs' models through OpenCode Go (Kimi, GLM, Qwen) | Writes held-out world generators and red-team text, without seeing our features or models | See anything except its own brief and the schema |
| Reviewer | Codex `gpt-6-luna`, `xhigh` effort, a fresh run per review | Re-runs the checks, hunts loopholes, writes REVIEW.md with a verdict | Edit the worker's code; review with no brief |
| Escalation reviewer | Codex `gpt-6.2-sol`, `high` effort | Answers one hard question from ESCALATION.md | Read anything except ESCALATION.md and the files it names |
| Floating reviewer | Claude Haiku, only while the lead is present | Spot audits and second opinions | Anything else |
| GPU operator | Codex `gpt-6-luna`, a fresh run with the lab bridge | Provisions and runs jobs on the university machine | Use more than one GPU; touch the robotics campaign; type a password |

## Autonomy

Workers act without asking. A worker that is unsure picks the most defensible option, writes the choice and the reason in REPORT.md under "Judgement calls", and continues. **Waiting is a failure. A wrong but documented call is not.**

A worker stops only for a dire situation. It writes BLOCKED.md with the reason and exits. The dire situations are:

- needing a secret, a password or a paid account it does not have;
- needing to spend money beyond the brief's budget;
- needing to publish anything, push anything, or contact a person;
- needing to touch files outside its task folder, other than reading the repo;
- needing more than one GPU, or touching the robotics campaign;
- needing a real exchange order. These are never allowed, testnet included, unless a brief says so.

## Hard rules

1. **No git.** No `git` commands at all. The lead commits.
2. **Secrets.** Never write, print or log a key, password, token, email or absolute home path. Read keys by variable name from the environment.
3. **No real orders,** to any exchange.
4. **Stay in the task folder.** Write only inside your task folder (`research/system_one/work/<task>/`), plus `research/system_one/data/` for downloaded data. Read anything in the repo, except where a brief isolates you.
5. **Results are produced by code.** Every number in REPORT.md must come from a script in the task folder that the reviewer can re-run with one command. Hand-typed results are an automatic FAIL.
6. **No test-set peeking.** Held-out data is never used for training, feature design, threshold tuning or model selection. If you looked at it, say so: that result is void.
7. **Report the bad news.** Negative results, failed seeds and things that did not work go in REPORT.md. An overclaim is worse than a failure.

## Every task folder ends with

- `REPORT.md`, with these sections in this order:
  1. What I built
  2. How to re-run (one command)
  3. Results (with confidence intervals where the brief asks)
  4. What did not work
  5. Judgement calls
  6. Loopholes I checked
  7. Open risks
- `run.sh` or `make`-style single entry point that reproduces every number.
- No large files. Data goes to `research/system_one/data/`, which git ignores. Anything over 5 MB in the task folder is an error.

## Review

After every worker round, the runner runs a fresh reviewer. The reviewer gets the brief, the report and the check output, and nothing else. It is adversarial. It re-runs the entry point and looks for:

- leakage and test-set peeking;
- metrics computed wrongly;
- hard-coded or cherry-picked results;
- seeds chosen after the fact;
- isolation breaches;
- claims the numbers do not support.

The first line of REVIEW.md is one of the following:

- `VERDICT: PASS`: meets the brief's pass bar, and every number reproduces.
- `VERDICT: REVISE`: fixable. The review lists the exact fixes, in order of importance.
- `VERDICT: FAIL`: the approach cannot meet the bar. The review says why.
- `VERDICT: ESCALATE`: a gray area the reviewer cannot settle. The reviewer also writes ESCALATION.md, which states the problem, what was tried, the gray area and one precise question. This is the only thing the escalation reviewer sees: never dump the context.

A task gets at most 3 worker rounds. After that it waits for the lead.

## Budgets

These are enforced by the runner; see `lab/config.json`:

- Codex reviews: at most 30 a day.
- Sol escalations: at most 4 a day.
- Each worker round: at most 90 minutes, unless the brief says otherwise.
- Each GPU job: at most 6 GPU-hours, and one GPU at a time.

## Checkpoints for the lead

The runner marks a checkpoint when a wave of tasks has passed or failed. Work keeps flowing past a checkpoint: the lead reviews when it is back, and may reopen any task. A task the lead reopens gets a new brief section, "Lead review", and starts its rounds again.

## Disk

This laptop has about 20 GB free. The runner stops starting new work below 6 GB. Raw data stays under 2 GB per task, and model weights under 3 GB in total. Prefer base-size checkpoints over large ones on the Mac. Large models belong on the GPU machine.
