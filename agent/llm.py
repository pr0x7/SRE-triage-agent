"""
ChatGroq wrapper with automatic retry on tool_use_failed errors.

Groq's Llama models occasionally emit malformed tool calls (XML-style instead of JSON)
which causes Groq's server-side validation to reject them with a 400 tool_use_failed error.
This wrapper catches that specific error and retries with slightly increased temperature
to nudge the model toward a different (hopefully valid) tool call format.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

logger = logging.getLogger(__name__)


class ChatGroqWithRetry(ChatGroq):
    """ChatGroq subclass that retries on tool_use_failed errors.

    Groq validates tool call format server-side. When Llama generates
    malformed XML-style tool calls, the server returns 400 tool_use_failed.
    This subclass catches that and retries up to max_retries times.
    """

    max_tool_retries: int = 4
    """Maximum number of retries on tool_use_failed errors."""

    retry_base_delay: float = 1.0
    """Base delay in seconds between retries (exponential backoff)."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_error = None
        for attempt in range(self.max_tool_retries + 1):
            try:
                return super()._generate(messages, stop, run_manager, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Handle Rate limits dynamically by falling back to llama-3.1-8b-instant or mixtral-8x7b-32768
                if "rate_limit" in error_str.lower() or "429" in error_str or "rate limit" in error_str.lower():
                    last_error = e
                    delay = self.retry_base_delay * (attempt + 1)
                    
                    # Cycle models to find one with quota
                    fallback_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
                    current_model = self.model_name
                    next_model = fallback_models[attempt % len(fallback_models)]
                    
                    if current_model == next_model and len(fallback_models) > 1:
                        next_model = fallback_models[(attempt + 1) % len(fallback_models)]
                        
                    logger.warning(
                        f"Groq Rate Limit on '{current_model}' (attempt {attempt + 1}). "
                        f"Falling back to model '{next_model}' and retrying in {delay:.1f}s..."
                    )
                    self.model_name = next_model
                    time.sleep(delay)
                elif "tool_use_failed" in error_str or "Failed to call a function" in error_str:
                    last_error = e
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        f"Groq tool_use_failed (attempt {attempt + 1}/{self.max_tool_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

                    # Bump temperature slightly on each retry to get different output
                    if "temperature" not in kwargs:
                        kwargs["temperature"] = min(0.3 + (attempt * 0.15), 0.9)
                else:
                    raise

        # All retries exhausted
        raise last_error  # type: ignore[misc]
