"""L1 normalise: code-only cleaning of text before any model reads it.

  - strips default-ignorable Unicode characters, including zero-width and bidi controls, reporting them;
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
# Further default-ignorable characters that render as nothing and can split a keyword in front of a text screen.
ZERO_WIDTH.update({chr(c): n for c, n in (
    (0x2061, "FUNCTION APPLICATION"), (0x2062, "INVISIBLE TIMES"), (0x2063, "INVISIBLE SEPARATOR"), (0x2064, "INVISIBLE PLUS"),
    (0x034F, "COMBINING GRAPHEME JOINER"), (0x115F, "HANGUL CHOSEONG FILLER"), (0x1160, "HANGUL JUNGSEONG FILLER"),
    (0x3164, "HANGUL FILLER"), (0xFFA0, "HALFWIDTH HANGUL FILLER"), (0x17B4, "KHMER VOWEL INHERENT AQ"),
    (0x17B5, "KHMER VOWEL INHERENT AA"), (0x180B, "MONGOLIAN FVS1"), (0x180C, "MONGOLIAN FVS2"), (0x180D, "MONGOLIAN FVS3"),
    (0x180F, "MONGOLIAN FVS4"))})
ZERO_WIDTH.update({chr(c): f"VARIATION SELECTOR-{c - 0xFE00 + 1}" for c in range(0xFE00, 0xFE10)})
# Remaining Default_Ignorable_Code_Point ranges from Unicode 17 DerivedCoreProperties.txt.
# U+E0000..U+E007F are handled separately to recover the text encoded by Unicode tags.
ZERO_WIDTH.update({
    chr(c): unicodedata.name(chr(c), f"U+{c:04X}")
    for start, end in ((0x2065, 0x2065), (0x206A, 0x206F), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
                       (0x1D173, 0x1D17A), (0xE0080, 0xE0FFF))
    for c in range(start, end + 1)
})
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
    except ValueError:
        return None
    if not text:
        return None
    printable = sum(
        ch.isprintable() or ch in "\n\t" or ch in ZERO_WIDTH or TAG_LO <= ord(ch) <= TAG_HI
        for ch in text
    ) / len(text)
    return text if printable > 0.95 else None


def _expand_base64(text: str, findings: list[str]) -> str:
    parts: list[str] = []
    end = 0
    while (match := _B64.search(text, end)) is not None:
        parts.append(text[end:match.end()])
        end = match.end()
        run = match.group()
        decoded = _decode_b64(run)
        if decoded is None:
            continue

        # Decoding shrinks the input, so cleaning the decoded text also exposes nested runs.
        cleaned, decoded_findings = clean(decoded)
        annotation = f" [decoded base64: {cleaned}]"
        if text.startswith(annotation, end):
            end += len(annotation)
            # A matching annotation can come from untrusted input. Still report hidden text in the encoded run.
            findings.extend(severe(decoded_findings))
        else:
            findings.append(f"base64: a {len(run)}-character run decodes to {decoded[:160]!r}")
            findings.extend(decoded_findings)
        parts.append(annotation)
    parts.append(text[end:])
    return "".join(parts)


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
    return _expand_base64(text, findings), findings


SEVERE = ("tag characters", "zero-width characters", "bidi controls", "mixed-script tokens")


def severe(findings: list[str]) -> list[str]:
    """Findings that on their own justify quarantining the chunk without asking a model."""
    return [f for f in findings if f.startswith(SEVERE)]
