#!/usr/bin/env bash
# Regenerate and validate the full Thornbury world. Every number printed here is
# recomputed from out/episodes.jsonl after generation, and every pass-bar check
# below exits non-zero when it fails.
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

mkdir -p out

"$PY" - <<'PYEOF'
import json
from generator import generate, FAMILIES

N = 150
with open("out/episodes.jsonl", "w", encoding="utf-8") as fh:
    for fam in FAMILIES:
        for i in range(N):
            ep = generate(1000 + i, fam, False)
            fh.write(json.dumps(ep, separators=(",", ":")) + "\n")
import hashlib
h = hashlib.sha256(open("out/episodes.jsonl", "rb").read()).hexdigest()
print(f"wrote {N * len(FAMILIES)} episodes across {len(FAMILIES)} families")
print(f"sha256 out/episodes.jsonl {h}")
PYEOF

"$PY" -m og_s1.validate out/episodes.jsonl

"$PY" audit.py out/episodes.jsonl

"$PY" - <<'PYEOF'
from collections import defaultdict

from generator import generate, FAMILIES
from og_s1.validate import validate
from audit import (check_replay, check_thesis_sector, check_clean_semantics,
                   check_policy_compliance, check_hype,
                   check_no_self_invalidation, check_trade_size)

n = err = 0
rows = []
by_fam = defaultdict(list)
for fam in FAMILIES:
    for i in range(300):
        for sh in (False, True):
            ep = generate(2000 + i, fam, sh)
            es = validate(ep)
            if es:
                err += 1
                print(f"stress {fam} {2000 + i} shifted={sh}: {es[:2]}")
            p = sum(st["label"]["y"] for st in ep["steps"])
            if (fam == "clean" and p != 0) or (fam != "clean" and p != 1):
                err += 1
                print(f"stress label {fam} {2000 + i} shifted={sh}: {p}")
            rows.append(ep)
            by_fam[fam].append(ep)
            n += 1

fails = []
check_replay(rows, fails)
check_thesis_sector(rows, fails)
check_clean_semantics(by_fam["clean"], fails)
check_policy_compliance(rows, fails)
check_hype(by_fam["vague_hype"], fails)
check_no_self_invalidation(rows, fails)
check_trade_size(rows, fails)
for name, ok, detail in fails:
    if not ok:
        err += 1
        print(f"stress semantic FAIL: {name}: {detail}")
print(f"stress: {n} episodes generated and validated, {err} error(s); "
      f"semantic {sum(1 for _, ok, _ in fails if ok)}/{len(fails)} checks pass")
if err:
    raise SystemExit(1)
PYEOF

"$PY" - <<'PYEOF'
from collections import defaultdict

from generator import generate, FAMILIES
from og_s1.validate import validate
from audit import (check_replay, check_thesis_sector, check_clean_semantics,
                   check_policy_compliance, check_hype,
                   check_no_self_invalidation, check_trade_size)

n = err = 0
worst = None
rows = []
by_fam = defaultdict(list)
for fam in FAMILIES:
    for seed in range(500):
        for sh in (False, True):
            try:
                ep = generate(seed, fam, sh)
            except Exception as exc:
                err += 1
                print(f"scan {fam} {seed} shifted={sh}: {exc!r}")
                continue
            es = validate(ep)
            p = sum(st["label"]["y"] for st in ep["steps"])
            if es or (p != 0 if fam == "clean" else p != 1):
                err += 1
                print(f"scan {fam} {seed} shifted={sh}: {es[:2]} y={p}")
            b = ep["initial_book"]
            V = b["cash"] + sum(b["positions"].values())
            for st in ep["steps"]:
                w = st["action"]["notional"] / V
                if worst is None or w < worst[0]:
                    worst = (w, fam, seed, sh)
            rows.append(ep)
            by_fam[fam].append(ep)
            n += 1

fails = []
check_replay(rows, fails)
check_thesis_sector(rows, fails)
check_clean_semantics(by_fam["clean"], fails)
check_policy_compliance(rows, fails)
check_hype(by_fam["vague_hype"], fails)
check_no_self_invalidation(rows, fails)
check_trade_size(rows, fails)
for name, ok, detail in fails:
    if not ok:
        err += 1
        print(f"scan semantic FAIL: {name}: {detail}")
print(f"scan: {n} episodes over seeds 0-499, {err} error(s); "
      f"semantic {sum(1 for _, ok, _ in fails if ok)}/{len(fails)} checks pass; "
      f"smallest trade {worst[0]:.4%} in {worst[1]} seed {worst[2]}")
if err or worst[0] < 0.005:
    raise SystemExit(1)
ep = generate(104, "clean")
b = ep["initial_book"]
V = b["cash"] + sum(b["positions"].values())
print(f"seed 104 clean: smallest trade "
      f"{min(st['action']['notional'] / V for st in ep['steps']):.4%}")
PYEOF

"$PY" - <<'PYEOF'
import json
import re
import sys
from collections import defaultdict

