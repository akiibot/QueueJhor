"""Extract structured signals from free-text complaints.

Handles English, Bangla (incl. Bangla digits ০-৯), and mixed Banglish. The goal
is to pull out the few facts the matcher needs — amounts, phone numbers,
explicitly named transaction IDs, and rough time hints — without ever trusting
instructions embedded in the text (prompt-injection is treated as plain data).
"""
import re
from dataclasses import dataclass, field
from typing import List

_BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

_TXN_ID_RE = re.compile(r"\bTXN-\d+\b", re.IGNORECASE)
# Bangladeshi mobile numbers in various shapes: +8801XXXXXXXXX / 8801... / 01...
_PHONE_RE = re.compile(r"(?:\+?88)?0?1[3-9]\d{8}")
_TIME_RE = re.compile(r"\b(\d{1,2})\s*(?::\d{2})?\s*([ap])\.?m\.?", re.IGNORECASE)
# A plausible money amount: 1-7 digits, optional thousands separators / decimals.
_AMOUNT_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{1,7}(?:\.\d+)?\b")


def normalize_digits(text: str) -> str:
    return text.translate(_BENGALI_DIGITS)


def detect_language(text: str) -> str:
    has_bn = any("ঀ" <= ch <= "৿" for ch in text)
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_bn and has_latin:
        return "mixed"
    if has_bn:
        return "bn"
    return "en"


def normalize_phone(value: str) -> str:
    """Reduce any phone-ish string to its last 10 digits for comparison."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", normalize_digits(value))
    return digits[-10:] if len(digits) >= 10 else digits


@dataclass
class Signals:
    language: str
    amounts: List[float] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    txn_ids: List[str] = field(default_factory=list)
    hours: List[int] = field(default_factory=list)
    mentions_today: bool = False
    mentions_yesterday: bool = False

    def amount_matches(self, amount) -> bool:
        if amount is None:
            return False
        return any(abs(float(amount) - a) < 0.01 for a in self.amounts)


def _extract_hours(text: str) -> List[int]:
    hours = []
    for raw_h, ap in _TIME_RE.findall(text):
        try:
            h = int(raw_h) % 12
        except ValueError:
            continue
        if ap.lower() == "p":
            h += 12
        hours.append(h)
    return hours


def extract_signals(complaint: str) -> Signals:
    raw = complaint or ""
    text = normalize_digits(raw)

    txn_ids = [m.upper() for m in _TXN_ID_RE.findall(text)]
    hours = _extract_hours(text)

    # Strip tokens that would otherwise be mis-read as money amounts, in order:
    # transaction IDs, phone numbers, then "2pm"-style time references.
    scrubbed = _TXN_ID_RE.sub(" ", text)
    phones = [normalize_phone(p) for p in _PHONE_RE.findall(scrubbed)]
    scrubbed = _PHONE_RE.sub(" ", scrubbed)
    scrubbed = _TIME_RE.sub(" ", scrubbed)

    amounts: List[float] = []
    for token in _AMOUNT_RE.findall(scrubbed):
        cleaned = token.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        # Ignore lone tiny integers and 4-digit year-like values that are
        # almost never the disputed amount.
        if value <= 0:
            continue
        amounts.append(value)

    low = text.lower()
    return Signals(
        language=detect_language(raw),
        amounts=amounts,
        phones=[p for p in phones if p],
        txn_ids=txn_ids,
        hours=hours,
        mentions_today="today" in low or "আজ" in raw,
        mentions_yesterday="yesterday" in low or "গতকাল" in raw or "কাল" in raw,
    )
