"""Generate the three human-facing text fields from a Decision.

`agent_summary` and `recommended_next_action` are internal (always English, as
in the sample pack). `customer_reply` is localized to the complaint language and
written to satisfy every safety rule by construction:
  * never requests PIN/OTP/password/card,
  * never promises a refund/reversal it cannot authorize,
  * directs only to official channels.
"""
from typing import Optional

from .reasoning import Decision
from .schemas import TransactionEntry

# Credential-safety reminder appended to customer replies, per language.
_PIN_REMINDER = {
    "en": "Please do not share your PIN or OTP with anyone.",
    "bn": "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।",
}


def _reminder(lang: str) -> str:
    return _PIN_REMINDER["bn"] if lang == "bn" else _PIN_REMINDER["en"]


def _amount_str(matched: Optional[TransactionEntry], decision: Decision) -> str:
    if matched and matched.amount is not None:
        amt = matched.amount
    else:
        amts = []  # fall back to any extracted amount
        from .extract import extract_signals
        amts = extract_signals(decision_complaint(decision)).amounts
        amt = amts[0] if amts else None
    if amt is None:
        return "the disputed amount"
    if float(amt).is_integer():
        return f"{int(amt)} BDT"
    return f"{amt} BDT"


# `Decision` does not carry the raw complaint; the caller passes it in.
_COMPLAINT_HOLDER: dict = {}


def decision_complaint(decision: Decision) -> str:
    return _COMPLAINT_HOLDER.get(id(decision), "")


def build_texts(decision: Decision, complaint: str):
    _COMPLAINT_HOLDER[id(decision)] = complaint
    try:
        return _build(decision)
    finally:
        _COMPLAINT_HOLDER.pop(id(decision), None)


def _build(decision: Decision):
    case = decision.case_type
    inv = decision.investigation
    matched = inv.matched
    txn_id = inv.relevant_transaction_id
    lang = decision.language
    amount = _amount_str(matched, decision)
    cp = matched.counterparty if matched and matched.counterparty else "the recipient"
    reminder = _reminder(lang)

    summary, action, reply_en, reply_bn = _CASE_BUILDERS[case](
        txn_id, amount, cp, inv.verdict, reminder
    )
    reply = reply_bn if lang == "bn" else reply_en
    return summary, action, reply


def _wrong_transfer(txn_id, amount, cp, verdict, reminder):
    if txn_id is None:
        summary = (
            f"Customer reports a {amount} transfer was not received, but multiple "
            "transactions of that amount exist and the correct one cannot be "
            "determined without more detail."
        )
        action = (
            "Reply to the customer asking for the recipient's number to identify "
            "the correct transaction. Do not initiate a dispute until confirmed."
        )
        reply_en = (
            f"Thank you for reaching out. We see multiple transactions of {amount} "
            "around that time. Could you share the recipient's number so we can "
            f"identify the right transaction? {reminder}"
        )
        reply_bn = (
            f"আপনার সাথে যোগাযোগের জন্য ধন্যবাদ। ওই সময়ে {amount} এর একাধিক লেনদেন "
            "আমরা দেখতে পাচ্ছি। সঠিক লেনদেনটি চিহ্নিত করতে অনুগ্রহ করে প্রাপকের "
            f"নম্বরটি জানান। {reminder}"
        )
        return summary, action, reply_en, reply_bn

    if verdict == "inconsistent":
        summary = (
            f"Customer claims {txn_id} ({amount} to {cp}) was a wrong transfer, but "
            "transaction history shows prior transfers to the same counterparty, "
            "suggesting an established recipient."
        )
        action = (
            "Flag for human review. Verify with the customer whether this was "
            "genuinely a wrong transfer given the established pattern with this "
            "recipient."
        )
    else:
        summary = (
            f"Customer reports sending {amount} via {txn_id} to {cp}, which they now "
            "believe was the wrong recipient."
        )
        action = (
            f"Verify {txn_id} details with the customer and initiate the "
            "wrong-transfer dispute workflow per policy."
        )
    reply_en = (
        f"We have noted your concern about transaction {txn_id}. {reminder} Our "
        "dispute team will review the case and contact you through official "
        "support channels."
    )
    reply_bn = (
        f"আপনার লেনদেন {txn_id} এর বিষয়ে আমরা অবগত হয়েছি। {reminder} আমাদের ডিসপিউট "
        "দল বিষয়টি পর্যালোচনা করে অফিসিয়াল চ্যানেলে আপনার সাথে যোগাযোগ করবে।"
    )
    return summary, action, reply_en, reply_bn


