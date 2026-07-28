#!/usr/bin/env python3
"""Run sleep consolidation with Claude as the summarizer.

The local MiniCPM5-1B GGUF is unusably slow on Trevor's CPU -- a single
39-item group ran past 45 minutes without emitting one episodic summary,
burning ~95 CPU-minutes. This routes summarization and fact extraction
through the Anthropic API instead, via mnemosyne's own host-backend
registry (mnemosyne/core/llm_backends.py).

Deliberately not the MNEMOSYNE_LLM_BASE_URL path: _call_remote_llm POSTs
OpenAI-shaped JSON to {base_url}/chat/completions, which is not the
Messages API shape, so that route would need a translating gateway.

Invoked by entrypoint.sh's sleep-loop mode. Also runnable by hand:

    ANTHROPIC_API_KEY=... MNEMOSYNE_HOST_LLM_ENABLED=true \
      python /data/claude_sleep.py [--reclaim-now]

Env (all read at import time by mnemosyne.core.local_llm, so they must be
set on the command line -- exporting them afterwards has no effect):

    MNEMOSYNE_HOST_LLM_ENABLED  must be true, or this exits
    MNEMOSYNE_HOST_LLM_MODEL    model id (default: claude-opus-5)
    MNEMOSYNE_HOST_LLM_TIMEOUT  per-call timeout, seconds (default 15,
                                floored to MIN_TIMEOUT_SECONDS below)
"""

import os
import sys

import anthropic

from mnemosyne.core.llm_backends import CallableLLMBackend, set_host_llm_backend

DEFAULT_MODEL = "claude-opus-5"
MIN_TIMEOUT_SECONDS = 120.0

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def _model_id(override=None):
    return override or os.environ.get("MNEMOSYNE_HOST_LLM_MODEL") or DEFAULT_MODEL


def complete(prompt, *, max_tokens, temperature, timeout, provider=None, model=None):
    """Host-backend adapter: prompt in, text-or-None out.

    Signature is fixed by CallableLLMBackend.complete (llm_backends.py:60).

    `temperature` is accepted and deliberately NOT forwarded: sampling
    parameters were removed on Claude Opus 5 and a request carrying
    temperature/top_p/top_k is rejected with a 400. mnemosyne passes one
    because the local GGUF path needs it; dropping it here is the whole
    reason this adapter exists rather than a generic passthrough.

    Returning None is the failure contract -- _try_host_llm() reads it as
    "attempted but empty" and, per its precedence rule, falls through to
    the local GGUF. That fallback is why main() preflights the API: an
    unattended loop that silently degrades to the GGUF would grind for
    hours per cycle instead of failing fast.
    """
    # MNEMOSYNE_HOST_LLM_TIMEOUT defaults to 15s (local_llm.py:57) -- sized for
    # a host-local aux client, not a remote API call. Thinking is on by
    # default on Claude Opus 5, so a summarization call exceeds it. Floor it;
    # an explicitly raised env var still wins.
    timeout = max(timeout, MIN_TIMEOUT_SECONDS)

    try:
        response = _client.with_options(timeout=timeout).messages.create(
            model=_model_id(model),
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
    reclaim_now = "--reclaim-now" in sys.argv[1:]

    if os.environ.get("MNEMOSYNE_HOST_LLM_ENABLED", "").lower() not in ("1", "true", "yes"):
        sys.exit(
            "MNEMOSYNE_HOST_LLM_ENABLED must be true on the command line.\n"
            "It is read at import time, so exporting it later has no effect."
        )

    # Preflight: a metadata GET, so it costs no tokens. Catches a missing or
    # revoked key, a blocked egress path, and an unavailable model before we
    # claim any rows -- all cases where proceeding would fall through to the
    # GGUF and grind. Fail fast instead; the loop retries next cycle.
    model = _model_id()
    try:
        _client.models.retrieve(model)
    except Exception as exc:
        sys.exit(f"preflight failed for {model} ({type(exc).__name__}): {exc}")

    set_host_llm_backend(CallableLLMBackend(name="anthropic", func=complete))

    from mnemosyne.core import local_llm
    from mnemosyne.core.memory import reclaim_orphans, sleep_all_sessions

    if not local_llm.llm_available():
        sys.exit("llm_available() is False -- the host backend did not register.")

    print(f"Summarizing via {model}\n", flush=True)

    # Default to the 1-hour staleness guard so a scheduled run can never
    # steal a claim from a concurrent sleep. --reclaim-now drops it to 0 for
    # interactive cleanup after an interrupted run, which is only safe when
    # you have confirmed nothing else is sleeping.
    stale_after = 0 if reclaim_now else 3600
    print("reclaim:", reclaim_orphans(stale_after_seconds=stale_after), "\n", flush=True)
    print("sleep:", sleep_all_sessions(), flush=True)


if __name__ == "__main__":
    main()
