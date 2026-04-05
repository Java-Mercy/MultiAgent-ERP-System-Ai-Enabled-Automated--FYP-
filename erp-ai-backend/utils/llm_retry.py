"""
Groq / LLM invocation with a single retry on timeout (SRS error recovery).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class GroqUnavailableError(Exception):
    """Raised when Groq remains unavailable after retries."""


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return True
    if "readtimeout" in name or "connecttimeout" in name:
        return True
    return False


def invoke_groq(llm: Any, messages: list, *, max_attempts: int = 2) -> Any:
    """
    Invoke llm.invoke(messages), retry once on timeout-like failures.
    After exhausting attempts on timeouts, raises GroqUnavailableError.
    """
    for attempt in range(max_attempts):
        try:
            return llm.invoke(messages)
        except Exception as e:
            if _is_timeout_error(e):
                if attempt < max_attempts - 1:
                    logger.warning(
                        "Groq invoke timed out (attempt %s/%s), retrying once …",
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(0.4)
                    continue
                logger.error("Groq unavailable after retry: %s", e)
                raise GroqUnavailableError(
                    "AI service temporarily unavailable"
                ) from e
            raise
    raise GroqUnavailableError("AI service temporarily unavailable")
