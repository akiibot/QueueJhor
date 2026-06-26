"""FastAPI service exposing GET /health and POST /analyze-ticket.

Error handling follows the spec:
  400 — malformed body (invalid JSON, missing required fields)
  422 — schema valid but semantically invalid (empty complaint)
  500 — internal error, with a non-sensitive message (never a stack trace)
The process must never crash on bad input; handlers below guarantee that.
"""
import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .config import config
from .llm import polish
from .reasoning import decide
from .replies import build_texts
from .safety import enforce
from .schemas import AnalysisResponse, TicketRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("queuestorm")

app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0",
    description="Evidence-grounded support-ops copilot for digital finance.",
)


@app.get("/health")
def health():
    return {"status": "ok"}


def analyze(req: TicketRequest) -> AnalysisResponse:
    """Pure function: TicketRequest -> AnalysisResponse. Easy to unit test."""
    decision = decide(req)
    summary, action, reply = build_texts(decision, req.complaint or "")

    if config.llm_enabled:
        summary, reply = polish(
            req.complaint or "",
            decision.language,
            decision.case_type,
            decision.investigation.verdict,
            summary,
            reply,
        )

    # Safety backstop always runs last, on whatever text we ended up with.
    reply, action = enforce(reply, action, decision.language)

    return AnalysisResponse(
        ticket_id=req.ticket_id,
        relevant_transaction_id=decision.investigation.relevant_transaction_id,
        evidence_verdict=decision.investigation.verdict,
        case_type=decision.case_type,
        severity=decision.severity,
        department=decision.department,
        agent_summary=summary,
        recommended_next_action=action,
        customer_reply=reply,
        human_review_required=decision.human_review,
        confidence=round(decision.confidence, 2),
        reason_codes=decision.reason_codes,
    )


@app.post("/analyze-ticket")
async def analyze_ticket(req: TicketRequest):
    if not (req.complaint or "").strip():
        return _json_error(422, "The 'complaint' field must not be empty.")
    try:
        result = analyze(req)
    except Exception:  # never leak internals; never crash the worker
        logger.exception("analyze failed for ticket_id=%s", req.ticket_id)
        return _json_error(500, "Internal error while analyzing the ticket.")
    body = json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
    return Response(content=body, media_type="application/json; charset=utf-8")


def _json_error(status: int, msg: str) -> Response:
    body = json.dumps({"error": msg}, ensure_ascii=False)
    return Response(content=body, status_code=status,
                    media_type="application/json; charset=utf-8")


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return _json_error(400, "Malformed request: invalid JSON or missing required fields.")


@app.exception_handler(Exception)
async def on_unhandled(request: Request, exc: Exception):
    logger.exception("unhandled error")
    return _json_error(500, "Internal error.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT)
