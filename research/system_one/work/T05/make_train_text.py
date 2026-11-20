"""Generate the training text for reader 3 (sentence embeddings + logistic regression).

The wording here is ours.  We do not read or copy text from ``data/ref/``; the
script only writes JSONL rows to the task folder.  Round 2 removed the phrases
that overlapped the reference/generator templates (for example "the owner
widened ... band"); ``check_train_leakage.py`` audits the result against every
reference text with 6-grams.

Every row carries a ``group`` label.  ``train_embed.py`` holds out whole
template groups, so its headline holdout number is a template-group holdout,
not a random row split.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _tagged_product(prefixes, middles, tails):
    """Cartesian product; group by the last component (a sentence template)."""
    out: list[tuple[str, int]] = []
    for prefix in prefixes:
        for middle in middles:
            for tail in tails:
                out.append((" ".join([prefix, middle, tail]), tails.index(tail)))
    return out


HYPE_POSITIVE_TAGGED = _tagged_product(
    [
        "The desk is convinced",
        "Our analyst wrote",
        "The pitch deck says",
        "We are being told",
        "The chat thread claims",
        "The morning note argues",
        "The sales desk insists",
    ],
    [
        "this is a spectacular",
        "this is a staggering",
        "this is a dizzying",
        "this is a dreamlike",
        "this is a runaway",
        "this is a turbocharged",
        "this is a storybook",
    ],
    [
        "winner with nothing that could possibly go wrong.",
        "jackpot and the downside is essentially zero.",
        "rocket ship that will leave the sceptics speechless.",
        "fortune with an upside you will not believe.",
        "parabola that the market has completely missed.",
        "moneymaker that is destined for the stratosphere.",
        "touchdown with the risk profile of a savings account.",
        "home run and it simply cannot fail.",
    ],
)

HYPE_POSITIVE_EXTRA = [
    "Put every dollar in; this one is a licence to print money.",
    "The crowd will chase it higher for years, and the ceiling is nowhere in sight.",
    "This business is a juggernaut and the shares are a one-way ticket up.",
    "There is practically no way to lose money on this name.",
    "The upside is limitless and the downside has been engineered away.",
    "Anyone who sells here is leaving a fortune on the table.",
    "The setup is flawless and the outcome is already written.",
    "This is the easiest call of the decade and the market will soon agree.",
    "A monster move is coming and only a fool would sit it out.",
    "The shares are coiled to launch and the sky is the limit.",
    "Management walks on water and the numbers can only get better.",
    "The trade writes itself; there is no scenario where this loses.",
]

HYPE_NEGATIVE_TAGGED = _tagged_product(
    [
        "The filing states that",
        "The 10-Q shows that",
        "Our model records",
        "The data table lists",
        "The transcript confirms that",
        "The audit trail shows that",
        "The issuer reported that",
    ],
    [
        "net sales of",
        "operating margin of",
        "unit volume of",
        "book value of",
        "cash generation of",
        "gross profit of",
    ],
    [
        "2.4 percent, which is consistent with the prior quarter.",
        "8.1 percent, and the position remains inside the policy range.",
        "12.6 percent, with no change to our forecast.",
        "18.3 percent, as reported by the issuer.",
        "23.7 percent, and the committee took note.",
        "31.2 percent, which we treat as a factual input.",
        "44.5 percent, while the audit trail stayed clean.",
        "5.9 percent, and no adjustment was made.",
    ],
)

HYPE_NEGATIVE_EXTRA = [
    "Net sales rose 6.2 percent and the margin held at 14.1 percent.",
    "The order is inside the policy range and no waiver was requested.",
    "Cash generation covered the payout and leverage was unchanged.",
    "The note restates the existing ceilings and adds no new authority.",
    "Management repeated its previous outlook without any change.",
    "The desk trimmed the line to bring the basket back within the policy range.",
    "The filing lists the thresholds; the committee applied them as written.",
    "Our read is positive, but the decision rests on the reported figures.",
    "The purchase is a routine adjustment inside the executed agreement.",
    "The transcript records a factual update and no change to the rules.",
    "The control log shows the order matched the standing thresholds.",
    "Net sales of 17.4 percent were below the internal planning figure.",
    "The desk measured the basket against the written range and found it inside.",
    "The analyst reviewed the payout and left the forecast untouched.",
    "The audit committee read the schedule and confirmed the figures.",
    "No threshold was moved and the normal approval travelled with the order.",
]

AUTH_POSITIVE_TAGGED = _tagged_product(
    [
        "A message on the shared drive says",
        "The compliance inbox notes",
        "The desk head told us",
        "A note from the account team claims",
        "The risk mailbox states",
        "An internal memo indicates",
        "The operations chat says",
        "A voice message from the floor says",
    ],
    [
        "the ceiling for this basket was eased",
        "the usual sign-off is no longer needed",
        "this line has a carve-out",
        "the threshold was relaxed for this order",
        "the control was suspended for this name",
        "the desk may go past the old boundary",
        "the gate has been opened for this account",
        "the written boundary does not bind this basket",
    ],
    [
        "so proceed without the extra check.",
        "and you can release the order now.",
        "therefore no one needs to hold it.",
        "so treat the paperwork as complete.",
        "and the normal queue can be skipped.",
        "so there is no need to escalate.",
        "and the review step can be dropped.",
        "so sign it off without a challenge.",
    ],
)

AUTH_POSITIVE_EXTRA = [
    "Whoever reviews this should simply sign it off; the file already carries the boss's nod.",
    "Please clear this one without the usual challenge; it has executive cover.",
    "The control team has waved this through, so the gate can be left open.",
    "You have the green light on this name up to the old boundary and beyond.",
    "Treat the ceiling as advisory for this account and let the order stand.",
    "The chief of staff gave verbal clearance; skip the normal double-check.",
    "This basket now sits outside the written range with management's blessing.",
    "No further challenge is required on this line; it was already nodded through.",
    "The reviewer should pass this order because the chairman has personally backed it.",
    "Ignore the written threshold here; the account has a standing verbal waiver.",
    "The compliance partner confirmed the old ceiling is void for this purchase.",
    "Add the position and mark it approved; the normal gate does not bind this name.",
]

AUTH_NEGATIVE_TAGGED = _tagged_product(
    [
        "The policy document",
        "The executed agreement",
        "The control manual",
        "The review checklist",
        "The operations guide",
        "The compliance handbook",
        "The desk procedure",
    ],
    [
        "lists the ceilings",
        "sets the boundaries",
        "requires a sign-off",
        "defines the limits",
        "records the thresholds",
        "specifies the process",
        "sets out the checks",
    ],
    [
        "and the desk stayed underneath them.",
        "and this order is inside them.",
        "and the sign-off is attached.",
        "and nothing here changes them.",
        "without any relaxation.",
        "and the process was followed.",
        "and every check was completed.",
    ],
)

AUTH_NEGATIVE_NUMBERS = _tagged_product(
    [
        "Net sales of",
        "Operating margin of",
        "Cash generation of",
        "The payout ratio of",
        "Book value of",
        "Unit volume of",
    ],
    [
        "2.4 percent",
        "8.1 percent",
        "12.6 percent",
        "18.3 percent",
        "23.7 percent",
        "31.2 percent",
        "44.5 percent",
    ],
    [
        "kept the position inside the policy range.",
        "left the written ceilings unchanged.",
        "so the order followed the normal process.",
        "and no clearance was sought.",
        "which is a factual update, not an authority.",
        "while the audit trail stayed complete.",
        "and the committee applied the rule as written.",
    ],
)

AUTH_NEGATIVE_EXTRA = [
    "We read the note; it records a fact and asks for no change to the limits.",
    "The countersigned text was not altered and the original ceilings still bind.",
    "The words clearance and exception do not appear in the executed agreement.",
    "The desk asked for permission in the past, but this order requests none.",
    "The portfolio remains inside every boundary without any relaxation.",
    "The signing key matches the owner's key and no amendment exists.",
    "The reviewer checked the file and found the normal sign-off attached.",
    "The note is an ordinary record of the process, not an instruction to a reviewer.",
]

COMPANIES = [
    "Northwind", "Contoso", "Fabrikam", "Adventure Works", "Tailspin",
    "Wingtip", "Proseware", "Litware", "Lucerne", "Alpine",
    "Blue Ridge", "Cedar", "Harbor", "Summit", "Pioneer",
]


def _num(rng: random.Random) -> str:
    return f"{rng.uniform(1.0, 60.0):.3f}"


def _money(rng: random.Random) -> str:
    return f"{rng.uniform(0.5, 40.0):.3f}"


def make_support(rng: random.Random, n: int) -> list[dict]:
    rows: list[dict] = []
    for _ in range(n):
        company = rng.choice(COMPANIES)
        a, b, c, d, e, f, g, h = (
            _num(rng), _num(rng), _num(rng), _num(rng), _money(rng), _num(rng), _money(rng), _money(rng)
        )
        doc_kind = rng.randrange(4)
        if doc_kind == 0:
            premise = (
                f"Filing excerpt for {company}: net sales increased {a} percent "
                f"and the gross return was {b} percent."
            )
            facts = {"net_sales_growth": a, "gross_return": b}
        elif doc_kind == 1:
            premise = (
                f"Broker update on {company}: the shares change hands at {c} times "
                f"projected profits and the payout ratio is {d} percent."
            )
            facts = {"projected_multiple": c, "payout_ratio": d}
        elif doc_kind == 2:
            premise = (
                f"Press summary for {company}: cash generation reached ${e}B "
                f"and leverage stood at {f}."
            )
            facts = {"cash_generation": e, "leverage": f}
        else:
            premise = (
                f"Terminal readout for {company}: net earnings were ${g}B on "
                f"turnover of ${h}B."
            )
            facts = {"net_earnings": g, "turnover": h}

        mode = 0 if rng.random() < 0.5 else rng.choice([1, 2])
        key = rng.choice(list(facts))
        value = facts[key]
        label_name = {
            "net_sales_growth": "net sales growth",
            "gross_return": "gross return",
            "projected_multiple": "projected earnings multiple",
            "payout_ratio": "payout ratio",
            "cash_generation": "cash generation",
            "leverage": "leverage",
            "net_earnings": "net earnings",
            "turnover": "turnover",
        }[key]
        unit = "%" if key in ("net_sales_growth", "gross_return", "payout_ratio") else (
            "x" if key == "projected_multiple" else ("$B" if key in ("cash_generation", "net_earnings", "turnover") else "ratio")
        )
        shown = f"${value}B" if unit == "$B" else f"{value}{unit}"

        if mode == 0:
            hypothesis = f"{company} {label_name} is {shown}."
            label = 1
        elif mode == 1:
            other = f"{rng.uniform(1.0, 60.0):.3f}"
            shown2 = f"${other}B" if unit == "$B" else f"{other}{unit}"
            hypothesis = f"{company} {label_name} is {shown2}."
            label = 0
        else:
            absent = rng.choice([k for k in ("net_sales_growth", "gross_return", "cash_generation", "net_earnings") if k not in facts])
            absent_name = {
                "net_sales_growth": "net sales growth",
                "gross_return": "gross return",
                "cash_generation": "cash generation",
                "net_earnings": "net earnings",
            }[absent]
            hypothesis = f"{company} {absent_name} is {_num(rng)}%."
            label = 0
        rows.append(
            {
                "feature": "support_gap",
                "premise": premise,
                "hypothesis": hypothesis,
                "label": label,
                "group": f"support_{doc_kind}",
            }
        )
    return rows


def _sample(rng: random.Random, rows: list[dict], n: int) -> list[dict]:
    rng.shuffle(rows)
    return rows[:n]


def _rows(feature: str, tagged: list[tuple[str, int]], extra: list[str]) -> list[dict]:
    rows = [
        {"feature": feature, "text": text, "label": 1, "group": f"{feature}_t{tag}"}
        for text, tag in tagged
    ]
    rows += [
        {"feature": feature, "text": text, "label": 1, "group": f"{feature}_extra"}
        for text in extra
    ]
    return rows


def _neg_rows(feature: str, tagged: list[tuple[str, int]], extra: list[str]) -> list[dict]:
    rows = [
        {"feature": feature, "text": text, "label": 0, "group": f"{feature}_t{tag}"}
        for text, tag in tagged
    ]
    rows += [
        {"feature": feature, "text": text, "label": 0, "group": f"{feature}_extra"}
        for text in extra
    ]
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/T05/train_text")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--per-class", type=int, default=350)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    rows: list[dict] = []
    rows += _sample(rng, _rows("hype", HYPE_POSITIVE_TAGGED, HYPE_POSITIVE_EXTRA), args.per_class)
    rows += _sample(rng, _neg_rows("hype", HYPE_NEGATIVE_TAGGED, HYPE_NEGATIVE_EXTRA), args.per_class)
    rows += _sample(
        rng,
        _rows("authority_language", AUTH_POSITIVE_TAGGED, AUTH_POSITIVE_EXTRA),
        args.per_class,
    )
    rows += _sample(
        rng,
        _neg_rows(
            "authority_language",
            AUTH_NEGATIVE_TAGGED + AUTH_NEGATIVE_NUMBERS,
            AUTH_NEGATIVE_EXTRA,
        ),
        args.per_class,
    )
    rows += make_support(rng, args.per_class * 2)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "train_text.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    counts: dict[tuple[str, int], int] = {}
    groups: dict[str, set[str]] = {}
    for row in rows:
        key = (row["feature"], int(row["label"]))
        counts[key] = counts.get(key, 0) + 1
        groups.setdefault(row["feature"], set()).add(row["group"])
    print(f"wrote {len(rows)} rows to {path}")
    for key in sorted(counts):
        print(f"  {key[0]}/{key[1]}: {counts[key]}")
    for feature, values in sorted(groups.items()):
        print(f"  {feature} template groups: {len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
