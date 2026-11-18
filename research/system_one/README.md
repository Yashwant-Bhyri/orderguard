# System One lab

This is where System One is built and tested. Start here, whether you are a model or a person.

| File | What it is |
|---|---|
| [SPRINT.md](SPRINT.md) | The current sprint: claims, pass bars, tasks |
| [POLICY.md](POLICY.md) | How work is done here: roles, autonomy, hard rules, review, budgets |
| [SCHEMA.md](SCHEMA.md) | The world format, written for independent authors (produced by T01) |
| [STATUS.md](STATUS.md) | The live board, rewritten by the runner |
| `tasks/` | One brief per task, with its pass bar |
| `work/<task>/` | Each task's code, REPORT.md and REVIEW.md |
| `runs/<task>/round<n>/` | An archive of each round: report, review, check output and logs |
| `og_s1/` | The System One package the tasks build |
| `lab/` | The runner, its config, the event log and the checkpoints |
| `data/` | Downloaded and generated data; git ignores it |

## Running the lab

The runner needs the worker key, which it reads by variable name from an env file that you name:

```bash
cd research/system_one
OG_ENV_FILE=/path/to/.env.local nohup python3 lab/run_lab.py --loop > lab/runner.out 2>&1 &
```

To see the board:

```bash
python3 lab/run_lab.py --status
```

To reopen a task after a lead review:

```bash
python3 lab/run_lab.py --reset T03
```

The runner is safe to stop and restart: the state is in `lab/state.json`. It never runs git, and it never prints keys.

## For the lead, coming back

1. Read STATUS.md and `lab/CHECKPOINTS.md`.
2. For each task that is passed, failed, needs the lead or is blocked, read `work/<id>/REPORT.md` and `REVIEW.md`.
3. Spot-check one number per task by re-running its `run.sh`.
4. Write decisions into `docs/vision/lab/DECISIONS.md`, and add a line to `docs/vision/lab/LEDGER.md`.
5. Commit.
