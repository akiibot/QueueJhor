# QueueJhor

Evidence-grounded support-ops copilot for digital finance — built for the
**SUST CSE Carnival 2026 · Codex Community Hackathon (Online Preliminary)**.

It exposes a small HTTP API that reads one customer complaint **plus that
customer's recent transaction history**, investigates what actually happened,
classifies and routes the case, decides whether a human must review it, and
drafts a **safe** customer reply — one that never asks for a PIN/OTP/password
and never promises a refund it has no authority to confirm.

---

## TL;DR

```bash
# Run locally (Python 3.11+)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Health
curl http://localhost:8000/health        # -> {"status":"ok"}

# Analyze a ticket
curl -X POST http://localhost:8000/analyze-ticket \
  -H 'content-type: application/json' \
  -d '{"ticket_id":"T1","complaint":"I sent 5000 taka to a wrong number.","transaction_history":[{"transaction_id":"TXN-1","type":"transfer","amount":5000,"counterparty":"+8801799999999","status":"completed"}]}'
```

Or with Docker:

```bash
docker build -t queuejhor .
docker run -p 8000:8000 queuejhor
```

---

## API

| Method | Path              | Purpose                                            |
|--------|-------------------|----------------------------------------------------|
| GET    | `/health`         | Returns `{"status":"ok"}` (readiness probe).       |
| POST   | `/analyze-ticket` | Accepts one ticket, returns the structured verdict.|

**HTTP status codes:** `200` success · `400` malformed body (invalid JSON or
missing required fields) · `422` empty/semantically-invalid complaint · `500`
internal error (non-sensitive message, never a stack trace). The process never
crashes on bad input.

Request/response field definitions and enum vocabularies live in
[`app/schemas.py`](app/schemas.py) and match the problem statement exactly.

A worked output for all 10 public sample cases is in
[`sample_output.json`](sample_output.json).

---

## Architecture & AI approach

Two-tier pipeline: **deterministic rules first, Gemini AI only as a last resort.**

```
complaint + transaction_history
        │
        ▼
  extract.py     amounts, phones, txn-ids, time, language (en/bn/mixed, Bangla digits)
        │
        ▼
  reasoning.py   classify → match transaction → evidence_verdict → severity
                 → department → human_review → confidence → reason_codes
                 (100% deterministic — this is the scored core)
        │
        ▼
   Confident result?
   /             \
 YES              NO (vague, ambiguous, unmatched, "other")
  │                │
  │          USE_LLM=true + GEMINI_API_KEY set?
  │           /                    \
  │         YES                     NO
  │          │                      │
  │    ai_fallback.py          rules result
  │    (Gemini, 10s cap)       unchanged
  │          │
  │    safety.py ◄─────────────────┘
  │    (always runs on all text)
  │          │
  ▼          ▼
  structured JSON response
```

### Why rules own the decision

Every field the judge scores
(`relevant_transaction_id`, `evidence_verdict`, `case_type`, `department`,
`severity`, `human_review_required`) is computed by explicit, inspectable rules
over both the complaint **and** the transaction list. This makes the service:

- **deterministic** — same input, same output, no enum/schema drift;
- **fast** — single-digit milliseconds, far under the 30s timeout and the 5s
  full-latency-credit threshold;
- **injection-proof on the core score** — instructions hidden in complaint text
  cannot change a verdict, because the verdict is not produced by a language
  model;
- **dependency-free** — no API key, no network, no model weights required to
  score well.

### Where Gemini helps (and when it's skipped)

When `USE_LLM=true` and `GEMINI_API_KEY` is set, **Gemini is only called for
tickets the rules genuinely could not resolve** — vague complaints, multiple
ambiguous matching transactions, or no matching transaction at all. These are
the cases that would otherwise return a low-value "please clarify" response.

Gemini is **never called** for:
- Cases the rules already handled confidently (clear wrong transfer, obvious
  duplicate, phishing, failed payment with a matching transaction, etc.)
- Phishing reports (injection risk; the rules handle these at `critical` severity)