def _payment_failed(txn_id, amount, cp, verdict, reminder):
    ref = txn_id or "the reported payment"
    summary = (
        f"Customer attempted a {amount} payment ({ref}) which failed but reports "
        "the balance was deducted. Requires payments operations investigation."
    )
    action = (
        f"Investigate {ref} ledger status. If balance was deducted on a failed "
        "payment, initiate the automatic reversal flow within standard SLA."
    )
    reply_en = (
        f"We have noted that transaction {ref} may have caused an unexpected "
        "balance deduction. Our payments team will review the case and any "
        f"eligible amount will be returned through official channels. {reminder}"
    )
    reply_bn = (
        f"লেনদেন {ref} এর কারণে অপ্রত্যাশিত ব্যালেন্স কর্তন হয়ে থাকতে পারে বলে আমরা "
        "অবগত হয়েছি। আমাদের পেমেন্টস দল বিষয়টি পর্যালোচনা করবে এবং নিয়ম অনুযায়ী "
        f"প্রযোজ্য কোনো অর্থ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে। {reminder}"
    )
    return summary, action, reply_en, reply_bn


def _refund_request(txn_id, amount, cp, verdict, reminder):
    ref = txn_id or "the reported payment"
    summary = (
        f"Customer requests a refund of {amount} for {ref} (merchant payment). "
        "Not a service failure."
    )
    action = (
        "Inform the customer that refund eligibility depends on the merchant's own "
        "policy. Provide guidance on contacting the merchant directly."
    )
    reply_en = (
        "Thank you for reaching out. Refunds for completed merchant payments "
        "depend on the merchant's own policy. We recommend contacting the "
        "merchant directly. If you need help reaching them, please reply and we "
        f"will guide you. {reminder}"
    )
    reply_bn = (
        "যোগাযোগের জন্য ধন্যবাদ। সম্পন্ন হওয়া মার্চেন্ট পেমেন্টের রিফান্ড মার্চেন্টের "
        "নিজস্ব নীতির উপর নির্ভর করে। আমরা সরাসরি মার্চেন্টের সাথে যোগাযোগের পরামর্শ "
        "দিচ্ছি। তাদের সাথে যোগাযোগে সাহায্য প্রয়োজন হলে অনুগ্রহ করে জানান। "
        f"{reminder}"
    )
    return summary, action, reply_en, reply_bn


def _duplicate_payment(txn_id, amount, cp, verdict, reminder):
    ref = txn_id or "the reported payment"
    summary = (
        f"Customer reports a duplicate payment. Two identical {amount} payments to "
        f"{cp} were completed close together; {ref} is likely the duplicate."
    )
    action = (
        f"Verify the duplicate with payments_ops. If the biller confirms only one "
        f"payment was received, initiate reversal of {ref}."
    )
    reply_en = (
        f"We have noted the possible duplicate payment for transaction {ref}. Our "
        "payments team will verify with the biller and any eligible amount will be "
        f"returned through official channels. {reminder}"
    )
    reply_bn = (
        f"লেনদেন {ref} এর জন্য সম্ভাব্য ডুপ্লিকেট পেমেন্টের বিষয়ে আমরা অবগত হয়েছি। "
        "আমাদের পেমেন্টস দল বিলারের সাথে যাচাই করবে এবং প্রযোজ্য কোনো অর্থ অফিসিয়াল "
        f"চ্যানেলে ফেরত দেওয়া হবে। {reminder}"
    )
    return summary, action, reply_en, reply_bn


