"""L1 normalise: code-only cleaning of text before any model reads it.

  - strips default-ignorable Unicode characters, including zero-width and bidi controls, reporting them;
  - decodes what the tag characters spelled, so the hidden instruction is visible in the finding;
  - NFKC normalisation (fullwidth letters, ligatures, compatibility forms);
  - flags mixed-script tokens such as a Cyrillic А inside "АAPL";
  - decodes base64 (long, short, chunked across lines, URL-safe), hex, percent-escapes, backslash and HTML escapes and appends the
    decoded text so the screen can judge it; ROT13 and reversed directives are surfaced the same way;
  - strips control characters, unpaired surrogates and stacked combining marks (Zalgo) that split keywords in front of a text screen;
  - folds look-alike Latin letters that NFKC leaves alone (small capitals, dotless i).

`clean` never raises, whatever it is given, and is idempotent: clean(clean(x)[0])[0] == clean(x)[0].

Measured motivation: in the detection test (lab/legacy/attack-lab-2026-11-06/README.md, round 3) the one attack that
two of three model screens missed was the invisible Unicode-tag instruction. Code closes that gap for free.
"""
from __future__ import annotations

import base64
import binascii
import codecs
import functools
import html
import re
import unicodedata
from itertools import islice
from urllib.parse import unquote_to_bytes

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
# Not default-ignorable, but they render as nothing (a blank Braille cell) and split keywords just as well.
ZERO_WIDTH["\u2800"] = "BRAILLE PATTERN BLANK"
TAG_LO, TAG_HI = 0xE0000, 0xE007F
BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c")
_ZW_TABLE = {ord(c): None for c in ZERO_WIDTH}
# Controls that are not text: NUL, ANSI escape, the rest of C0/C1. Tab, newline, carriage return stay. Page/line separators become newlines.
_NEWLINES = {0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F, 0x85, 0x2028, 0x2029}
_CTRL_TABLE = {c: None for c in list(range(0x20)) + list(range(0x7F, 0xA0)) if c not in (9, 10, 13) and c not in _NEWLINES}
_NL_TABLE = {c: "\n" for c in _NEWLINES}
_SPACE_TABLE = {0x1680: " "}
_SURROGATE = re.compile("[\ud800-\udfff]")
_MARKS = "\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
_MARKED_WORD = re.compile(f"(?:[^\\W\\d_]|[{_MARKS}])+")
_MARK = re.compile(f"[{_MARKS}]")
_MAX_DEPTH = 6                 # nested decodings followed
_MAX_DECODED = 1 << 20         # total characters decoded from one call tree
_MAX_RUNS = 400                # encoded runs decoded from one call tree
_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=])")
_TOKEN = re.compile(r"[^\W\d_]{2,}[\w]*", re.UNICODE)
_B64X = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{20,}={0,2}(?![A-Za-z0-9+/=_-])")
_B64_PIECE = re.compile(r"[A-Za-z0-9+/_-]{2,}={0,2}|[A-Za-z0-9+/_-]={1,2}")
# Cheap pre-test for chunked base64: at least three base64-looking words (a digit, + / _, or a capital inside the word) anywhere in the text.
_LIKE_PIECE = re.compile(r"(?<![A-Za-z0-9+/_=-])(?=[A-Za-z0-9+/_-]{4})(?=[0-9+/_-]*[A-Za-z])(?:[A-Za-z0-9+/_-]*[0-9+/_]|[A-Za-z0-9+/_-]+[A-Z])")
_B64_GAP = re.compile(r"[ \t\r\n\"',.|;]{1,4}")
_HEX = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){12,}(?![0-9A-Fa-f])")
_HEX_SPACED = re.compile(r"(?<![A-Za-z0-9])(?:[0-9A-Fa-f]{2}[ :,-]){11,}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
_PCT = re.compile(r"(?:%[0-9A-Fa-f]{2}){6,}")
_BSLASH = re.compile(r"(?:\\x[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}){6,}")
_ENTITY_RUN = re.compile(r"(?:&#[xX]?[0-9A-Fa-f]{1,6};){6,}")
# What an attacker wants a trading agent to do, in the plainest words; used only to look inside ROT13 and reversed text.
_DIRECTIVE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b[^\n]{0,40}\b(?:instructions?|rules?|mandate|limits?|prompt|previous|above|prior|guidelines)\b"
    r"|\b(?:transfer|wire|withdraw|send)\b[^\n]{0,30}(?:\bfunds?\b|\bmoney\b|\baccount\b|\busd\b|\bdollars?\b|\$\d)"
    r"|\bsell (?:all|everything)\b|\bsystem prompt\b|\bnew instructions?\b", re.I)

