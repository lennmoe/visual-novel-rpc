from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_ROMAN = "IVXLCDM"


@dataclass
class Rule:
    name: str                 # rule id, e.g. "chapter"
    pattern: str              # regex, matched case-insensitively against the remainder
    label: str                # str.format template using named groups n / label
    section_type: str         # coarse category exposed to the UI / config

    _compiled: re.Pattern | None = None

    def match(self, text: str) -> "TitleInfo | None":
        if self._compiled is None:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)
        m = self._compiled.search(text)
        if not m:
            return None
        raw = {k: v for k, v in m.groupdict().items() if v}
        # allow rules to use alternate capture groups (n/n2, label/label2)
        n_value = raw.get("n") or raw.get("n2") or ""
        label_value = raw.get("label") or raw.get("label2") or ""
        groups: dict[str, Any] = dict(raw)
        groups["n"] = _normalize_ordinal(n_value)
        groups["label"] = _titlecase(label_value.strip(" -:,"))
        try:
            text_out = self.label.format(**{k: groups.get(k, "") for k in _fields(self.label)})
        except (KeyError, IndexError):
            text_out = m.group(0)
        return TitleInfo(
            section_type=self.section_type,
            section_label=_squash(text_out),
            rule=self.name,
            matched=m.group(0).strip(),
        )


@dataclass
class TitleInfo:
    section_type: str = ""     # "prologue" | "chapter" | "route" | "ending" | "free" | ""
    section_label: str = ""    # display string, e.g. "Chapter 4 — Yumiko Route"
    rule: str = ""             # which rule produced it ("" / "fallback" / "none")
    matched: str = ""          # the raw substring that matched

    @property
    def is_empty(self) -> bool:
        return not self.section_label


# Order matters: more specific patterns come first.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("prologue", r"\b(prologue|prolog|プロローグ|序章|序幕)\b", "Prologue", "prologue"),
    Rule("epilogue", r"\b(epilogue|epilog|エピローグ|終章)\b", "Epilogue", "ending"),
    Rule("opening", r"\b(opening|intro(?:duction)?|オープニング|導入)\b", "Opening", "prologue"),
    Rule(
        "route",
        r"\b(?P<label>[\w'’\. ]+?)\s*(?:route|ルート|편|線|の物語)\b"
        r"|\b(?:route|arc|path)\s*[:\-]?\s*(?P<label2>[\w'’\. ]+)",
        "{label} Route",
        "route",
    ),
    Rule(
        # a route/character name preceding the chapter, e.g. "Kokoro, Chapter 1"
        "chapter_named",
        r"(?P<label>[^,]+?)\s*,\s*(?:chapter|chapitre|chap\.?|ch\.?|episode|épisode|ep\.?|act|acte|scene|"
        r"sc[eè]ne|part|partie|volume|vol\.?)\s*(?P<n>[0-9]{1,3}|[" + _ROMAN + r"]{1,7})\b",
        "{label} — Chapter {n}",
        "chapter",
    ),
    Rule(
        "chapter",
        r"\b(?:chapter|chapitre|chap\.?|ch\.?|episode|épisode|ep\.?|act|acte|scene|"
        r"sc[eè]ne|part|partie|volume|vol\.?)\s*(?P<n>[0-9]{1,3}|[" + _ROMAN + r"]{1,7})\b"
        r"|第\s*(?P<n2>[0-9一二三四五六七八九十百]+)\s*[章話幕節]",
        "Chapter {n}",
        "chapter",
    ),
    Rule("common", r"\b(common route|common|共通(?:ルート)?|共通線)\b", "Common Route", "route"),
    Rule("true", r"\b(true route|true end(?:ing)?|グランドルート|真ルート)\b", "True Route", "route"),
    Rule("ending", r"\b(?P<label>good|bad|normal|happy|true|grand|harem)\s+end(?:ing)?\b", "{label} Ending", "ending"),
    Rule("ending2", r"\b(ending|end|エンディング|エンド)\b", "Ending", "ending"),
    Rule("day", r"\b(?:day|jour|days?)\s*(?P<n>[0-9]{1,3})\b|(?P<n2>[0-9]{1,3})\s*日目", "Day {n}", "chapter"),
    Rule("hen", r"(?P<label>[\w'’぀-ヿ一-鿿]+?)\s*編\b", "{label} Arc", "route"),
    Rule("tilde", r"[～~]\s*(?P<label>.+?)\s*[～~]", "{label}", "free"),
)

_FIELD_RE = re.compile(r"\{(\w+)\}")


def _fields(template: str) -> Iterable[str]:
    return _FIELD_RE.findall(template)


