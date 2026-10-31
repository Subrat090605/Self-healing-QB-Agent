"""llm.py — Groq LLM wrapper with retry, rate-limiting, chaos mode, and usage tracking.

All LLM calls in the project MUST go through chat() or json_chat() here.
See SPEC §3b and CLAUDE.md for constraints.
"""

import json
import os
import random
import threading
import time
from collections import deque
from typing import Any

from groq import Groq, APIStatusError, APIConnectionError, APITimeoutError

from src.config import GROQ_API_KEY, CHAOS_MODE

# -- Client ---------------------------------------------------------------------
_client = Groq(api_key=GROQ_API_KEY, timeout=30.0)

# -- Usage counter (thread-safe) ------------------------------------------------

class _Usage:
    """Simple thread-safe counters exposed as llm.usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion

    def reset(self) -> None:
        with self._lock:
            self.calls = 0
            self.prompt_tokens = 0
            self.completion_tokens = 0

    def __repr__(self) -> str:
        return (
            f"Usage(calls={self.calls}, "
            f"prompt_tokens={self.prompt_tokens}, "
            f"completion_tokens={self.completion_tokens})"
        )


usage = _Usage()


# -- Rate limiter (~25 RPM + token budget per minute) ---------------------------

class _RateLimiter:
    """Sliding-window rate limiter: max RPM requests per minute."""

    def __init__(self, rpm: int = 25, tpm: int = 60_000) -> None:
        self._rpm = rpm
        self._tpm = tpm
        self._lock = threading.Lock()
        self._req_times: deque[float] = deque()
        self._token_times: deque[tuple[float, int]] = deque()   # (ts, tokens)

    def _evict(self, now: float) -> None:
        """Remove entries older than 60 s."""
        cutoff = now - 60.0
        while self._req_times and self._req_times[0] < cutoff:
            self._req_times.popleft()
        while self._token_times and self._token_times[0][0] < cutoff:
            self._token_times.popleft()

    def wait(self, estimated_tokens: int = 500) -> None:
        """Block until both RPM and TPM windows have capacity."""
        while True:
            with self._lock:
                now = time.time()
                self._evict(now)
                tokens_used = sum(t for _, t in self._token_times)
                if (
                    len(self._req_times) < self._rpm
                    and tokens_used + estimated_tokens <= self._tpm
                ):
                    self._req_times.append(now)
                    self._token_times.append((now, estimated_tokens))
                    return
            time.sleep(0.5)

    def record_tokens(self, actual_tokens: int, estimated_tokens: int = 500) -> None:
        """Correct the estimate with actual token count."""
        with self._lock:
            if actual_tokens > estimated_tokens:
                self._token_times.append((time.time(), actual_tokens - estimated_tokens))


_limiter = _RateLimiter(rpm=25, tpm=int(os.getenv("GROQ_TPM", "60000")))


# -- Chaos mode -----------------------------------------------------------------

def _maybe_chaos() -> None:
    """If CHAOS_MODE is enabled, raise 30 % of the time to simulate failures."""
    if CHAOS_MODE and random.random() < 0.30:
        raise APIConnectionError(request=None)  # type: ignore[arg-type]


# -- Core chat -----------------------------------------------------------------

def chat(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call the Groq chat completion API with retry and backoff.

    Args:
        model:       Model name from config (ORCH_MODEL, SOLVER_MODEL, FAST_MODEL).
        system:      System prompt text.
        messages:    List of {"role": ..., "content": ...} dicts (OpenAI format).
                     Tool results use role="tool" with tool_call_id.
        tools:       Optional list of OpenAI-format tool definitions.
        temperature: Sampling temperature (= 0.1 per SPEC §3b).

    Returns:
        The raw Groq response message dict (includes tool_calls if any).

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    temperature = max(0.1, temperature)
    full_messages = [{"role": "system", "content": system}] + messages

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    max_retries = 3
    backoff = 1.0
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            _maybe_chaos()
            _limiter.wait()
            resp = _client.chat.completions.create(**kwargs)

            # Record usage
            u = resp.usage
            if u:
                usage.add(u.prompt_tokens, u.completion_tokens)
                _limiter.record_tokens(u.total_tokens)

            msg = resp.choices[0].message
            return _message_to_dict(msg)

        except APIStatusError as exc:
            last_exc = exc
            status = exc.status_code

            if status == 429:
                # Honour Retry-After header if present
                retry_after = float(exc.response.headers.get("retry-after", backoff * 2))
                time.sleep(retry_after)
                backoff = retry_after
                continue

            if status == 400 and attempt == 0:
                # Malformed tool call — retry once with explicit instruction
                messages = messages + [
                    {
                        "role": "user",
                        "content": "Call exactly one tool with valid JSON arguments.",
                    }
                ]
                full_messages = [{"role": "system", "content": system}] + messages
                kwargs["messages"] = full_messages
                continue

            # Other 4xx / 5xx — backoff and retry
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

        except (APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    raise RuntimeError(
        f"LLM call failed after {max_retries} attempts. Last error: {last_exc}"
    )


def json_chat(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call Groq with JSON response_format and parse the result.

    The system or user prompt MUST contain the word "JSON" (Groq requirement).

    Args:
        model:       Model name.
        system:      System prompt (should mention JSON output).
        user:        User message.
        temperature: Sampling temperature.

    Returns:
        Parsed JSON dict from the model response.

    Raises:
        ValueError: If the response is not valid JSON after retries.
        RuntimeError: If LLM call fails.
    """
    # Ensure "JSON" appears in the user message (Groq requirement for json_object)
    if "JSON" not in user and "JSON" not in system:
        user = user + "\n\nRespond with valid JSON only."

    temperature = max(0.1, temperature)
    full_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    max_retries = 3
    backoff = 1.0
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            _maybe_chaos()
            _limiter.wait()
            resp = _client.chat.completions.create(
                model=model,
                messages=full_messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            u = resp.usage
            if u:
                usage.add(u.prompt_tokens, u.completion_tokens)
                _limiter.record_tokens(u.total_tokens)

            content = resp.choices[0].message.content or ""
            return json.loads(content)

        except json.JSONDecodeError as exc:
            last_exc = exc  # type: ignore[assignment]
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

        except APIStatusError as exc:
            last_exc = exc  # type: ignore[assignment]
            if exc.status_code == 429:
                retry_after = float(exc.response.headers.get("retry-after", backoff * 2))
                time.sleep(retry_after)
                backoff = retry_after
            else:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        except (APIConnectionError, APITimeoutError) as exc:
            last_exc = exc  # type: ignore[assignment]
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    raise RuntimeError(
        f"json_chat failed after {max_retries} attempts. Last error: {last_exc}"
    )


# -- Message serialisation helper ----------------------------------------------

def _message_to_dict(msg: Any) -> dict[str, Any]:
    """Convert a Groq ChatCompletionMessage object to a plain dict."""
    d: dict[str, Any] = {
        "role": msg.role,
        "content": msg.content or "",
    }
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d
