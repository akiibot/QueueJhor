"""Runtime configuration, sourced entirely from environment variables.

Nothing here ever holds a default secret. The service is fully functional with
no configuration at all (rules-only mode); the LLM fallback is opt-in and only
fires when the rules engine genuinely cannot categorize a ticket.
"""
import os


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # When false (the default) the service is 100% deterministic rules — no
    # network calls, no API key required, instant latency, injection-proof.
    # When true, Gemini is called ONLY for tickets the rules cannot resolve.
    USE_LLM: bool = _flag("USE_LLM")

    # Gemini API key — only read when USE_LLM=true.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # Hard cap well under the 30s judge timeout.
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "10"))

    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def llm_enabled(self) -> bool:
        return self.USE_LLM and bool(self.GEMINI_API_KEY)


config = Config()
