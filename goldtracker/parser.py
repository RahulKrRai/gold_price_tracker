"""Parse weight, purity and form from messy retailer product titles.

Examples it handles:
    "PNG Jewellers 2.5 gram Vedhani Gold Ring 24 kt (995)"      -> 2.5 g, 0.995, ring
    "Kalyan Jewellers 24K Gold Ayodhya Coin -10gm"              -> 10 g, 0.999, coin
    "BHIMA Set Of 2 24K 999 Purity Gold Bar 2g+1g"              -> 3 g, 0.999, bar
    "Muthoot ... Pendant 3 Gram (1gm each x 3 Pcs)"             -> 3 g, 0.999, pendant
    "P.C Chandra Jewellers 22kt(916) ... Coin Cum Pendant - 2 Gram" -> 2 g, 0.916, coin
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A number followed by a gram unit. "g" must not be followed by letters other than the unit
# spellings, so "24kt gold" or "Gold" never match.
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(?:grams?|grm?s?|gms?|g)"
WEIGHT_RE = re.compile(rf"(?<![\d.]){_NUM}\s*{_UNIT}(?![a-z])", re.I)
SUM_RE = re.compile(rf"{_NUM}\s*{_UNIT}(?:\s*\+\s*{_NUM}\s*{_UNIT})+", re.I)
# "2+2 GM", "2 + 1 gm combo": unit only after the last number
SUM_SHARED_UNIT_RE = re.compile(rf"(?<![\d.]){_NUM}((?:\s*\+\s*\d+(?:\.\d+)?)+)\s*{_UNIT}(?![a-z])", re.I)
MG_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:mg|milligrams?)(?![a-z])", re.I)
EACH_RE = re.compile(rf"{_NUM}\s*{_UNIT}\s*each", re.I)
COUNT_RE = re.compile(r"(?:(?:pack|set)\s*of\s*(\d+))|(?:x\s*(\d+)\s*(?:pcs?|pieces?|nos?)?)", re.I)

FINENESS_RE = re.compile(r"(?<![\d.])(999\.9|9999|999|995|916|750|585)(?![\d])")
KARAT_RE = re.compile(r"(?<![\d.])(24|23|22|18|14)\s*(?:k|kt|kts|karat|carat|ct)(?![a-z])", re.I)

FINENESS_TO_PURITY = {"999.9": 0.9999, "9999": 0.9999, "999": 0.999, "995": 0.995, "916": 0.916, "750": 0.75, "585": 0.585}
KARAT_TO_PURITY = {"24": 0.999, "23": 0.958, "22": 0.916, "18": 0.75, "14": 0.585}

EXCLUDE_RE = re.compile(
    r"\b(plated|gold[- ]?plated|gold[- ]?toned|imitation|covering|one gram gold|silver coin|silver bar|brass|"
    r"diamond[- ]studded|studded|necklace|chain|earrings?|silver|artificial|rakhi)\b", re.I)
HALF_RE = re.compile(r"\bhalf\s*(?:a\s*)?(?:grams?|gms?|g)\b", re.I)


@dataclass(frozen=True)
class ParsedTitle:
    weight_g: float | None
    purity: float | None
    form: str
    excluded: bool

    @property
    def fine_grams(self) -> float | None:
        if self.weight_g is None or self.purity is None:
            return None
        return self.weight_g * self.purity


def _strip_parens(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


def _weight_from(text: str) -> float | None:
    m = SUM_RE.search(text)
    if m:
        return round(sum(float(x) for x in WEIGHT_RE.findall(m.group(0))), 4)
    m = SUM_SHARED_UNIT_RE.search(text)
    if m:
        return round(float(m.group(1)) + sum(float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(2))), 4)
    m = MG_RE.search(text)
    if m:
        return round(float(m.group(1)) / 1000, 4)
    m = EACH_RE.search(text)
    if m:
        c = COUNT_RE.search(text)
        if c:
            count = int(c.group(1) or c.group(2))
            return round(float(m.group(1)) * count, 4)
    found = WEIGHT_RE.findall(text)
    if found:
        return float(found[0])
    if HALF_RE.search(text):  # "Gold coin of 0.5 / Half Grams"
        return 0.5
    return None


def parse_weight(title: str) -> float | None:
    """Total gold weight in grams, or None if the title doesn't say."""
    t = title.replace(",", " ")
    # Prefer what's outside parentheses: "3 gram (2 Gm + 1 Gm)" -> 3
    outer = _weight_from(_strip_parens(t))
    if outer is not None:
        return outer
    return _weight_from(t)


def parse_purity(title: str) -> float | None:
    """Purity as a fraction (0.999, 0.995, 0.916 ...). Explicit fineness beats karat."""
    m = FINENESS_RE.search(title)
    if m:
        return FINENESS_TO_PURITY[m.group(1)]
    m = KARAT_RE.search(title)
    if m:
        return KARAT_TO_PURITY[m.group(1)]
    return None


def parse_form(title: str) -> str:
    t = title.lower()
    if re.search(r"\b(bar|biscuit)\b", t):
        return "bar"
    if re.search(r"\bcoins?\b", t):
        return "coin"
    if re.search(r"\bpendants?\b", t):
        return "pendant"
    if re.search(r"\b(ring|vedhani)\b", t):
        return "ring"
    return "other"


def parse_title(title: str) -> ParsedTitle:
    return ParsedTitle(
        weight_g=parse_weight(title),
        purity=parse_purity(title),
        form=parse_form(title),
        excluded=bool(EXCLUDE_RE.search(title)),
    )
