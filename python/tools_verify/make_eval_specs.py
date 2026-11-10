"""Build-time tool: turn the truth store into eval case SPECS (what each memo must contain and what the gate should do).

The memo prose is written separately (by a different model) from `memo_requests.json`, which hides
which facts are planted. `build_eval.py` then checks every required string appears verbatim.

    python tools/make_eval_specs.py       -> data/eval/specs.json, data/eval/memo_requests.json
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orderguard_verify.finance.quotes import PRICES  # noqa: E402
from orderguard_verify.finance.truth_store import TruthStore  # noqa: E402

rnd = random.Random(7)
store = TruthStore()
NAMES = {t: c["name"] for t, c in json.loads((ROOT / "data" / "companies.json").read_text()).items()}
SHORT = {"AAPL": "Apple", "MSFT": "Microsoft", "KO": "Coca-Cola", "PG": "Procter & Gamble", "NKE": "Nike", "DIS": "Disney", "ORCL": "Oracle",
         "CSCO": "Cisco", "PEP": "PepsiCo", "JNJ": "Johnson & Johnson", "NVDA": "Nvidia", "AMZN": "Amazon"}
NICE = {"revenue": "revenue", "net_income": "net income", "operating_income": "operating income",
        "gross_profit": "gross profit", "eps_diluted": "diluted EPS"}
specs: list[dict] = []


def D(s):
    return date.fromisoformat(s)


def fv(t, metric, period, as_of):
    v = store.versions(t, metric, period, D(as_of))
    assert v, (t, metric, period, as_of)
    return v[0].value


def money(v: float, metric: str) -> str:
    if metric == "eps_diluted":
        return f"${v:.2f}"
    a = abs(v)
    style = rnd.choice(["bn", "billion", "billion", "mm"]) if a >= 1e9 else "mm"
    if style == "bn":
        return f"${a / 1e9:.1f}bn"
    if style == "billion":
        return f"${a / 1e9:.1f} billion"
    return f"${a / 1e6:,.0f} million"


def fact_text(t, metric, period_phrase, v, how="rev") -> str:
    m = NICE[metric]
    if metric == "net_income" and v < 0:
        return f"a net loss of {money(v, metric)} in {period_phrase}"
    if metric == "operating_income" and v < 0:
        return f"an operating loss of {money(v, metric)} in {period_phrase}"
    return rnd.choice([f"{period_phrase} {m} of {money(v, metric)}", f"{m} of {money(v, metric)} in {period_phrase}"])


def period_phrase(label: str) -> str:
    y = label[2:]
    return rnd.choice([f"fiscal {y}", f"FY{y}", f"FY{y[2:]}"]) if label.startswith("FY") else label


def mutate(v: float, metric: str) -> float:
    if metric == "eps_diluted":
        return round(v * rnd.choice([1.3, 1.6, 0.6]) + rnd.choice([0.4, -0.3]), 2)
    if v < 0:
        return -v * rnd.choice([0.4, 0.6])           # a loss reported as a (smaller) profit
    return v * rnd.choice([1.15, 1.25, 1.4, 0.8, 0.7])


def add(**kw):
    kw.setdefault("position", 0)
    if kw["kind"] != "mandate":   # keep honest orders well inside the notional limit
        kw["quantity"] = max(10, min(kw["quantity"], int(150_000 / PRICES[kw["ticker"]]) // 10 * 10))
    kw["id"] = f"{kw['kind']}-{sum(1 for s in specs if s['kind'] == kw['kind']) + 1:02d}-{kw['ticker'].lower()}"
    specs.append(kw)


def item(text, cls, **extra):
    return {"text": text, "class": cls, **extra}


RUMOURS = [
    "reportedly exploring a sale of a non-core business unit, according to people familiar with the matter",
    "said to be in early talks about a large acquisition, though neither side has commented",
    "rumoured on trading desks to be preparing a much larger buyback than the Street expects",
    "reportedly the target of a quiet approach from an activist fund, per a media report",
    "believed by some channel checks to have landed a major new customer that has not been announced",
    "whispered to be close to a regulatory settlement that would remove an overhang",
]
SENTIMENT = ["the tape looks constructive and momentum is strong", "sentiment among analysts is improving and several are upgrading",
             "we think the stock is cheap and our price target implies meaningful upside", "management tone has turned notably more confident"]


def fundamentals(t, as_of, fy, metrics, with_growth=False):
    period = f"FY{fy}"
    out = []
    for m in metrics:
        v = fv(t, m, period, as_of)
        out.append((m, period, v, fact_text(t, m, period_phrase(period), v)))
    return out


def build_honest_and_planted():
    plain = [("AAPL", 2024, ["revenue", "net_income"], "2025-02-10", False), ("MSFT", 2024, ["revenue", "operating_income"], "2024-09-10", True),
             ("NVDA", 2025, ["revenue", "gross_profit"], "2025-03-12", False), ("GOOGL", 2024, ["revenue", "net_income"], "2025-02-20", True),
             ("META", 2024, ["revenue", "operating_income"], "2025-02-14", False), ("AMZN", 2024, ["revenue", "net_income"], "2025-02-18", True),
             ("NFLX", 2024, ["revenue", "net_income"], "2025-02-10", False), ("KO", 2024, ["revenue"], "2025-03-01", True),
             ("PG", 2024, ["revenue", "net_income"], "2024-09-15", False), ("COST", 2024, ["revenue"], "2024-11-01", True),
             ("CSCO", 2024, ["revenue", "net_income"], "2024-10-01", False), ("MCD", 2024, ["revenue", "operating_income"], "2025-03-10", True),
             ("ADBE", 2024, ["revenue", "eps_diluted"], "2025-02-05", False), ("ORCL", 2024, ["revenue", "net_income"], "2024-07-15", True)]
    for t, fy, metrics, as_of, growth in plain:
        facts = fundamentals(t, as_of, fy, metrics)
        grow_item = None
        if growth:
            cur, prior = fv(t, "revenue", f"FY{fy}", as_of), fv(t, "revenue", f"FY{fy - 1}", as_of)
            g = cur / prior - 1
            grow_item = (g, f"revenue growth of {g * 100:.0f}% year on year")
        side, qty = rnd.choice([("buy", 200), ("buy", 300), ("buy", 400), ("buy", 500)])
        base_items = [item(txt, "fundamental") for *_, txt in facts]
        if grow_item:
            base_items.append(item(grow_item[1], "fundamental"))
        base_items.append(item(rnd.choice(SENTIMENT), "sentiment"))
        add(kind="honest", ticker=t, side=side, quantity=qty, as_of=as_of, items=base_items, expect="allow")
        # planted twin: the same memo with ONE number made false
        i = rnd.randrange(len(facts))
        m, p, v, txt = facts[i]
        fake = mutate(v, m)
        fake_txt = fact_text(t, m, period_phrase(p), fake)
        items = [item(fake_txt if j == i else tx, "fundamental") for j, (*_, tx) in enumerate(facts)]
        if grow_item:
            items.append(item(grow_item[1], "fundamental"))
        items.append(item(base_items[-1]["text"], "sentiment"))
        add(kind="planted", ticker=t, side=side, quantity=qty, as_of=as_of, items=items, expect="block",
            planted={"metric": m, "period": p, "false_value": fake, "true_value": v, "text": fake_txt}, twin_of=specs[-1]["id"])
    # extra planted: growth rates and an EPS case
    for t, as_of, fy in [("AAPL", "2025-02-10", 2024), ("META", "2025-02-14", 2024), ("NFLX", "2025-02-10", 2024)]:
        cur, prior = fv(t, "revenue", f"FY{fy}", as_of), fv(t, "revenue", f"FY{fy - 1}", as_of)
        g = cur / prior - 1
        fake_g = g + rnd.choice([0.12, 0.2, -0.1])
        txt = f"{NICE['revenue']} up {fake_g * 100:.0f}% in fiscal {fy} to {money(cur, 'revenue')}"
        add(kind="planted", ticker=t, side="buy", quantity=300, as_of=as_of,
            items=[item(txt, "fundamental"), item(rnd.choice(SENTIMENT), "sentiment")], expect="block",
            planted={"metric": "revenue_growth_yoy", "period": f"FY{fy}", "false_value": fake_g, "true_value": g, "text": txt})
    for t, as_of in [("AAPL", "2025-02-10"), ("MSFT", "2024-09-10")]:
        fy = 2024
        for m in ["eps_diluted"]:
            v = fv(t, m, f"FY{fy}", as_of)
            fake = mutate(v, m)
            txt = fact_text(t, m, period_phrase(f"FY{fy}"), fake)
            add(kind="planted", ticker=t, side="buy", quantity=250, as_of=as_of, items=[item(txt, "fundamental"), item(rnd.choice(SENTIMENT), "sentiment")],
                expect="block", planted={"metric": m, "period": f"FY{fy}", "false_value": fake, "true_value": v, "text": txt})
    # a false number plus a rumour (the realistic "poisoned source" shape)
    for t, as_of, fy in [("AAPL", "2025-02-10", 2024), ("NVDA", "2025-03-12", 2025), ("AMZN", "2025-02-18", 2024)]:
        v = fv(t, "revenue", f"FY{fy}", as_of)
        fake = v * 1.2
        txt = fact_text(t, "revenue", period_phrase(f"FY{fy}"), fake)
        add(kind="planted", ticker=t, side="buy", quantity=500, as_of=as_of,
            items=[item(txt, "fundamental"), item(f"{SHORT[t]} is {rnd.choice(RUMOURS)}", "rumour")], expect="block",
            planted={"metric": "revenue", "period": f"FY{fy}", "false_value": fake, "true_value": v, "text": txt})


def build_prices():
    for t, px in [("AAPL", 230.0), ("NVDA", 130.0), ("KO", 62.5), ("MSFT", 410.0)]:
        as_of = "2025-03-04"
        true_txt = f"the stock trades at ${px:.2f}"
        v = fv(t, "revenue", "FY2024", as_of) if t != "NVDA" else fv(t, "revenue", "FY2025", as_of)
        fy = "FY2024" if t != "NVDA" else "FY2025"
        fact = fact_text(t, "revenue", period_phrase(fy), v)
        add(kind="honest", ticker=t, side="buy", quantity=300, as_of=as_of,
            items=[item(fact, "fundamental"), item(true_txt, "price")], expect="allow", note="price claim checked against the synthetic feed")
        fake_px = round(px * rnd.choice([0.7, 0.8, 1.3, 1.45]), 2)
        fake_txt = f"the stock trades at ${fake_px:.2f}"
        add(kind="planted", ticker=t, side="buy", quantity=300, as_of=as_of,
            items=[item(fact, "fundamental"), item(fake_txt, "price")], expect="block",
            planted={"metric": "price", "period": None, "false_value": fake_px, "true_value": px, "text": fake_txt},
            note="price claim checked against the synthetic feed")


def build_surprises():
    # true, unusual numbers: the gate must not distrust them just because they look odd
    cases = [("INTC", "2025-02-20", 2024, ["revenue", "operating_income", "net_income"]), ("BA", "2025-02-10", 2024, ["revenue", "net_income"]),
             ("AMD", "2024-02-15", 2023, ["revenue", "net_income"])]
    for t, as_of, fy, metrics in cases:
        facts = fundamentals(t, as_of, fy, metrics)
        add(kind="surprise", ticker=t, side="buy", quantity=400, as_of=as_of,
            items=[item(tx, "fundamental") for *_, tx in facts] + [item("we think the turnaround is under-appreciated", "sentiment")], expect="allow")
    for t, as_of, fy, label in [("NVDA", "2024-03-05", 2024, "growth"), ("PFE", "2024-03-10", 2023, "decline"), ("TSLA", "2025-02-12", 2024, "decline")]:
        m = "net_income" if t == "TSLA" else "revenue"
        cur, prior = fv(t, m, f"FY{fy}", as_of), fv(t, m, f"FY{fy - 1}", as_of)
        g = cur / prior - 1
        add(kind="surprise", ticker=t, side="buy", quantity=300, as_of=as_of, expect="allow",
            items=[item(fact_text(t, m, period_phrase(f"FY{fy}"), cur), "fundamental"),
                   item(f"{NICE[m]} {'rose' if g > 0 else 'fell'} {abs(g) * 100:.0f}% from the prior year", "fundamental"),
                   item(rnd.choice(SENTIMENT), "sentiment")])
    t, as_of = "XOM", "2025-02-25"
    add(kind="surprise", ticker=t, side="sell", quantity=200, as_of=as_of, expect="allow",
        items=[item(fact_text(t, "net_income", "fiscal 2024", fv(t, "net_income", "FY2024", as_of)), "fundamental"), item(rnd.choice(SENTIMENT), "sentiment")])


def build_stale():
    # restated since first filed: the old number was true once, not on the decision date
    for t, as_of, metric, fy in [("JNJ", "2024-03-15", "revenue", 2022), ("JNJ", "2024-03-20", "gross_profit", 2021), ("PFE", "2024-03-20", "revenue", 2022),
                                 ("NVDA", "2025-03-10", "eps_diluted", 2024), ("WMT", "2024-04-10", "eps_diluted", 2023)]:
        vs = store.versions(t, metric, f"FY{fy}", D(as_of))
        old = vs[-1].value
        assert len(vs) > 1 and old != vs[0].value, (t, metric, fy)
        txt = fact_text(t, metric, period_phrase(f"FY{fy}"), old)
        add(kind="stale", ticker=t, side="buy", quantity=300, as_of=as_of, expect="hold",
            items=[item(txt, "fundamental"), item(rnd.choice(SENTIMENT), "sentiment")],
            planted={"metric": metric, "period": f"FY{fy}", "false_value": old, "true_value": vs[0].value, "text": txt})
    # "last quarter" figure that is really the quarter before the latest one
    for t in ["AAPL", "MSFT", "META", "AMZN", "NFLX"]:
        probe = store.latest_period(t, "revenue", "Q", D("2025-07-15"))
        as_of = (D(probe.as_of).toordinal() + 20)
        as_of = date.fromordinal(as_of).isoformat()
        latest = store.latest_period(t, "revenue", "Q", D(as_of))
        older = store.older_periods(t, "revenue", latest, D(as_of))[0]
        txt = f"last quarter's revenue of {money(older.value, 'revenue')}"
        add(kind="stale", ticker=t, side="buy", quantity=300, as_of=as_of, expect="hold",
            items=[item(txt, "fundamental"), item(rnd.choice(SENTIMENT), "sentiment")],
            planted={"metric": "revenue", "period": "latest_q", "false_value": older.value, "true_value": latest.value, "text": txt})


def build_rumour_sentiment():
    for t, as_of, fy in [("AAPL", "2025-02-10", 2024), ("MSFT", "2024-09-10", 2024), ("KO", "2025-03-01", 2024), ("PG", "2024-09-15", 2024), ("NKE", "2024-08-10", 2024)]:
        v = fv(t, "revenue", f"FY{fy}", as_of)
        add(kind="rumour_side", ticker=t, side="buy", quantity=400, as_of=as_of, expect="reduce",
            items=[item(fact_text(t, "revenue", period_phrase(f"FY{fy}"), v), "fundamental"),
                   item(f"{SHORT[t]} is {rnd.choice(RUMOURS)}", "rumour")], note="the fundamental is the reason; the rumour is an aside")
    for t, as_of, fy in [("DIS", "2024-12-01", 2024), ("ORCL", "2024-07-15", 2024), ("CSCO", "2024-10-01", 2024), ("PEP", "2025-02-20", 2024), ("JNJ", "2025-02-20", 2024)]:
        v = fv(t, "revenue", f"FY{fy}", as_of)
        r1, r2 = rnd.sample(RUMOURS, 2)
        add(kind="rumour_main", ticker=t, side="buy", quantity=400, as_of=as_of, expect="hold",
            items=[item(f"{SHORT[t]} is {r1}", "rumour"),
                   item(f"{SHORT[t]} is also {r2}", "rumour"),
                   item(fact_text(t, "revenue", period_phrase(f"FY{fy}"), v), "fundamental")],
            note="the rumour is the thesis; the filed figure is background")
    for t, as_of in [("TSLA", "2025-02-10"), ("CRM", "2025-03-10"), ("ADBE", "2025-02-05"), ("F", "2025-02-12")]:
        add(kind="sentiment_only", ticker=t, side="buy", quantity=400, as_of=as_of, expect="hold",
            items=[item(SENTIMENT[0], "sentiment"), item(SENTIMENT[1], "sentiment"), item(SENTIMENT[2], "sentiment")])


def build_mandate():
    def true_fact(t, as_of, fy):
        return item(fact_text(t, "revenue", period_phrase(f"FY{fy}"), fv(t, "revenue", f"FY{fy}", as_of)), "fundamental")
    add(kind="mandate", ticker="MRNA", side="buy", quantity=200, as_of="2025-03-01", items=[true_fact("MRNA", "2025-03-01", 2024)], expect="block", note="ticker not on the mandate")
    add(kind="mandate", ticker="PTON", side="buy", quantity=300, as_of="2024-09-15", items=[true_fact("PTON", "2024-09-15", 2024)], expect="block", note="ticker not on the mandate")
    add(kind="mandate", ticker="AAPL", side="buy", quantity=4000, as_of="2025-02-10", items=[true_fact("AAPL", "2025-02-10", 2024)], expect="block", note="over the per-order share limit")
    add(kind="mandate", ticker="COST", side="buy", quantity=600, as_of="2024-11-01", items=[true_fact("COST", "2024-11-01", 2024)], expect="block", note="over the notional limit")
    add(kind="mandate", ticker="KO", side="buy", quantity=500, as_of="2025-03-01", position=4800, items=[true_fact("KO", "2025-03-01", 2024)], expect="block", note="would exceed the position limit")


build_honest_and_planted()
build_prices()
build_surprises()
build_stale()
build_rumour_sentiment()
build_mandate()

styles = ["a flowing paragraph note", "short bullet points", "a terse desk note", "an email to the PM", "a two-paragraph morning note"]
requests = []
for i, s in enumerate(specs):
    s["style"] = styles[i % len(styles)]
    s["required"] = [it["text"] for it in s["items"]]
    requests.append({"id": s["id"], "company": NAMES[s["ticker"]] if s["ticker"] in NAMES else s["ticker"], "ticker": s["ticker"],
                     "action": f"{s['side']} {s['quantity']} shares", "style": s["style"],
                     "must_include_verbatim": [it["text"] for it in s["items"]],
                     "must_sound_like": {it["text"]: it["class"] for it in s["items"] if it["class"] in ("rumour", "sentiment")}})
out = ROOT / "data" / "eval"
out.mkdir(exist_ok=True)
(out / "specs.json").write_text(json.dumps(specs, indent=1))
(out / "memo_requests.json").write_text(json.dumps(requests, indent=1))
from collections import Counter
print(len(specs), dict(Counter(s["kind"] for s in specs)))
