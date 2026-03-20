"""
Centralized LLM wrapper for ctrlAI.
All LLM calls in the project go through this module. Never call the API directly.
Handles: retry with backoff, timeout, logging, token counting.
"""

import time
from typing import Any

from langchain_openai import ChatOpenAI
from loguru import logger

# Token usage tracking
_total_prompt_tokens = 0
_total_completion_tokens = 0
_total_calls = 0


def get_llm(
    model: str = "gpt-4o-mini",
    temperature: float = 0,
    max_tokens: int = 4096,
    max_retries: int = 3,
    timeout: float = 30.0,
) -> ChatOpenAI:
    """Get a configured LLM instance. Use this everywhere."""
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        request_timeout=timeout,
    )


async def call_llm(
    llm: ChatOpenAI,
    messages: list,
    label: str = "unnamed",
) -> Any:
    """
    Call the LLM with logging and error handling.
    Use this for direct calls outside of LangGraph tool calling.
    """
    global _total_prompt_tokens, _total_completion_tokens, _total_calls

    start = time.time()
    try:
        response = await llm.ainvoke(messages)
        latency = (time.time() - start) * 1000

        # Track usage if available
        usage = getattr(response, "usage_metadata", None)
        if usage:
            _total_prompt_tokens += usage.get("input_tokens", 0)
            _total_completion_tokens += usage.get("output_tokens", 0)

        _total_calls += 1

        logger.info(
            f"LLM | {label} | model={llm.model_name} | "
            f"latency={latency:.0f}ms | "
            f"tokens={usage if usage else 'N/A'}"
        )
        return response

    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(f"LLM ERROR | {label} | {type(e).__name__}: {e} | latency={latency:.0f}ms")
        raise


def get_usage_stats() -> dict:
    """Return cumulative token usage stats."""
    return {
        "total_calls": _total_calls,
        "total_prompt_tokens": _total_prompt_tokens,
        "total_completion_tokens": _total_completion_tokens,
        "estimated_cost_usd": round(
            (_total_prompt_tokens * 0.15 / 1_000_000)
            + (_total_completion_tokens * 0.6 / 1_000_000),
            4,
        ),
    }
