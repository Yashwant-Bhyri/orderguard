"""The decision table. Code only: no model is consulted here.

Input: the claims, one verdict per claim. Output: pass, revise, block or escalate for the TEXT. What that means for an
order (or anything else) is the domain pack's business, not this file's. The order of the rules is their precedence."""
from __future__ import annotations

from .models import Claim, Decision, Verdict
from .pack import Pack


def decide(pack: Pack, claims: list[Claim], verdicts: list[Verdict]) -> Decision:
    label = {v.claim_id: v.label for v in verdicts}
    ids = lambda cs: [c.id for c in cs]

    def key_claims(want: str) -> list[Claim]:
        return [c for c in claims if label[c.id] == want and c.key and c.type not in pack.never_key_types]

    def why(c: Claim) -> str:
        return f"“{c.text}” — {next(v.reason for v in verdicts if v.claim_id == c.id)}"

    # 1. a key claim is contradicted by trusted data -> block, and tell someone
    bad = key_claims("contradicted")
    if bad:
        return Decision(action="block", alert=True, fix=ids(bad), reasons=["contradicted by trusted data: " + why(c) for c in bad])

    # 2. a key claim was true once but is out of date -> revise (the pipeline refreshes the data and re-checks once first)
    stale = key_claims("stale")
    if stale:
        return Decision(action="revise", fix=ids(stale), refresh=sorted({c.subject for c in stale if c.subject}),
                        reasons=["out of date: " + why(c) for c in stale])

    # 2b. a key claim states a fact the source proves did not exist yet on the memo's date (a figure from the future) -> revise
    premature = [c for c in key_claims("unverifiable") if next(v.premature for v in verdicts if v.claim_id == c.id)]
    if premature:
        return Decision(action="revise", fix=ids(premature), reasons=["not public on the decision date, remove it or date the text later: " + why(c) for c in premature])

    # 3. the main reason for the request cannot be verified -> a human must look
    unverifiable = key_claims("unverifiable")
    main = [c for c in unverifiable if c.main_reason]
    if main:
        return Decision(action="escalate", fix=ids(main), reasons=["the main reason cannot be verified: " + why(c) for c in main])

    # 4. nothing verified supports it: opinion and rumour alone never carry a request -> a human must look
    if not any(label[c.id] == "confirmed" and c.type in pack.hard_types for c in claims):
        return Decision(action="escalate", reasons=["no claim could be verified (rumour and opinion alone never carry a request)"])

    # 5. smaller problems: a wrong side-claim, or a rumour stated as part of the case -> revise
    side_bad = [c for c in claims if label[c.id] == "contradicted" and c.type not in pack.never_key_types]
    rumours = [c for c in unverifiable if c.type in pack.unconfirmable_types]
    if side_bad or rumours:
        return Decision(action="revise", fix=ids(side_bad + rumours),
                        reasons=["wrong: " + why(c) for c in side_bad] + ["cannot be confirmed, remove or source it: " + why(c) for c in rumours])

    # 6. otherwise pass (claims that could not be checked are listed in the coverage line, never silently trusted)
    n = sum(label[c.id] == "confirmed" for c in claims)
    return Decision(action="pass", reasons=[f"{n} claim(s) confirmed by trusted data; none contradicted"])
