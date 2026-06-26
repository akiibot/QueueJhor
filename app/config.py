"""Runtime configuration, sourced entirely from environment variables.

Nothing here ever holds a default secret. The service is fully functional with
no configuration at all (rules-only mode); the LLM polish layer is opt-in.
"""
import os


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # When false (the default) the service is 100% deterministic rules — no
    # network calls, no API key required, instant latency, injection-proof.
    USE_LLM: bool = _flag("USE_LLM")

    # Optional polish provider. Only read if USE_LLM is true AND a key is set.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

    # Hard cap well under the 30s judge timeout so a slow LLM never sinks us.
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "8"))

    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def llm_enabled(self) -> bool:
        return self.USE_LLM and bool(self.ANTHROPIC_API_KEY)


config = Config()
