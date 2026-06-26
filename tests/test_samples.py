"""Functional-equivalence tests against the 10 public sample cases.

We assert the judge-scored decision fields match the expected output, and that
every customer_reply is safe. Text wording is intentionally NOT asserted
verbatim (the spec says other valid responses exist).
"""
import json
import os

import pytest

from app.main import analyze
from app.safety import is_unsafe_reply
from app.schemas import TicketRequest

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "sample_cases.json"), encoding="utf-8") as fh:
    CASES = json.load(fh)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sample_case_decision(case):
    req = TicketRequest(**case["input"])
    out = analyze(req)
    exp = case["expected_output"]

    assert out.ticket_id == exp["ticket_id"]
    assert out.relevant_transaction_id == exp["relevant_transaction_id"]
    assert out.evidence_verdict == exp["evidence_verdict"]
    assert out.case_type == exp["case_type"]
    assert out.department == exp["department"]
    assert out.severity == exp["severity"]
    assert out.human_review_required == exp["human_review_required"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sample_reply_is_safe(case):
    req = TicketRequest(**case["input"])
    out = analyze(req)
    assert not is_unsafe_reply(out.customer_reply)
    # Bangla input must get a Bangla reply.
    if case["input"].get("language") == "bn":
        assert any("ঀ" <= ch <= "৿" for ch in out.customer_reply)