def _merchant_settlement(txn_id, amount, cp, verdict, reminder):
    ref = txn_id or "the reported settlement"
    summary = (
        f"Merchant reports {amount} settlement ({ref}) delayed beyond the expected "
        "window. Settlement status is pending."
    )
    action = (
        "Route to merchant_operations to verify the settlement batch status and "
        "communicate a revised ETA if the batch is delayed."
    )
    reply_en = (
        f"We have noted your concern about settlement {ref}. Our merchant "
        "operations team will check the batch status and update you on the "
        "expected settlement time through official channels."
    )
    reply_bn = (
        f"সেটেলমেন্ট {ref} সম্পর্কিত আপনার উদ্বেগ আমরা অবগত হয়েছি। আমাদের মার্চেন্ট "
        "অপারেশন্স দল ব্যাচ স্ট্যাটাস যাচাই করে প্রত্যাশিত সেটেলমেন্ট সময় অফিসিয়াল "
        "চ্যানেলে আপনাকে জানাবে।"
    )
    return summary, action, reply_en, reply_bn


def _agent_cash_in(txn_id, amount, cp, verdict, reminder):
    ref = txn_id or "the reported cash-in"
    summary = (
        f"Customer reports {amount} cash-in via {cp} ({ref}) not reflected in "
        "balance. Transaction status is pending."
    )
    action = (
        f"Investigate {ref} pending status with agent operations. Confirm "
        "settlement state and resolve within the standard cash-in SLA."
    )
    reply_en = (
        f"We have noted your concern about transaction {ref}. Our agent operations "
        "team will verify it promptly and update you through official channels. "
        f"{reminder}"
    )
    reply_bn = (
        f"আপনার লেনদেন {ref} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স দল "
        "এটি দ্রুত যাচাই করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
        f"{reminder}"
    )
    return summary, action, reply_en, reply_bn


def _phishing(txn_id, amount, cp, verdict, reminder):
    summary = (
        "Customer reports an unsolicited contact claiming to be from the company "
        "and asking for credentials. Likely social engineering attempt."
    )
    action = (
        "Escalate to fraud_risk immediately. Confirm the company never asks for "
        "OTP. Log the reported source for fraud pattern analysis."
    )
    reply_en = (
        "Thank you for reaching out before sharing any information. We never ask "
        "for your PIN, OTP, or password under any circumstances. Please do not "
        "share these with anyone, even if they claim to be from us. Our fraud team "
        "has been notified of this incident."
    )
    reply_bn = (
        "কোনো তথ্য শেয়ার করার আগে আমাদের সাথে যোগাযোগ করার জন্য ধন্যবাদ। আমরা কখনোই "
        "আপনার পিন, ওটিপি বা পাসওয়ার্ড চাই না। কেউ আমাদের নাম বললেও এগুলো কারো সাথে "
        "শেয়ার করবেন না। আমাদের ফ্রড দলকে এই ঘটনাটি জানানো হয়েছে।"
    )
    return summary, action, reply_en, reply_bn


def _other(txn_id, amount, cp, verdict, reminder):
    summary = (
        "Customer reports a vague concern without specifying transaction, amount, "
        "or issue. Insufficient detail to identify any relevant transaction."
    )
    action = (
        "Reply to the customer asking for specific details: which transaction, "
        "what amount, what went wrong, and approximate time."
    )
    reply_en = (
        "Thank you for reaching out. To help you faster, please share the "
        "transaction ID, the amount involved, and a short description of what went "
        f"wrong. {reminder}"
    )
    reply_bn = (
        "যোগাযোগের জন্য ধন্যবাদ। আপনাকে দ্রুত সাহায্য করতে অনুগ্রহ করে লেনদেন আইডি, "
        "সংশ্লিষ্ট পরিমাণ এবং কী সমস্যা হয়েছে তার সংক্ষিপ্ত বিবরণ জানান। "
        f"{reminder}"
    )
    return summary, action, reply_en, reply_bn


_CASE_BUILDERS = {
    "wrong_transfer": _wrong_transfer,
    "payment_failed": _payment_failed,
    "refund_request": _refund_request,
    "duplicate_payment": _duplicate_payment,
    "merchant_settlement_delay": _merchant_settlement,
    "agent_cash_in_issue": _agent_cash_in,
    "phishing_or_social_engineering": _phishing,
    "other": _other,
}
