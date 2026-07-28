#!/usr/bin/env python3
"""One-off: run sleep consolidation with Claude as the summarizer.

The local MiniCPM5-1B GGUF is unusably slow on Trevor's CPU -- a single
39-item group ran >45 minutes without producing one episodic summary. This
script routes summarization AND fact extraction through the Anthropic API
instead, using mnemosyne's own host-backend registry
(mnemosyne/core/llm_backends.py) rather than the OpenAI-shaped
MNEMOSYNE_LLM_BASE_URL path, which expects /chat/completions and does not
match the Messages API shape.

Usage (inside the mnemosyne-sleep container, as the mnemosyne user):

    pip install anthropic
    ANTHROPIC_API_KEY=... \
    MNEMOSYNE_HOST_LLM_ENABLED=true \
    MNEMOSYNE_DATA_DIR=/data \
      python /data/claude_sleep.py

Optional:
    MNEMOSYNE_HOST_LLM_MODEL   model id (default: claude-opus-5)
    MNEMOSYNE_HOST_LLM_TIMEOUT per-call timeout in seconds (default: 15)

Both env vars are read at import time by mnemosyne.core.local_llm, so they
must be set on the command line -- setting them after import has no effect.
"""

import os
import sys

import anthropic

from mnemosyne.core.llm_backends import CallableLLMBackend, set_host_llm_backend

DEFAULT_MODEL = "claude-opus-5"

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def complete(prompt, *, max_tokens, temperature, timeout, provider=None, model=None):
    """Host-backend adapter: prompt in, text-or-None out.

    Signature is fixed by CallableLLMBackend.complete (llm_backends.py:60).

    `temperature` is accepted and deliberately NOT forwarded: sampling
    parameters were removed on Claude Opus 5 and a request carrying
    temperature/top_p/top_k is rejected with a 400. mnemosyne passes one
    because the local GGUF path needs it; dropping it here is the whole
    reason this adapter exists rather than a generic passthrough.

    Returning None on failure is the contract -- _try_host_llm() treats it
    as "attempted but empty" and falls through to the local GGUF.
    """
    try:
        response = _client.with_options(timeout=timeout).messages.create(
            model=model or os.environ.get("MNEMOSYNE_HOST_LLM_MODEL") or DEFAULT_MODEL,
            max_tokens=max_tokens,
            # Summarizing a handful of memories into 1-3 sentences is not a
            # reasoning-heavy task; low effort keeps latency and cost down
            # without measurably hurting summary quality.
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"  [claude] call failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return None

    # Safety classifiers can decline with a normal HTTP 200 and an empty or
    # partial content list. Check stop_reason before indexing into content.
    if response.stop_reason == "refusal":
        print("  [claude] request declined by safety classifiers", file=sys.stderr)
        return None

    return next((b.text for b in response.content if b.type == "text"), None)


def main():
    if os.environ.get("MNEMOSYNE_HOST_LLM_ENABLED", "").lower() not in ("1", "true", "yes"):
        sys.exit(
            "MNEMOSYNE_HOST_LLM_ENABLED must be true on the command line.\n"
            "It is read at import time, so exporting it later has no effect."
        )

    set_host_llm_backend(CallableLLMBackend(name="anthropic", func=complete))

    from mnemosyne.core import local_llm
    from mnemosyne.core.memory import reclaim_orphans, sleep_all_sessions

    if not local_llm.llm_available():
        sys.exit("llm_available() is False -- the host backend did not register.")

    model = os.environ.get("MNEMOSYNE_HOST_LLM_MODEL") or DEFAULT_MODEL
    print(f"Summarizing via {model}\n", flush=True)

    # stale_after_seconds=0 also frees claims left by an interrupted run.
    # Safe only because nothing else is sleeping concurrently -- check that
    # the sleep-loop (PID 1) is parked in `sleep` before running this.
    print("reclaim:", reclaim_orphans(stale_after_seconds=0), "\n", flush=True)
    print("sleep:", sleep_all_sessions(), flush=True)


if __name__ == "__main__":
    main()
