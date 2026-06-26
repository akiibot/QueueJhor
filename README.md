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
  -d @tests/sample_cases.json   # (send a single case's "input" object)
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

This is a **rules-first hybrid**, deliberately chosen for safety, latency, and
reliability under the automated judge:

```
complaint + transaction_history
        │
        ▼
  extract.py     amounts, phones, txn-ids, time, language (en/bn/mixed, Bangla digits)
        │
        ▼
  reasoning.py   classify → match transaction → evidence_verdict → severity
                 → department → human_review → confidence → reason_codes
        │                       (100% deterministic — this is the scored core)
        ▼
  replies.py     safe agent_summary / next_action / customer_reply (en + bn templates)
        │
        ▼
  llm.py         OPTIONAL polish of summary + reply (off by default)
        │
        ▼
  safety.py      always-on backstop: scrub credential requests & refund promises
        │
        ▼
  structured JSON response
```

**Why rules own the decision.** Every field the judge scores
(`relevant_transaction_id`, `evidence_verdict`, `case_type`, `department`,
`severity`, `human_review_required`) is computed by explicit, inspectable rules
over both the complaint **and** the transaction list. This makes the service:

- **deterministic** — same input, same output, no enum/schema drift;
- **fast** — typically single-digit milliseconds, far under the 30s timeout and
  the 5s full-latency-credit threshold;
- **injection-proof on the core score** — instructions hidden in complaint text
  cannot change a verdict, because the verdict is not produced by a language
  model;
- **dependency-free** — no API key, no network, no model weights required to
  score well.

**Where the optional LLM helps.** If `USE_LLM=true` and `ANTHROPIC_API_KEY` is
set, an LLM only *rephrases* the already-decided `agent_summary` and
`customer_reply` for fluency (useful for nuanced Banglish). It cannot alter the
decision, it runs under an 8s timeout, and **any** failure falls back silently
to the rule-based text. The safety filter then runs on whatever text comes back.

### The "investigator" logic (highlights)

- **Established-recipient inconsistency** — a "wrong transfer" claim is marked
  `inconsistent` when the history shows repeated prior transfers to the same
  counterparty (SAMPLE-02).
- **Ambiguity → `null`** — when several transactions plausibly match and nothing
  disambiguates them, we return `relevant_transaction_id: null` +
  `insufficient_data` and ask the customer, rather than guessing (SAMPLE-08).
- **Duplicate detection** — two identical completed payments to the same
  counterparty resolve to the **later** transaction as the suspected duplicate
  (SAMPLE-10).
- **Escalation matrix** — `human_review_required` is `true` for phishing, and
  for wrong-transfer / duplicate / agent-cash-in cases **only once a specific
  transaction is identified**; clarification-needed cases stay `false`.

---

## Safety logic

Safety is enforced in two places so a single mistake cannot leak through:

1. **By construction** — all reply templates already avoid credential requests,
   use "any eligible amount will be returned through official channels" instead
   of promising refunds, and point only to official channels.
2. **Backstop filter** ([`app/safety.py`](app/safety.py)) — runs on every
   `customer_reply` and `recommended_next_action`, including LLM output. It
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
| **None (rule-based engine)** | In-process, CPU only | **Default.** Powers every scored decision and all safety guardrails. No key, no cost, deterministic, instant. |
| `claude-haiku-4-5` (Anthropic) | Optional remote API call | **Off by default.** Only when `USE_LLM=true` + key set. Rephrases `agent_summary` and `customer_reply` for fluency; never changes the decision; 8s timeout with template fallback. Chosen for low latency/cost so it stays well within the 30s budget. |

No GPU, no local model weights, no multi-GB downloads. Docker image is a slim
`python:3.11-slim` + pure-Python deps.

---

## Assumptions

- Transaction amounts in the complaint are in BDT and roughly match a history
  entry's `amount`; approximate time references ("2pm", "today") are secondary
  hints, not hard requirements.
- `agent_summary` and `recommended_next_action` are internal (English), as in
  the sample pack; only `customer_reply` is localized to the complaint language.
- A complaint may include a phone number that is the *intended* (not actual)
  recipient, so phone matching is used to narrow candidates but amount + type
  remain the primary signal.
- Phishing reports are critical by default and are about an external contact,
  so `relevant_transaction_id` is `null` / `insufficient_data`.

## Known limitations

- Classification is keyword-driven; highly indirect phrasing in a language we
  have fewer keywords for (deep Banglish slang) may fall to `other` /
  `insufficient_data` — a deliberately safe failure mode rather than a wrong
  confident answer.
- Time-of-day matching is coarse (hour-level) and not used to break ties when
  amounts already disambiguate.
- The optional LLM polish requires the team's own Anthropic key and network
  egress; without it the service uses the (already safe) templates.

## Tests

```bash
pip install pytest
python -m pytest -q
```

- `tests/test_samples.py` — functional equivalence on all 10 public cases
  (decision fields + reply safety + Bangla-language check).
- `tests/test_adversarial.py` — health, 400/422/invalid-JSON handling, empty /
  missing fields, prompt-injection, safety-filter behavior, Bangla parsing.

## Deployment

See [`RUNBOOK.md`](RUNBOOK.md) for live-URL and Docker deployment steps. The
service binds to `0.0.0.0`, needs no login, and requires no environment
variables to run.