On any Gemini failure (timeout, quota, bad JSON) the service falls back to the
rule-based response silently — no 500, no degradation.

The `ai_fallback_used` reason code is added when Gemini's answer is applied, so
it's visible in the response.

### The "investigator" logic (highlights)

- **Established-recipient inconsistency** — a "wrong transfer" claim is marked
  `inconsistent` when the history shows repeated prior transfers to the same
  counterparty (SAMPLE-02).
- **Ambiguity → `null`** — when several transactions plausibly match and nothing
  disambiguates them, we return `relevant_transaction_id: null` +
  `insufficient_data` and (with Gemini) try to resolve; without Gemini, we ask
  the customer (SAMPLE-08).
- **Duplicate detection** — two identical completed payments resolve to the
  **later** transaction as the suspected duplicate (SAMPLE-10).
- **Escalation matrix** — `human_review_required` is `true` for phishing, and
  for wrong-transfer / duplicate / agent-cash-in cases **only once a specific
  transaction is identified**.

---

## Safety logic

Safety is enforced in two places so a single mistake cannot leak through:

1. **By construction** — all reply templates already avoid credential requests,
   use "any eligible amount will be returned through official channels" instead
   of promising refunds, and point only to official channels.
2. **Backstop filter** ([`app/safety.py`](app/safety.py)) — runs on every
   `customer_reply` and `recommended_next_action`, including Gemini output. It
   detects and replaces:
   - requests for PIN / OTP / password / card number (while *allowing* the safe
     "do not share your PIN" reminder, via negation-aware matching),
   - promises of a refund / reversal / unblock,
   - redirection to suspicious third parties.

This guarantees the `-15` (credential request) and `-10` (unauthorized refund /
third-party) penalties are not triggered even under prompt-injection attempts.

---

## MODELS

| Model | Where it runs | Why / when |
|-------|---------------|------------|
| **None (rule-based engine)** | In-process, CPU only | **Default.** Powers every scored decision and all safety guardrails. No key, no cost, deterministic, instant. Used for ALL confident cases even when USE_LLM=true. |
| `gemini-2.0-flash` (Google) | Optional remote API call | **Fallback only.** Only when `USE_LLM=true` + `GEMINI_API_KEY` set, AND the rules engine could not confidently categorize the ticket. 10s timeout with rules fallback. Chosen for its free tier and low latency. |

No GPU, no local model weights, no multi-GB downloads. Docker image is a slim
`python:3.11-slim` + pure-Python deps (~200 MB).

---

## Assumptions

- Transaction amounts in the complaint are in BDT and roughly match a history
  entry's `amount`; approximate time references are secondary hints.
- `agent_summary` and `recommended_next_action` are internal (always English);
  only `customer_reply` is localized to the complaint language.
- A complaint may include a phone number that is the *intended* (not actual)
  recipient, so phone matching narrows candidates but amount + type are primary.
- Phishing reports are critical by default and about an external contact, so
  `relevant_transaction_id` is `null` / `insufficient_data`.

## Known limitations

- Classification is keyword-driven; highly indirect phrasing in an unsupported
  dialect may fall to `other` / `insufficient_data` — a deliberately safe
  failure mode. Gemini (when enabled) handles these cases.
- The Gemini fallback requires the team's own API key and network egress from
  the deployment environment. Without it the service uses rules templates.

## Tests

```bash
pip install pytest
python -m pytest -q
```

- `tests/test_samples.py` — functional equivalence on all 10 public cases
  (decision fields + reply safety + Bangla-language check).
- `tests/test_adversarial.py` — health, 400/422/invalid-JSON handling, empty /
  missing fields, prompt-injection, safety-filter behaviour, Bangla parsing.

## Deployment

See [`RUNBOOK.md`](RUNBOOK.md) for live-URL and Docker deployment steps. The
service binds to `0.0.0.0`, needs no login, and requires no environment
variables to run (rules-only mode).

To enable the Gemini fallback on a live deployment, set:
```
USE_LLM=true
GEMINI_API_KEY=<your key>
```