# Characters that look like Latin letters. Used to tell "ticker written with a Cyrillic А" from a real ticker.
CONFUSABLES = {
    # Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "Ԁ": "D", "ԁ": "d", "Ԛ": "Q", "ԛ": "q", "Ԝ": "W", "ԝ": "w", "һ": "h", "Ӏ": "I", "ӏ": "l", "ѵ": "v", "Ү": "Y", "ү": "y", "ё": "e", "Ё": "E",
    # Greek
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "ο": "o", "ν": "v", "α": "a", "ι": "i", "κ": "k", "ρ": "p", "υ": "u", "ϲ": "c", "Ϲ": "C", "ϳ": "j", "Ϳ": "J",
    # Armenian
    "օ": "o", "Օ": "O", "ո": "n", "ս": "u", "Ս": "U", "ց": "g", "ք": "q",
    # Cherokee
    "Ꭺ": "A", "Ᏼ": "B", "Ꮯ": "C", "Ꭰ": "D", "Ꭼ": "E", "Ꮐ": "G", "Ꮋ": "H", "Ꭻ": "J", "Ꮶ": "K", "Ꮮ": "L", "Ꮇ": "M", "Ꮪ": "S", "Ꭲ": "T", "Ꮩ": "V",
    "Ꮃ": "W", "Ꮓ": "Z", "Ꮲ": "P",
}
# Latin-script letters that NFKC keeps as they are (small capitals, dotless i, script g): folded by `clean`, not a script mix.
LATIN_LOOKALIKES = {
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n",
    "ᴏ": "o", "ᴘ": "p", "ʀ": "r", "ꜱ": "s", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w", "ʏ": "y", "ᴢ": "z", "ɑ": "a", "ɡ": "g", "ı": "i", "ȷ": "j",
    "ɩ": "i", "ǀ": "l",
}
_LOOKALIKE_TABLE = {ord(k): v for k, v in LATIN_LOOKALIKES.items()}
# Scripts that have letters shaped like Latin ones. A token mixing two of these is a spoof candidate; Latin next to CJK, Arabic, Hebrew,
# Thai or Indic letters is ordinary text (no look-alikes), so it is not flagged.
_SPOOF_SCRIPTS = frozenset({"Latin", "Cyrillic", "Greek", "Armenian", "Cherokee", "Coptic", "Georgian", "Lisu"})
_SCRIPT_WORDS = {"CJK": "Han", "KATAKANA": "Katakana", "HIRAGANA": "Hiragana"}
_NOT_SCRIPT = frozenset({"MODIFIER", "SMALL", "CAPITAL", "FULLWIDTH", "HALFWIDTH", "SUBSCRIPT", "SUPERSCRIPT", "MATHEMATICAL", "DIGIT", "ROMAN",
                         "CIRCLED", "PARENTHESIZED", "SQUARED", "NEGATIVE", "DOUBLE-STRUCK", "BLACK-LETTER", "SCRIPT", "BOLD", "ITALIC", "PLANCK",
                         "ANGSTROM", "KELVIN", "OHM", "ACCOUNT", "DEGREE", "PER", "NUMERO", "SERVICE", "TELEPHONE", "COMBINING"})


