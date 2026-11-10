"""The evidence card, as plain text (terminal) and as a small HTML fragment (review page)."""
from __future__ import annotations

from html import escape

from .pipeline import Result

MARK = {"confirmed": "OK ", "contradicted": "XX ", "stale": "OLD", "unverifiable": "?? "}


def text_card(r: Result, status: str = "") -> str:
    d = r.decision
    lines = [f"DECISION: {d.action.upper()}" + ("  [ALERT]" if d.alert else "") + (f"   ({status})" if status else ""),
             f"About:    {r.summary} (decision date {r.as_of})", f"Coverage: {r.coverage}"] + (["", "Claims checked:"] if r.claims else [])
    verdict = {v.claim_id: v for v in r.verdicts}
    for c in r.claims:
        v = verdict[c.id]
        flag = " (key)" if c.key else ""
        fix = "  <- fix" if c.id in d.fix else ""
        lines.append(f"  [{MARK[v.label]}] {v.label.upper()}{flag}: “{c.text}”{fix}")
        lines.append(f"        {v.reason}")
        for e in v.evidence[:1]:
            lines.append(f"        evidence: {e.source}, public {e.as_of}\n                  {e.source_url}\n                  hash {e.hash[:16]}")
    lines += ["", "Why:"] + [f"  - {x}" for x in d.reasons]
    return "\n".join(lines)


def html_card(r: Result, status: str = "") -> str:
    d = r.decision
    verdict = {v.claim_id: v for v in r.verdicts}
    rows = []
    for c in r.claims:
        v = verdict[c.id]
        ev = "".join(
            f'<div class="ev"><b>{escape(e.source)}</b> · public {escape(e.as_of)} · {e.value:g} {escape(e.unit)}'
            f' · <a href="{escape(e.source_url)}">source</a> · <code>{escape(e.hash[:12])}</code></div>' for e in v.evidence)
        rows.append(
            f'<tr class="{v.label}"><td><span class="tag {v.label}">{v.label}</span>{" <i>key</i>" if c.key else ""}'
            f'{" <b>fix</b>" if c.id in d.fix else ""}</td>'
            f'<td>“{escape(c.text)}”<div class="why">{escape(v.reason)}</div>{ev}</td></tr>')
    reasons = "".join(f"<li>{escape(x)}</li>" for x in d.reasons)
    return (f'<section class="card {d.action}"><h2><span class="act {d.action}">{d.action.upper()}</span> '
            f'{escape(r.summary)}{" <span class=alert>ALERT</span>" if d.alert else ""} <small>{escape(status)}</small></h2>'
            f'<p class="meta">decision date {r.as_of} · {escape(r.coverage)} · run {escape(r.run_id)}</p>'
            f'<table>{"".join(rows)}</table><h3>Why</h3><ul>{reasons}</ul></section>')
