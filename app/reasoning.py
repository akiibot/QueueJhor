"""The deterministic investigator.

Every judge-scored field is decided here by explicit rules over the complaint
text AND the transaction history — never by the complaint text alone. This is
the "investigator, not classifier" requirement, and it is what reproduces the
tricky sample cases (established-recipient inconsistency, ambiguous→null,
duplicate→second transaction, the human-review matrix, etc.).
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .extract import Signals, extract_signals, normalize_phone
from .schemas import TicketRequest, TransactionEntry

# Keyword tables. Ordered evaluation in `classify` resolves overlaps
# (e.g. "wrong number ... get my money back" is a wrong_transfer, not a refund).
_PHISHING = (
    "otp", "one time password", "one-time password", "pin code", "password",
    "card number", "cvv", "scam", "phishing", "fraud call", "suspicious call",
    "asked for my", "claiming to be", "claim to be", "pretending", "lottery",
    "you won", "prize", "blocked if", "will be blocked", "verify your account",
    "ওটিপি", "পিন", "পাসওয়ার্ড", "প্রতারক", "প্রতারণা", "ফাঁদ",
)
_DUPLICATE = (
    "twice", "two times", "double", "duplicate", "deducted two", "charged twice",
    "two payments", "দুইবার", "দুবার", "ডাবল",
)
_FAILED = ("failed", "fail hoyeche", "did not go through", "ব্যর্থ", "fail হয়েছে")
_WRONG = (
    "wrong number", "wrong person", "wrong account", "wrong recipient",
    "wrong transfer", "by mistake", "accidentally", "mistakenly",
    "ভুল নম্বর", "ভুল মানুষ", "ভুল",
)
# A transfer was sent but the recipient says it never arrived: also a transfer
# dispute (handled by dispute_resolution), even with no explicit "wrong" word.
_SENT = (
    "sent", "transferred", "send money", "pathiyechi", "পাঠিয়েছি",
    "টাকা পাঠ", "transfer kor",
)
_NOT_RECEIVED = (
    "didn't get", "did not get", "didn't receive", "did not receive",
    "not received", "hasn't received", "haven't received", "did not arrive",
    "never received", "পায়নি", "পাইনি", "আসেনি", "পাইনাই",
)
_AGENT = ("cash in", "cash-in", "cashin", "ক্যাশ ইন", "এজেন্ট", "agent")
_SETTLEMENT = ("settlement", "settle", "settled", "সেটেলমেন্ট", "নিষ্পত্তি")
_REFUND = ("refund", "money back", "return my money", "ফেরত", "টাকা ফেরত")


def _has(text: str, needles) -> bool:
    return any(n in text for n in needles)


def classify(complaint: str, req: TicketRequest, signals: Signals,
             history: List[TransactionEntry]) -> str:
    """First-match-wins classification. Order encodes priority."""
    low = complaint.lower()

    # Safety category first — it is critical and must never be missed.
    if _has(low, _PHISHING):
        return "phishing_or_social_engineering"

    if _has(low, _DUPLICATE) or _has_duplicate_pair(history):
        return "duplicate_payment"

    # A failed payment (esp. with a balance deducted) outranks a generic
    # "refund" mention in the same sentence.
    if _has(low, _FAILED) or _has_failed_payment(history):
        return "payment_failed"

    if _has(low, _WRONG):
        return "wrong_transfer"

    # "I sent money but it wasn't received" + a transfer exists -> transfer dispute.
    if _has(low, _SENT) and _has(low, _NOT_RECEIVED) and _has_type(history, "transfer"):
        return "wrong_transfer"

    is_merchant = (req.user_type or "").lower() == "merchant"
    if _has(low, _SETTLEMENT) or (is_merchant and _has_type(history, "settlement")):
        return "merchant_settlement_delay"

    if _has(low, ("cash in", "cash-in", "ক্যাশ ইন")) or (
        _has(low, ("agent", "এজেন্ট")) and _has_type(history, "cash_in")
    ):
        return "agent_cash_in_issue"

    if _has(low, _REFUND):
        return "refund_request"

    return "other"


# --- history helpers ---------------------------------------------------------

def _has_type(history, t) -> bool:
    return any((e.type or "") == t for e in history)


def _has_failed_payment(history) -> bool:
    return any((e.type or "") == "payment" and (e.status or "") == "failed"
               for e in history)


def _duplicate_pair(history) -> Optional[TransactionEntry]:
    """Return the later transaction of a duplicate group, if one exists."""
    groups: dict = {}
    for e in history:
        if (e.type or "") != "payment" or (e.status or "") != "completed":
            continue
        key = (e.amount, normalize_phone(e.counterparty) or (e.counterparty or ""))
        groups.setdefault(key, []).append(e)
    for members in groups.values():
        if len(members) >= 2:
            members.sort(key=lambda x: x.timestamp or "")
            return members[-1]
    return None


def _has_duplicate_pair(history) -> bool:
    return _duplicate_pair(history) is not None


# --- transaction matching + evidence verdict --------------------------------

@dataclass
class Investigation:
    relevant_transaction_id: Optional[str]
    verdict: str           # consistent | inconsistent | insufficient_data
    matched: Optional[TransactionEntry]
    note: str              # short machine reason, drives reason_codes/text


def _candidates_by_amount(history, signals: Signals, txn_type: Optional[str]):
    pool = [e for e in history if txn_type is None or (e.type or "") == txn_type]
    if signals.amounts:
        amt = [e for e in pool if signals.amount_matches(e.amount)]
        return amt
    return pool


def investigate(case_type: str, signals: Signals,
                history: List[TransactionEntry], complaint: str,
                req: TicketRequest) -> Investigation:
    # Explicit transaction ID named in the complaint always wins.
    if signals.txn_ids:
        for e in history:
            if (e.transaction_id or "").upper() in signals.txn_ids:
                return Investigation(e.transaction_id, "consistent", e, "explicit_id")

    if case_type == "phishing_or_social_engineering":
        # Safety reports are about an external contact, not a ledger entry.
        return Investigation(None, "insufficient_data", None, "safety_report")

    if case_type == "duplicate_payment":
        dup = _duplicate_pair(history)
        if dup is not None:
            return Investigation(dup.transaction_id, "consistent", dup, "duplicate_pair")
        single = _single_match(history, signals, "payment")
        if single:
            return Investigation(single.transaction_id, "insufficient_data", single,
                                 "no_duplicate_found")
        return Investigation(None, "insufficient_data", None, "no_match")

    if case_type == "wrong_transfer":
        return _investigate_transfer(history, signals)

    if case_type == "payment_failed":
        cands = _candidates_by_amount(history, signals, "payment")
        failed = [e for e in cands if (e.status or "") == "failed"]
        pick = (failed or cands)
        if len(pick) >= 1:
            return Investigation(pick[0].transaction_id, "consistent", pick[0],
                                 "payment_failed_match")
        return Investigation(None, "insufficient_data", None, "no_match")

    if case_type == "merchant_settlement_delay":
        m = _single_match(history, signals, "settlement")
        if m:
            return Investigation(m.transaction_id, "consistent", m, "settlement_match")
        return Investigation(None, "insufficient_data", None, "no_match")

    if case_type == "agent_cash_in_issue":
        m = _single_match(history, signals, "cash_in")
        if m:
            return Investigation(m.transaction_id, "consistent", m, "cash_in_match")
        return Investigation(None, "insufficient_data", None, "no_match")

    if case_type == "refund_request":
        m = _single_match(history, signals, "payment")
        if m:
            return Investigation(m.transaction_id, "consistent", m, "refund_match")
        return Investigation(None, "insufficient_data", None, "no_match")

    # other / vague
    return Investigation(None, "insufficient_data", None, "vague")


def _single_match(history, signals, txn_type) -> Optional[TransactionEntry]:
    cands = _candidates_by_amount(history, signals, txn_type)
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1 and signals.phones:
        narrowed = [e for e in cands
                    if normalize_phone(e.counterparty) in signals.phones]
        if len(narrowed) == 1:
            return narrowed[0]
    if not signals.amounts:
        typed = [e for e in history if (e.type or "") == txn_type]
        if len(typed) == 1:
            return typed[0]
    return None


def _investigate_transfer(history, signals: Signals) -> Investigation:
    cands = [e for e in history if (e.type or "") == "transfer"]
    if signals.amounts:
        cands = [e for e in cands if signals.amount_matches(e.amount)]

    # Narrow by recipient phone if the complaint gave one.
    if signals.phones:
        narrowed = [e for e in cands
                    if normalize_phone(e.counterparty) in signals.phones]
        if narrowed:
            cands = narrowed

    if not cands:
        # No amount given but exactly one transfer in history → use it.
        transfers = [e for e in history if (e.type or "") == "transfer"]
        if not signals.amounts and len(transfers) == 1:
            cands = transfers
        else:
            return Investigation(None, "insufficient_data", None, "no_match")

    if len(cands) > 1:
        # Genuinely ambiguous: multiple plausible transfers, nothing to
        # disambiguate. Do not guess — ask the customer.
        return Investigation(None, "insufficient_data", None, "ambiguous_match")

    matched = cands[0]
    # Established-recipient check: repeated prior transfers to the same
    # counterparty contradict a "wrong recipient" claim.
    cp = normalize_phone(matched.counterparty) or (matched.counterparty or "")
    prior = [e for e in history
             if e is not matched
             and (e.type or "") == "transfer"
             and (normalize_phone(e.counterparty) or (e.counterparty or "")) == cp]
    if len(prior) >= 2:
        return Investigation(matched.transaction_id, "inconsistent", matched,
                             "established_recipient")
    return Investigation(matched.transaction_id, "consistent", matched,
                         "transfer_match")


# --- severity / routing / escalation ----------------------------------------

def severity_for(case_type: str, inv: Investigation) -> str:
    if case_type == "phishing_or_social_engineering":
        return "critical"
    if case_type in ("payment_failed", "duplicate_payment", "agent_cash_in_issue"):
        return "high"
    if case_type == "wrong_transfer":
        return "high" if inv.verdict == "consistent" else "medium"
    if case_type == "merchant_settlement_delay":
        return "medium"
    if case_type == "refund_request":
        return "low"
    return "low"


_DEPARTMENT = {
    "wrong_transfer": "dispute_resolution",
    "payment_failed": "payments_ops",
    "duplicate_payment": "payments_ops",
    "refund_request": "customer_support",
    "merchant_settlement_delay": "merchant_operations",
    "agent_cash_in_issue": "agent_operations",
    "phishing_or_social_engineering": "fraud_risk",
    "other": "customer_support",
}


def route(case_type: str) -> str:
    return _DEPARTMENT.get(case_type, "customer_support")


def human_review_required(case_type: str, inv: Investigation) -> bool:
    """Escalate disputes, fraud, and agent issues that we could actually act on.
    When we still need the customer to clarify (no identified transaction), the
    ball is in their court — do not raise a human ticket yet."""
    if case_type == "phishing_or_social_engineering":
        return True
    if case_type in ("wrong_transfer", "duplicate_payment", "agent_cash_in_issue"):
        return inv.relevant_transaction_id is not None
    return False


def confidence_for(case_type: str, inv: Investigation) -> float:
    if case_type == "phishing_or_social_engineering":
        return 0.95
    if inv.note in ("ambiguous_match", "vague", "no_match", "no_duplicate_found"):
        return 0.6
    if inv.verdict == "inconsistent":
        return 0.75
    base = {
        "duplicate_payment": 0.92,
        "merchant_settlement_delay": 0.92,
        "wrong_transfer": 0.9,
        "payment_failed": 0.9,
        "agent_cash_in_issue": 0.88,
        "refund_request": 0.85,
    }
    return base.get(case_type, 0.7)


def reason_codes_for(case_type: str, inv: Investigation) -> List[str]:
    codes = [case_type]
    note_map = {
        "established_recipient": "established_recipient_pattern",
        "ambiguous_match": "ambiguous_match",
        "vague": "needs_clarification",
        "no_match": "no_transaction_match",
        "duplicate_pair": "duplicate_detected",
        "safety_report": "credential_protection",
        "payment_failed_match": "potential_balance_deduction",
        "explicit_id": "transaction_match",
        "transfer_match": "transaction_match",
    }
    if inv.note in note_map:
        codes.append(note_map[inv.note])
    if inv.verdict == "inconsistent":
        codes.append("evidence_inconsistent")
    elif inv.verdict == "insufficient_data" and inv.note not in ("safety_report",):
        codes.append("needs_clarification")
    if human_review_required(case_type, inv):
        codes.append("human_review")
    # De-duplicate while preserving order.
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


@dataclass
class Decision:
    case_type: str
    investigation: Investigation
    severity: str
    department: str
    human_review: bool
    confidence: float
    reason_codes: List[str]
    language: str


def decide(req: TicketRequest) -> Decision:
    complaint = req.complaint or ""
    signals = extract_signals(complaint)
    language = (req.language or signals.language or "en")
    if language not in ("en", "bn", "mixed"):
        language = signals.language
    history = req.transaction_history or []

    case_type = classify(complaint, req, signals, history)
    inv = investigate(case_type, signals, history, complaint, req)
    return Decision(
        case_type=case_type,
        investigation=inv,
        severity=severity_for(case_type, inv),
        department=route(case_type),
        human_review=human_review_required(case_type, inv),
        confidence=confidence_for(case_type, inv),
        reason_codes=reason_codes_for(case_type, inv),
        language=language,
    )