@functools.lru_cache(maxsize=65536)
def script_of(ch: str) -> str:
    """Script name for one letter: Latin, Cyrillic, Greek, Armenian, Cherokee, Han, ... ('Other' when it has none)."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "Other"
    first = name.split(" ", 1)[0]
    if first in _SCRIPT_WORDS:
        return _SCRIPT_WORDS[first]
    if first in _NOT_SCRIPT:
        return "Other"
    return first.title()


def mixed_script_tokens(text: str) -> list[tuple[str, list[str]]]:
    """Tokens that mix letters from two or more look-alike-capable scripts, e.g. ('АAPL', ['Cyrillic', 'Latin']).

    A token written entirely in look-alike letters of another script ("ѕсоре" in Cyrillic) is reported too when the text around it is mostly Latin."""
    out = []
    latin = other = 0
    toks = _TOKEN.findall(text)
    for tok in toks:
        if tok.isascii():
            latin += len(tok)
            continue
        scripts = {script_of(c) for c in tok if c.isalpha()}
        scripts.discard("Other")
        if len(scripts & _SPOOF_SCRIPTS) >= 2:
            out.append((tok, sorted(scripts)))
        elif scripts == {"Latin"}:
            latin += len(tok)
        elif scripts:
            other += len(tok)
    if latin and other and latin >= 4 * other:
        seen = {t for t, _ in out}
        for tok in toks:
            if tok in seen or len(tok) < 3:
                continue
            letters = [c for c in tok if c.isalpha()]
            if letters and all(c in CONFUSABLES for c in letters):
                out.append((tok, sorted({script_of(c) for c in letters}) + ["whole-word look-alike"]))
                seen.add(tok)
    return out


def fold_confusables(s: str) -> str:
    """Map look-alike letters to their Latin shapes. Used by the gate to name what the ticker looked like."""
    return "".join(CONFUSABLES.get(c) or LATIN_LOOKALIKES.get(c, c) for c in s)


def non_latin_letters(s: str) -> list[str]:
    return [c for c in s if c.isalpha() and script_of(c) not in ("Latin", "Other")]


# ---- decoders -------------------------------------------------------------------------------------------------------------------

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


def _prose(text: str) -> bool:
    """Is this decoded text plausibly something written for a reader (not a hash, a key or random bytes)?"""
    if len(text) < 6:
        return False
    ok = sum(c.isalnum() or c in " \n\t.,;:'\"!?$%&()/_+@#-" for c in text)
    letters = sum(c.isalpha() or c == " " for c in text)
    return ok >= 0.9 * len(text) and letters >= 0.6 * len(text) and (" " in text or "\n" in text or len(text) >= 12)


def _b64_text(run: str, strict: bool) -> str | None:
    run = run.replace("-", "+").replace("_", "/")
    if len(run.rstrip("=")) % 4 == 1:          # a dangling sextet cannot be decoded; the rest still can
        run = run.rstrip("=")[:-1]
    d = _decode_b64(run)
    if d is None:
        return None
    return d if (not strict or _prose(d)) else None


_LIKE_CHAR = re.compile(r"[0-9+/_]|.[A-Z]")


def _b64_like(piece: str) -> bool:
    core = piece.rstrip("=")
    return _LIKE_CHAR.search(core) is not None and not core.isdigit()


def _chunked_b64(text: str) -> list[tuple[int, int, str, int]]:
    """Base64 split over lines or words ("aWdub3Jl IHByZXZ..."): (start, end, decoded, length) for groups of adjacent base64-looking pieces."""
    out: list[tuple[int, int, str, int]] = []
    if sum(1 for _ in islice(_LIKE_PIECE.finditer(text), 3)) < 3:
        return out
    group: list[re.Match] = []
    pending: list[re.Match] = []        # plain-looking pieces between two base64-looking ones (a short chunk can be all lowercase)

    def flush() -> None:
        if len(group) >= 2:
            for k in range(len(pending), -1, -1):       # the last chunk may be a short plain-looking tail ("MQ==")
                members = group + pending[:k]
                joined = "".join(m.group().rstrip("=") for m in members)
                if len(joined) >= 20 and (d := _b64_text(joined, strict=True)) is not None:
                    out.append((members[0].start(), members[-1].end(), d, len(joined)))
                    break
        group.clear()
        pending.clear()

    prev_end = -1
    for m in _B64_PIECE.finditer(text):
        if (group or pending) and not _B64_GAP.fullmatch(text[prev_end:m.start()]):
            flush()
        if _b64_like(m.group()) and (len(m.group()) >= 4 or group):
            group.extend(pending)
            pending.clear()
            group.append(m)
        elif group and len(pending) < 3:
            pending.append(m)
        else:
            flush()
        prev_end = m.end()
    flush()
    return out


def _bytes_text(raw: bytes) -> str | None:
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return t if _prose(t) else None


def _candidates(text: str) -> list[tuple[int, int, str, str, int]]:
    """Encoded runs in `text`: (start, end, decoded, label, run_length). Overlaps are resolved by the caller."""
    out: list[tuple[int, int, str, str, int]] = []
    for m in _B64X.finditer(text):
        run = m.group()
        urlsafe_only = ("-" in run or "_" in run) and not ("+" in run or "/" in run)
        d = _b64_text(run, strict=len(run.rstrip("=")) < 48 or urlsafe_only)
        if d is not None:
            out.append((m.start(), m.end(), d, "base64", len(run)))
    for s, e, d, n in _chunked_b64(text):
        out.append((s, e, d, "base64", n))
    for rx in ((_HEX, _HEX_SPACED) if any(c in text for c in "abcdefABCDEF") else ()):
        for m in rx.finditer(text):
            try:
                d = _bytes_text(bytes.fromhex(re.sub(r"[ :,-]", "", m.group())))
            except ValueError:
                d = None
            if d is not None:
                out.append((m.start(), m.end(), d, "hex", len(m.group())))
    for m in (_PCT.finditer(text) if text.count("%") >= 6 else ()):
        d = _bytes_text(unquote_to_bytes(m.group()))
        if d is not None:
            out.append((m.start(), m.end(), d, "percent-encoding", len(m.group())))
    for m in (_BSLASH.finditer(text) if "\\" in text else ()):
        try:
            d = "".join(chr(int(h[2:], 16)) for h in re.findall(r"\\x[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}", m.group()))
        except (ValueError, OverflowError):
            continue
        if _prose(d):
            out.append((m.start(), m.end(), d, "escape sequences", len(m.group())))
    for m in (_ENTITY_RUN.finditer(text) if "&#" in text else ()):
        d = html.unescape(m.group())
        if _prose(d):
            out.append((m.start(), m.end(), d, "html entities", len(m.group())))
    return out


class _Budget:
    __slots__ = ("depth", "decoded", "runs", "exhausted")

    def __init__(self) -> None:
        self.depth, self.decoded, self.runs, self.exhausted = 0, 0, 0, False


def _expand_encoded(text: str, findings: list[str], budget: _Budget) -> str:
    cands = _candidates(text)
    if not cands:
        return _reveal_transformed(text, findings)
    cands.sort(key=lambda c: (c[0], -c[1]))
    chosen, last_end = [], -1
    for c in cands:
        if c[0] >= last_end:
            chosen.append(c)
            last_end = c[1]
    parts: list[str] = []
    end = 0
    for start, stop, decoded, label, run_len in chosen:
        if start < end:         # inside an annotation this pass already accepted
            continue
        parts.append(text[end:stop])
        end = stop
        if budget.depth >= _MAX_DEPTH or budget.runs >= _MAX_RUNS or budget.decoded + len(decoded) > _MAX_DECODED:
            if not budget.exhausted:
                budget.exhausted = True
                findings.append("decoding limit: encoded content is nested or repeated beyond what is decoded here; the chunk is treated as hostile")
            continue
        budget.runs += 1
        budget.decoded += len(decoded)
        # Decoding shrinks the input, so cleaning the decoded text also exposes nested runs.
        budget.depth += 1
        try:
            cleaned, decoded_findings = _clean(decoded, budget)
        finally:
            budget.depth -= 1
        annotation = f" [decoded {label}: {cleaned}]"
        if text.startswith(annotation, end):
            end += len(annotation)
            # A matching annotation can come from untrusted input. Still report hidden text in the encoded run.
            findings.extend(severe(decoded_findings))
        else:
            findings.append(f"{label}: a {run_len}-character run decodes to {decoded[:160]!r}")
            findings.extend(decoded_findings)
        parts.append(annotation)
    parts.append(text[end:])
    return _reveal_transformed("".join(parts), findings)


_DIRECTIVE_WORDS = ("ignore", "disregard", "forget", "override", "bypass", "transfer", "wire", "withdraw", "send", "sell ", "system prompt", "new instruction")


def _may_hold_directive(s: str) -> bool:
    low = s.lower()
    return any(w in low for w in _DIRECTIVE_WORDS)


def _reveal_transformed(text: str, findings: list[str]) -> str:
    """ROT13 and reversed text: appended only when the transformed text holds a directive that the plain text does not."""
    if len(text) < 12 or (_may_hold_directive(text) and _DIRECTIVE.search(text)):
        return text           # nothing to look inside, or already readable: the screen sees it as it is
    for label, view in (("ROT13", codecs.encode(text, "rot13")), ("reversed", text[::-1])):
        m = _DIRECTIVE.search(view) if _may_hold_directive(view) else None
        if m:
            lo, hi = max(0, m.start() - 40), min(len(view), m.end() + 80)
            excerpt = "".join(c if c.isprintable() else " " for c in view[lo:hi] if c.isascii() or c == "\n")     # plain ASCII only: stays stable under later passes
            if not _DIRECTIVE.search(excerpt):      # the match leaned on a character that the excerpt drops: do not annotate what a rescan cannot see
                continue
            findings.append(f"{label}: the text reads as a directive when decoded: {excerpt[:160]!r}")
            return f"{text} [decoded {label}: {excerpt}]"
    return text


def _hidden_payloads(text: str) -> list[str]:
    """Text smuggled in the pattern of invisible characters: variation selectors as bytes, zero-width characters as bits."""
    out: list[str] = []
    for m in re.finditer("[︀-️\U000e0100-\U000e01ef]{4,}", text):
        raw = bytes((ord(c) - 0xFE00) if ord(c) <= 0xFE0F else (ord(c) - 0xE0100 + 16) for c in m.group())
        t = raw.decode("ascii", "ignore")
        if len(t) >= 4 and sum(c.isprintable() for c in t) >= 0.9 * len(t):
            out.append(t[:160])
    for m in re.finditer("[​‌‍⁠﻿]{16,}", text):
        run = m.group()
        syms = sorted(set(run))
        if len(syms) != 2:
            continue
        for one in syms:
            bits = "".join("1" if c == one else "0" for c in run)
            raw = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) - 7, 8))
            t = raw.decode("ascii", "ignore")
            if len(t) >= 2 and len(t) == len(raw) and all(c.isprintable() for c in t):
                out.append(t[:160])
                break
    return out


def _fold_marks(text: str, findings: list[str]) -> str:
    """Strip combining marks that NFKC could not compose, from Latin words carrying two or more ("i̇g̈n̈ö̈r̈e"): accents are dropped from the whole word."""
    if not _MARK.search(text):
        return text
    removed = 0

    def fix(m: re.Match) -> str:
        nonlocal removed
        w = m.group()
        n = len(_MARK.findall(w))
        if n >= 2 and all(script_of(c) == "Latin" for c in w if c.isalpha()):
            removed += n
            return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c)))
        return w

    out = _MARKED_WORD.sub(fix, text)
    if removed:
        findings.append(f"combining marks: {removed} stacked combining marks on Latin letters were removed")
    return out


def _clean(text: str, budget: _Budget) -> tuple[str, list[str]]:
    findings: list[str] = []
    if not text:
        return text, findings

    # 0. text that is not text: unpaired surrogates, control characters, page and line separators.
    if not text.isascii() and _SURROGATE.search(text):
        findings.append(f"invalid characters: {len(_SURROGATE.findall(text))} unpaired surrogates replaced")
        text = _SURROGATE.sub("�", text)
    if text.translate(_CTRL_TABLE) != text:
        findings.append(f"control characters: {len(text) - len(text.translate(_CTRL_TABLE))} control characters (NUL, escape or similar) removed")
        text = text.translate(_CTRL_TABLE)
    text = text.translate(_NL_TABLE)
    if not text.isascii():
        text = text.translate(_SPACE_TABLE)

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
            bidi = {c: n for c, n in counts.items() if c in BIDI}
            zw = {c: n for c, n in counts.items() if c not in bidi and c != "\xad"}
            if "\xad" in counts:   # soft hyphens occur in honest typeset text; report, do not treat as an attack
                findings.append(f"soft hyphens: {counts[chr(0xAD)]}; removed")
            if zw:
                desc = ", ".join(f"{n} {ZERO_WIDTH[c]}" for c, n in zw.items())
                payloads = _hidden_payloads(text)
                extra = f"; their pattern spells {payloads[0]!r}" if payloads else ""
                findings.append(f"zero-width characters: {desc}{extra}; removed")
            if bidi:
                desc = ", ".join(f"{n} {ZERO_WIDTH[c]}" for c, n in bidi.items())
                findings.append(f"bidi controls: {desc}; removed")
            text = text.translate(_ZW_TABLE)

        # 3. NFKC, then what NFKC leaves: look-alike Latin letters and stacked combining marks.
        # NFKC maps some modifier letters onto look-alikes and folding can enable a composition, so alternate until stable.
        folded_chars, normalised = [], False
        for _ in range(4):
            if any(c in LATIN_LOOKALIKES for c in text):
                folded_chars += [c for c in dict.fromkeys(text) if c in LATIN_LOOKALIKES]
                text = text.translate(_LOOKALIKE_TABLE)
            nfkc = unicodedata.normalize("NFKC", text)
            if nfkc == text:
                break
            normalised, text = True, nfkc
        if folded_chars:
            findings.append(f"look-alike letters: {''.join(dict.fromkeys(folded_chars))!r} (small capitals or similar) were folded to plain Latin letters")
        if normalised:
            findings.append("nfkc: compatibility characters (fullwidth letters, ligatures or similar) were normalised")
        text = _fold_marks(text, findings)

        # 4. Mixed-script tokens.
        mixed = mixed_script_tokens(text)
        if mixed:
            shown = "; ".join(f"{tok!r} ({'+'.join(s)}, looks like {fold_confusables(tok)!r})" for tok, s in mixed[:5])
            findings.append(f"mixed-script tokens: {shown}")

    # 5. Encoded runs: decode and append so a model screen sees the payload.
    # An annotation can end a run that was hidden behind another ("%65aWdub..."), so expand again until nothing changes.
    for _ in range(4):
        expanded = _expand_encoded(text, findings, budget)
        if expanded == text:
            break
        text = expanded
    return text, list(dict.fromkeys(findings))


def clean(text: str) -> tuple[str, list[str]]:
    """Return (clean_text, findings). Findings are plain sentences; an empty list means nothing was touched.

    Severity is in the first word of each finding: 'tag', 'zero-width', 'bidi', 'mixed-script', 'control', 'combining', 'base64', 'nfkc'.
    Never raises: input that is not a string is read as text (bytes as UTF-8 with replacement), and an internal fault quarantines the chunk.
    """
    if not isinstance(text, str):
        text = text.decode("utf-8", "replace") if isinstance(text, (bytes, bytearray)) else ("" if text is None else str(text))
    try:
        return _clean(text, _Budget())
    except RecursionError:
        return text, ["decoding limit: the text nests encodings too deeply; the chunk is treated as hostile"]
    except Exception as e:      # noqa: BLE001  L1 must never be the thing that crashes an agent turn
        return text, [f"zero-width characters: L1 could not process this text safely ({type(e).__name__}); the chunk is treated as hostile"]


SEVERE = ("tag characters", "zero-width characters", "bidi controls", "mixed-script tokens", "control characters", "combining marks",
          "decoding limit")


def severe(findings: list[str]) -> list[str]:
    """Findings that on their own justify quarantining the chunk without asking a model."""
    return [f for f in findings if f.startswith(SEVERE)]
