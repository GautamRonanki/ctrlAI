"""
Centralized LLM wrapper for ctrlAI.
All LLM calls in the project go through this module. Never call the API directly.
Handles: retry with backoff, timeout, logging, token counting.
"""

import json
import time
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from loguru import logger

# Shared usage stats file - readable by both Slack bot and Streamlit
USAGE_STATS_PATH = Path(__file__).parent.parent / "logs" / "llm_usage.json"
USAGE_STATS_PATH.parent.mkdir(exist_ok=True)


def _read_stats() -> dict:
    """Read current stats from shared file."""
    try:
        if USAGE_STATS_PATH.exists():
            return json.loads(USAGE_STATS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
    }


def _write_stats(stats: dict):
    """Write stats to shared file."""
    try:
        USAGE_STATS_PATH.write_text(json.dumps(stats))
    except OSError as e:
        logger.error(f"Failed to write LLM usage stats: {e}")


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
    Call the LLM with logging, token tracking, and error handling.
    Use this for all LLM calls - including inside the orchestrator.
    """
    start = time.time()
    try:
        response = await llm.ainvoke(messages)
        latency = (time.time() - start) * 1000

        # Track usage
        prompt_tokens = 0
        completion_tokens = 0
        usage = getattr(response, "usage_metadata", None)
        if usage:
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

        # Update shared file
        stats = _read_stats()
        stats["total_calls"] += 1
        stats["total_prompt_tokens"] += prompt_tokens
        stats["total_completion_tokens"] += completion_tokens
        _write_stats(stats)

        logger.info(
            f"LLM | {label} | model={llm.model_name} | "
            f"latency={latency:.0f}ms | "
            f"prompt_tokens={prompt_tokens} | completion_tokens={completion_tokens}"
        )
        return response

    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(
            f"LLM ERROR | {label} | {type(e).__name__}: {e} | latency={latency:.0f}ms"
        )
        raise


def get_usage_stats() -> dict:
    """Return cumulative token usage stats. Reads from shared file."""
    stats = _read_stats()
    return {
        "total_calls": stats["total_calls"],
        "total_prompt_tokens": stats["total_prompt_tokens"],
        "total_completion_tokens": stats["total_completion_tokens"],
        "estimated_cost_usd": round(
            (stats["total_prompt_tokens"] * 0.15 / 1_000_000)
            + (stats["total_completion_tokens"] * 0.6 / 1_000_000),
            4,
        ),
    }
