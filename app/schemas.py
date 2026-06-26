"""Pydantic models and the exact enum vocabularies from the problem statement.

Input is parsed leniently (unknown/extra context never breaks us); output is
constrained to the exact enum strings the automated judge expects.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# --- Enum vocabularies (must match the spec character-for-character) ---------

LANGUAGES = ("en", "bn", "mixed")
EVIDENCE_VERDICTS = ("consistent", "inconsistent", "insufficient_data")
CASE_TYPES = (
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
)
SEVERITIES = ("low", "medium", "high", "critical")
DEPARTMENTS = (
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
)

EvidenceVerdict = Literal[
    "consistent", "inconsistent", "insufficient_data"
]
CaseType = Literal[
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
]
Severity = Literal["low", "medium", "high", "critical"]
Department = Literal[
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
]


# --- Request models ----------------------------------------------------------

class TransactionEntry(BaseModel):
    """One recent transaction. Parsed leniently — unknown fields are ignored
    and every field is optional so a partial history never 500s the service."""

    model_config = ConfigDict(extra="ignore")

    transaction_id: Optional[str] = None
    timestamp: Optional[str] = None
    type: Optional[str] = None
    amount: Optional[float] = None
    counterparty: Optional[str] = None
    status: Optional[str] = None


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    complaint: str
    language: Optional[str] = None
    channel: Optional[str] = None
    user_type: Optional[str] = None
    campaign_context: Optional[str] = None
    transaction_history: Optional[List[TransactionEntry]] = None
    metadata: Optional[dict] = None


# --- Response model -----------------------------------------------------------

class AnalysisResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: Optional[List[str]] = None
