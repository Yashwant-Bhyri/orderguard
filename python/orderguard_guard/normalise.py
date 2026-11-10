"""L1 normalise: code-only cleaning of text before any model reads it.

  - strips zero-width and bidi-control characters and Unicode tag characters (U+E0000 block), reporting them;
  - decodes what the tag characters spelled, so the hidden instruction is visible in the finding;
  - NFKC normalisation (fullwidth letters, ligatures, compatibility forms);
  - flags mixed-script tokens such as a Cyrillic А inside "АAPL";
  - decodes long base64 runs and appends the decoded text so the screen can judge it.

Measured motivation: in the detection test (lab/legacy/attack-lab-2026-11-06/README.md, round 3) the one attack that
two of three model screens missed was the invisible Unicode-tag instruction. Code closes that gap for free.
"""
from __future__ import annotations

import base64
import re
import unicodedata

ZERO_WIDTH = {
    "​": "ZERO WIDTH SPACE", "‌": "ZERO WIDTH NON-JOINER", "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER", "﻿": "ZERO WIDTH NO-BREAK SPACE", "᠎": "MONGOLIAN VOWEL SEPARATOR",
    "­": "SOFT HYPHEN", "‎": "LEFT-TO-RIGHT MARK", "‏": "RIGHT-TO-LEFT MARK",
    "‪": "LRE", "‫": "RLE", "‬": "PDF", "‭": "LRO", "‮": "RLO",
    "⁦": "LRI", "⁧": "RLI", "⁨": "FSI", "⁩": "PDI", "؜": "ARABIC LETTER MARK",
}
TAG_LO, TAG_HI = 0xE0000, 0xE007F
_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=])")
_TOKEN = re.compile(r"[^\W\d_]{2,}[\w]*", re.UNICODE)

# Characters that look like Latin letters. Used to tell "ticker written with a Cyrillic А" from a real ticker.
CONFUSABLES = {
    # Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    # Greek
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "ο": "o", "ν": "v",
}


def script_of(ch: str) -> str:
    """Coarse script name for one letter: Latin, Cyrillic, Greek, Han, Other."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "Other"
    for s in ("LATIN", "CYRILLIC", "GREEK", "CJK", "HIRAGANA", "KATAKANA", "ARABIC", "HEBREW", "HANGUL", "THAI", "DEVANAGARI"):
        if name.startswith(s):
            return "Han" if s == "CJK" else s.title()
    return "Other"


def mixed_script_tokens(text: str) -> list[tuple[str, list[str]]]:
    """Tokens that mix letters from two or more scripts, e.g. ('АAPL', ['Cyrillic', 'Latin'])."""
    out = []
    for tok in _TOKEN.findall(text):
        scripts = {script_of(c) for c in tok if c.isalpha()}
        scripts.discard("Other")
        if len(scripts) >= 2:
            out.append((tok, sorted(scripts)))
    return out


def fold_confusables(s: str) -> str:
    """Map look-alike Cyrillic/Greek letters to their Latin shapes. Used by the gate to name what the ticker looked like."""
    return "".join(CONFUSABLES.get(c, c) for c in s)


def non_latin_letters(s: str) -> list[str]:
    return [c for c in s if c.isalpha() and script_of(c) not in ("Latin", "Other")]


def _decode_b64(run: str) -> str | None:
    try:
        raw = base64.b64decode(run + "=" * (-len(run) % 4), validate=False)
        text = raw.decode("utf-8")
    except Exception:
        return None
    if not text:
        return None
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in text) / len(text)
    return text if printable > 0.95 else None


def clean(text: str) -> tuple[str, list[str]]:
    """Return (clean_text, findings). Findings are plain sentences; an empty list means nothing was touched.

    Severity is in the first word of each finding: 'tag', 'zero-width', 'bidi', 'mixed-script', 'base64', 'nfkc'.
    """
    findings: list[str] = []
    if not text:
        return text, findings

    # 1. Unicode tag characters: decode what they spell, then remove them.
    tags = [c for c in text if TAG_LO <= ord(c) <= TAG_HI]
    if tags:
        hidden = "".join(chr(ord(c) - TAG_LO) for c in tags if 0x20 <= ord(c) - TAG_LO < 0x7F)
        findings.append(f"tag characters: {len(tags)} invisible Unicode tag characters spelled {hidden[:160]!r}; removed")
        text = "".join(c for c in text if not TAG_LO <= ord(c) <= TAG_HI)

    # 2. Zero-width and bidi controls.
    counts: dict[str, int] = {}
    for c in text:
        if c in ZERO_WIDTH:
            counts[c] = counts.get(c, 0) + 1
    if counts:
        bidi = {c: n for c, n in counts.items() if c in "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"}
        zw = {c: n for c, n in counts.items() if c not in bidi and c != "­"}
        if "­" in counts:   # soft hyphens occur in honest typeset text; report, do not treat as an attack
            findings.append(f"soft hyphens: {counts[chr(0xAD)]}; removed")
        if zw:
            desc = ", ".join(f"{n} {ZERO_WIDTH[c]}" for c, n in zw.items())
            findings.append(f"zero-width characters: {desc}; removed")
        if bidi:
            desc = ", ".join(f"{n} {ZERO_WIDTH[c]}" for c, n in bidi.items())
            findings.append(f"bidi controls: {desc}; removed")
        text = "".join(c for c in text if c not in ZERO_WIDTH)

    # 3. NFKC.
    nfkc = unicodedata.normalize("NFKC", text)
    if nfkc != text:
        findings.append("nfkc: compatibility characters (fullwidth letters, ligatures or similar) were normalised")
        text = nfkc

    # 4. Mixed-script tokens.
    mixed = mixed_script_tokens(text)
    if mixed:
        shown = "; ".join(f"{tok!r} ({'+'.join(s)}, looks like {fold_confusables(tok)!r})" for tok, s in mixed[:5])
        findings.append(f"mixed-script tokens: {shown}")

    # 5. Long base64 runs: decode and append so a model screen sees the payload.
    def repl(m: re.Match) -> str:
        decoded = _decode_b64(m.group(0))
        if decoded is None:
            return m.group(0)
        findings.append(f"base64: a {len(m.group(0))}-character run decodes to {decoded[:160]!r}")
        return f"{m.group(0)} [decoded base64: {decoded}]"
    text = _B64.sub(repl, text)
    return text, findings


SEVERE = ("tag characters", "zero-width characters", "bidi controls", "mixed-script tokens")


def severe(findings: list[str]) -> list[str]:
    """Findings that on their own justify quarantining the chunk without asking a model."""
    return [f for f in findings if f.startswith(SEVERE)]
