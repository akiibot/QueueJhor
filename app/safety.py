"""Defense-in-depth safety filter applied to customer-facing text.

The templates in replies.py are already safe. This module is the backstop that
runs on EVERY customer_reply and recommended_next_action regardless of source —
critically, on any text produced by the optional LLM, which could otherwise be
steered by prompt-injection into requesting credentials or promising a refund.

If a violation is detected the offending text is replaced with a guaranteed-safe
fallback rather than risking a -15/-10 penalty.
"""
import re
from typing import Tuple

# Verb ... credential, e.g. "share your OTP", "provide the pin", "enter password".
_CREDENTIAL_REQUEST = re.compile(
    r"(share|provide|send|give|enter|confirm|tell|type|verify\s+with|read\s+out)"
    r"[^.?!]{0,40}\b(pin|otp|password|card\s*number|cvv|one[\s-]*time\s*password)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(not|never|don't|do not|won't|cannot|can't|n't|no)\b",
                       re.IGNORECASE)

# Phrases that promise a financial action we have no authority to confirm.
_REFUND_PROMISE = re.compile(
    r"\b("
    r"we (?:will|'ll|have|are going to|shall)\s+(?:refund|reverse|return|credit|unblock|restore)"
    r"|your (?:refund|money|amount|balance|account) (?:will|has|have|is|are)\s+"
    r"(?:been\s+)?(?:refund|revers|return|credit|unblock|restor)"
    r"|i (?:will|'ll)\s+(?:refund|reverse|unblock)"
    r"|refund (?:has been|is being|will be) (?:processed|issued|completed)"
    r"|account (?:has been|will be) unblock"
    r")",
    re.IGNORECASE,
)

# Steering the customer to a non-official third party.
_THIRD_PARTY = re.compile(
    r"\b(call|contact|whatsapp|message|dial|visit)\b[^.?!]{0,40}"
    r"\b(this number|the number below|\+?\d[\d\s-]{7,}|t\.me/|wa\.me/|bit\.ly)",
    re.IGNORECASE,
)

_SAFE_REPLY = {
    "en": (
        "Thank you for reaching out. Our team will review your case and contact "
        "you only through official support channels. Please do not share your "
        "PIN or OTP with anyone."
    ),
    "bn": (
        "যোগাযোগের জন্য ধন্যবাদ। আমাদের দল আপনার বিষয়টি পর্যালোচনা করে শুধুমাত্র "
        "অফিসিয়াল সাপোর্ট চ্যানেলের মাধ্যমে আপনার সাথে যোগাযোগ করবে। অনুগ্রহ করে "
        "কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
    ),
}
_SAFE_ACTION = (
    "Route to the appropriate team for review. Do not promise any refund, "
    "reversal, or unblock; any eligible amount is handled only through official "
    "channels."
)


def _requests_credentials(text: str) -> bool:
    for m in _CREDENTIAL_REQUEST.finditer(text):
        window = text[max(0, m.start() - 18):m.start()]
        if _NEGATION.search(window):
            continue  # "do not share your PIN" — safe reminder
        return True
    return False


def is_unsafe_reply(text: str) -> bool:
    return (
        _requests_credentials(text)
        or bool(_REFUND_PROMISE.search(text))
        or bool(_THIRD_PARTY.search(text))
    )


def is_unsafe_action(text: str) -> bool:
    return bool(_REFUND_PROMISE.search(text)) or _requests_credentials(text)


def enforce(customer_reply: str, recommended_action: str, language: str
            ) -> Tuple[str, str]:
    """Return safety-guaranteed (customer_reply, recommended_next_action)."""
    lang = "bn" if language == "bn" else "en"
    if is_unsafe_reply(customer_reply or ""):
        customer_reply = _SAFE_REPLY[lang]
    if is_unsafe_action(recommended_action or ""):
        recommended_action = _SAFE_ACTION
    return customer_reply, recommended_action