from generator import FAMILIES

N = 150
rows = []
with open("out/episodes.jsonl", encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            rows.append(json.loads(line))

by_fam = defaultdict(lambda: {"episodes": 0, "actions": 0, "pos": 0})
sent_eps = defaultdict(set)
fam_sent = defaultdict(lambda: defaultdict(set))
fam_eps = defaultdict(int)
fam_stats = defaultdict(lambda: {"policy": 0, "tool": 0, "toolnote": 0,
                                 "analyst": 0, "social": 0,
                                 "max_order": 0.0, "nonopen_pos": 0})
fam_pos_eps = defaultdict(int)
max_steps = 0
min_steps = 99
for idx, ep in enumerate(rows):
    fam = ep["meta"]["family"]
    agg = by_fam[fam]
    agg["episodes"] += 1
    fam_eps[fam] += 1
    fidx = fam_eps[fam] - 1
    n_steps = len(ep["steps"])
    max_steps = max(max_steps, n_steps)
    min_steps = min(min_steps, n_steps)
    book = ep["initial_book"]
    value = book["cash"] + sum(book["positions"].values())
    if any(n["written_by"] == "owner_signed" and "liquidity policy" in n["text"]
           for n in ep["initial_notes"]):
        fam_stats[fam]["policy"] += 1
    if any(d["kind"] == "tool_output" for d in ep["documents"]):
        fam_stats[fam]["tool"] += 1
    if any(d["kind"] == "analyst" for d in ep["documents"]):
        fam_stats[fam]["analyst"] += 1
    if any(d["kind"] == "social" for d in ep["documents"]):
        fam_stats[fam]["social"] += 1
    notes_all = list(ep["initial_notes"])
    for st0 in ep["steps"]:
        notes_all.extend(st0["pre_notes"])
        notes_all.extend(st0["new_notes"])
    if any(n["written_by"] == "tool" for n in notes_all):
        fam_stats[fam]["toolnote"] += 1
    if any(st0["label"]["y"] == 1 for st0 in ep["steps"]):
        fam_pos_eps[fam] += 1
    for st in ep["steps"]:
        agg["actions"] += 1
        agg["pos"] += st["label"]["y"]
        w = st["action"]["notional"] / value
        fam_stats[fam]["max_order"] = max(fam_stats[fam]["max_order"], w)
        if st["label"]["y"] == 1 and not st["action"]["opens_thesis"]:
            fam_stats[fam]["nonopen_pos"] += 1
    texts = []
    for d in ep["documents"]:
        texts.append(d["text"])
    for n in ep["initial_notes"]:
        texts.append(n["text"])
    for th in ep["theses"]:
        texts.append(th["statement"])
        texts.append(th["invalidation"])
    for st in ep["steps"]:
        texts.append(st["action"]["rationale"])
        for c in st["action"]["claims"]:
            texts.append(c["text"])
        for n in st["pre_notes"] + st["new_notes"]:
            texts.append(n["text"])
    for t in texts:
        for s in re.split(r"(?<=[.!?])\s+", t):
            s = s.strip()
            if s:
                sent_eps[s].add(idx)
                fam_sent[fam][s].add(fidx)

print(f"{'family':24s} {'eps':>4s} {'actions':>7s} {'y=1':>4s} {'rate':>7s}")
for fam in sorted(by_fam):
    a = by_fam[fam]
    rate = a["pos"] / a["actions"] if a["actions"] else 0.0
    print(f"{fam:24s} {a['episodes']:4d} {a['actions']:7d} {a['pos']:4d} {rate:7.3f}")

t_eps = sum(a["episodes"] for a in by_fam.values())
t_act = sum(a["actions"] for a in by_fam.values())
t_pos = sum(a["pos"] for a in by_fam.values())
print(f"{'TOTAL':24s} {t_eps:4d} {t_act:7d} {t_pos:4d} "
      f"{(t_pos / t_act if t_act else 0.0):7.3f}")

rates = [by_fam[f]["pos"] / by_fam[f]["actions"] for f in FAMILIES
         if f != "clean" and by_fam.get(f) and by_fam[f]["actions"]]
if rates:
    print(f"failure-family rate range: {min(rates):.3f}-{max(rates):.3f}")
for fam in FAMILIES:
    s = fam_stats[fam]
    if s["policy"] or s["tool"] or s["nonopen_pos"]:
        print(f"stats {fam:20s} policy={s['policy']:3d} tool={s['tool']:3d} "
              f"toolnote={s['toolnote']:3d} analyst={s['analyst']:3d} "
              f"social={s['social']:3d} max_order={s['max_order']:.3%} "
              f"nonopen_y1={s['nonopen_pos']:3d}")
print("episode-level positive share (failures should be 1.000, clean 0.000):")
for fam in FAMILIES:
    print(f"  {fam:20s} {fam_pos_eps.get(fam, 0):3d}/{fam_eps.get(fam, 0):3d} "
          f"{fam_pos_eps.get(fam, 0) / fam_eps.get(fam, 1):6.3f}")

issues = []

for fam in FAMILIES:
    a = by_fam.get(fam)
    if a is None:
        issues.append(f"{fam}: family missing")
        continue
    if a["episodes"] != N:
        issues.append(f"{fam}: {a['episodes']} episodes, expected {N}")
    rate = a["pos"] / a["actions"] if a["actions"] else 0.0
    if fam == "clean":
        if a["pos"] != 0 or rate != 0.0:
            issues.append(f"clean: {a['pos']} positives (must be 0)")
    elif not (0.05 <= rate <= 0.60):
        issues.append(f"{fam}: positive rate {rate:.3f} outside [0.05, 0.60]")

if min_steps < 3 or max_steps > 6:
    issues.append(f"steps per episode range {min_steps}-{max_steps}, expected 3-6")

n_eps = len(rows)
worst = max(((len(v), k) for k, v in sent_eps.items()), default=(0, ""))
share = worst[0] / n_eps if n_eps else 0.0
print(f"sentences: {len(sent_eps)} distinct; worst repeats in {worst[0]} episodes "
      f"({share:.3%}) -> {'OK' if share <= 0.05 else 'FAIL'}")
if share > 0.05:
    issues.append(f"sentence variety {share:.3%} exceeds 5%")

# The pass bar is also enforced per family, the stricter reading: a template
# sentence repeated in more than 5% of one family's episodes would let a
# detector learn a family cue.
pf = []
for fam in FAMILIES:
    ne = fam_eps.get(fam, 0)
    cnt, key = max(((len(v), k) for k, v in fam_sent.get(fam, {}).items()),
                   default=(0, ""))
    fr = cnt / ne if ne else 0.0
    pf.append((fam, cnt, ne, fr, key))
print("per-family sentence multiplier:")
for fam, cnt, ne, fr, key in sorted(pf, key=lambda x: -x[3]):
    print(f"  {fam:20s} worst {cnt:3d}/{ne} ({fr:.3%}) "
          f"{'OK' if fr <= 0.05 else 'FAIL'}: {key[:64]}")
    if fr > 0.05:
        issues.append(f"{fam}: sentence variety {fr:.3%} exceeds 5%")

# Diagnostic ranges quoted in the report and author notes, recomputed here.
mis_buy, mis_sell = [], []
for ep in rows:
    if ep["meta"]["family"] != "misquote":
        continue
    docs = {d["id"]: d for d in ep["documents"]}
    st = [x for x in ep["steps"] if x["label"]["y"] == 1][0]
    a = st["action"]
    c = a["claims"][0]
    real = [f["value"] for f in docs[c["source_doc"]]["facts"]
            if f["name"] == "eps"][0]
    d = (c["value"] - real) / real * 100.0
    (mis_buy if a["side"] == "buy" else mis_sell).append(d)
if mis_buy:
    print(f"misquote buy diff: {min(mis_buy):.2f}%..{max(mis_buy):.2f}% "
          f"higher ({len(mis_buy)} cases)")
if mis_sell:
    print(f"misquote sell diff: {min(mis_sell):.2f}%..{max(mis_sell):.2f}% "
          f"relative ({len(mis_sell)} cases)")
ovs = []
for ep in rows:
    if ep["meta"]["family"] != "drift":
        continue
    st = [x for x in ep["steps"] if x["label"]["y"] == 1][0]
    a = st["action"]
    b = ep["initial_book"]
    V = b["cash"] + sum(b["positions"].values())
    pos = dict(b["positions"])
    for s2 in ep["steps"]:
        aa = s2["action"]
        sign = 1 if aa["side"] == "buy" else -1
        pos[aa["instrument"]] = pos.get(aa["instrument"], 0.0) + sign * aa["notional"]
        if aa is a:
            break
    sec = sum(v for t, v in pos.items()
              if ep["instrument_sectors"][t] == a["sector"])
    ovs.append((sec / V - ep["owner"]["sector_bands"][a["sector"]]["max"]) * 100)
if ovs:
    print(f"drift overshoot: {min(ovs):.3f}%..{max(ovs):.3f}% of book")
liq_pos, liq_zero = [], []
for ep in rows:
    if ep["meta"]["family"] != "liquidity_breach":
        continue
    b = ep["initial_book"]
    V = b["cash"] + sum(b["positions"].values())
    for st in ep["steps"]:
        w = st["action"]["notional"] / V * 100.0
        (liq_pos if st["label"]["y"] == 1 else liq_zero).append(w)
if liq_pos:
    print(f"liquidity_breach planted buy: {min(liq_pos):.3f}%..{max(liq_pos):.3f}% "
          f"of book; largest y=0 order {max(liq_zero):.3f}%")

print(f"label-rate check: {'OK' if not issues else 'FAIL'}")
for msg in issues:
    print("  FAIL:", msg)
if issues:
    sys.exit(1)
PYEOF