def build_rules(extra: list[dict[str, Any]] | None) -> list[Rule]:
    """Merge user rules from config in front of the defaults."""
    rules: list[Rule] = []
    for item in extra or []:
        try:
            rule = Rule(
                name=item.get("name", "user"),
                pattern=item["pattern"],
                label=item.get("label", "{label}"),
                section_type=item.get("section_type", "free"),
            )
            re.compile(rule.pattern)  # reject a broken regex now, not on every title
        except (KeyError, TypeError, AttributeError, re.error):
            continue  # hand-edited config: skip anything malformed
        rules.append(rule)
    rules.extend(DEFAULT_RULES)
    return rules


def _flex_pattern(name: str) -> str:
    """A regex that matches ``name`` with any run of spaces/punctuation between tokens."""
    collapsed = re.sub(r"[\s\W_]+", " ", name or "").strip().lower()
    if not collapsed:
        return ""
    return re.escape(collapsed).replace(r"\ ", r"[\s\W_]+")


def strip_game_name(title: str, game_name: str) -> str:
    """Remove the game name (and common separators) from either end of the title."""
    remainder = title.strip()
    if game_name:
        # try the full name first, then subtitle-trimmed variants
        variants = [game_name]
        for sep in (":", " - ", "~", "～"):
            if sep in game_name:
                variants.append(game_name.split(sep)[0])
        seen: set[str] = set()
        for variant in sorted(variants, key=len, reverse=True):
            pat = _flex_pattern(variant)
            if not pat or pat in seen:
                continue
            seen.add(pat)
            m = re.search(pat, remainder.lower(), re.IGNORECASE)
            if m:
                remainder = remainder[: m.start()] + " " + remainder[m.end():]
                break
    remainder = re.sub(r"\s{2,}", " ", remainder)
    # NB: brackets are deliberately not stripped here — they're often real content
    # (e.g. a trailing "[2/3]" part counter), not leftover punctuation. Genuinely
    # empty bracket pairs are already cleaned upstream by engines.clean_title.
    return remainder.strip(" -–—|:：·•　")


_VERSION_RE = re.compile(r"\bv?\d+[.;]\d+(?:[.;]\d+)*[a-z]?\b", re.IGNORECASE)
_EMPTY_BRACKETS_RE = re.compile(r"[\[(（【]\s*[\])）】]")


def parse(title: str, game_name: str = "", rules: list[Rule] | None = None) -> TitleInfo:
    rules = rules or list(DEFAULT_RULES)
    remainder = strip_game_name(title, game_name)
    remainder = _VERSION_RE.sub(" ", remainder)
    remainder = _EMPTY_BRACKETS_RE.sub("", remainder)  # e.g. "[1.05]" -> "[]" once the number is gone
    remainder = _squash(remainder).strip(" -–—|:：·•　")
    if not remainder:
        return TitleInfo(rule="none")
    for rule in rules:
        info = rule.match(remainder)
        if info and info.section_label:
            return info
    # nothing structural matched: if there's leftover text distinct from the game
    # name, surface it verbatim (this is what the user's per-VN scripts did).
    if remainder and _loose(remainder) != _loose(game_name):
        return TitleInfo(section_type="free", section_label=_squash(_titlecase(remainder)), rule="fallback", matched=remainder)
    return TitleInfo(rule="none")


def _loose(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def _titlecase(text: str) -> str:
    if not text:
        return ""
    if text.isupper() or text.islower():
        return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))
    return text


def _squash(text: str) -> str:
    return re.sub(r"\s{2,}", " ", (text or "")).strip(" -–—")


_ROMAN_MAP = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_KANJI_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _normalize_ordinal(token: str) -> str:
    if not token:
        return ""
    token = token.strip()
    if token.isdigit():
        return token
    if all(c in _ROMAN_MAP for c in token.upper()):
        return str(_roman_to_int(token.upper()))
    if any(c in _KANJI_MAP or c == "十" or c == "百" for c in token):
        return str(_kanji_to_int(token))
    return token


def _roman_to_int(s: str) -> int:
    total = 0
    prev = 0
    for ch in reversed(s):
        val = _ROMAN_MAP.get(ch, 0)
        total += -val if val < prev else val
        prev = max(prev, val)
    return total


def _kanji_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    total, section, number = 0, 0, 0
    for ch in s:
        if ch in _KANJI_MAP:
            number = _KANJI_MAP[ch]
        elif ch == "十":
            section += (number or 1) * 10
            number = 0
        elif ch == "百":
            section += (number or 1) * 100
            number = 0
        else:
            number = 0
    return total + section + number
