"""Freeze the authority candidate readers before any unseen scoring.

The lead's ruling (SOL_ADVICE.md, 2026-11-19) asks for the exact reader text
and a SHA-256 of each reader configuration in work/T05/PREREGISTERED.md.
T07 and T11 will score these frozen candidates on the unseen worlds; nothing
in this file may be tuned on data/ref after this run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from og_s1.readers import decision, lexicon, nli  # noqa: E402
import evaluate  # noqa: E402


def digest(value: object) -> str:
    body = json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def block(title: str, value: object) -> list[str]:
    return [
        f"### {title}",
        "",
        f"SHA-256 of configuration: `{digest(value)}`",
        "",
        "```json",
        json.dumps(value, indent=2, sort_keys=True),
        "```",
        "",
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import re

    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the frozen file")
    mode.add_argument("--check", action="store_true", help="fail on any hash mismatch")
    args = parser.parse_args(argv)

    config = {
        "small_lexicon": {
            "reader": lexicon.NAME,
            "hype_table": lexicon._HYPE,
            "authority_table": lexicon._AUTHORITY,
        },
        "extended_authority_list": {
            "reader": "extended_fixed_list_sensitivity",
            "phrases": evaluate.EXTENDED_AUTHORITY_PHRASES,
        },
        "nli_default_hypotheses": {
            "reader": nli.NAME,
            "checkpoint": nli.MODEL_ID,
            "hype_sides": nli.HYPE_SIDES,
            "authority_sides": nli.AUTHORITY_SIDES,
        },
        "nli_authority_template_candidates": {
            "reader": nli.NAME,
            "checkpoint": nli.MODEL_ID,
            "templates": evaluate.AUTHORITY_TEMPLATES,
        },
        "decision_model_questions": {
            "reader": decision.NAME,
            "model": decision.MODEL,
            "questions": decision.QUESTIONS,
        },
    }
    overall = digest(config)
    out = HERE / "PREREGISTERED.md"

    if args.check:
        if not out.exists():
            print("PREREGISTERED.md is missing; refusing to invent a freeze", file=sys.stderr)
            return 1
        frozen = out.read_text(encoding="utf-8")
        match = re.search(r"Overall SHA-256 of this frozen configuration: `([0-9a-f]{64})`", frozen)
        if not match:
            print("PREREGISTERED.md has no overall hash; refusing to continue", file=sys.stderr)
            return 1
        recorded = match.group(1)
        if recorded != overall:
            print("PREREGISTRATION MISMATCH", file=sys.stderr)
            print(f"  frozen file: {recorded}", file=sys.stderr)
            print(f"  current code: {overall}", file=sys.stderr)
            print(
                "A reader configuration changed. Write a new preregistration file; "
                "never overwrite the frozen one in place.",
                file=sys.stderr,
            )
            return 1
        print(f"preregistered configuration sha256: {overall} (matches static file)")
        return 0

    if not args.write and out.exists():
        # Default is check, so a plain invocation cannot silently rewrite history.
        print(
            "PREREGISTERED.md exists; use --check to verify or --write to replace it "
            "with a new preregistration.",
            file=sys.stderr,
        )
        return 1

    lines = [
        "# T05 pre-registered authority readers",
        "",
        "Frozen on 2026-11-19 under the lead's ruling in `SOL_ADVICE.md`. These",
        "are the only candidates T07/T11 may score for the authority sub-question;",
        "anything else is post-hoc. The official floor is the small registered",
        "lexicon. The extended list is an upper-bound sensitivity, not a reader.",
        "",
        "This file is static. `run.sh` recomputes these hashes and fails on any",
        "mismatch; it never rewrites the file. A changed reader needs a new",
        "preregistration file, not an edit to this one.",
        "",
        f"Overall SHA-256 of this frozen configuration: `{overall}`",
        "",
    ]
    lines += block("Small registered lexicon (floor)", config["small_lexicon"])
    lines += block("Extended authority list (sensitivity, not a reader)", config["extended_authority_list"])
    lines += block("NLI default hypotheses", config["nli_default_hypotheses"])
    lines += block("NLI authority template candidates", config["nli_authority_template_candidates"])
    lines += block("External decision model questions", config["decision_model_questions"])
    lines += [
        "NLI support uses the checkpoint with the document as premise and the",
        "claim as hypothesis; it has no free-text template to freeze.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote work/T05/PREREGISTERED.md")
    print(f"preregistered configuration sha256: {overall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
