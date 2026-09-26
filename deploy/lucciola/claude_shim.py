#!/usr/bin/env python3
"""claude-shim: the Anthropic Messages API, answered by headless Claude Code.

mnemosyne's sleep container talks to the Anthropic SDK (claude_sleep.py).
Pointing its ANTHROPIC_BASE_URL here moves consolidation from the paid API
onto D's Claude subscription via `claude -p` on lucciola, with no change to
mnemosyne's code. It implements only what claude_sleep.py uses:

  GET  /v1/models/{id}   the preflight (answered locally, costs nothing)
  POST /v1/messages      one user message in, one text block out

Anything else is a 404. Auth: the x-api-key header must equal CLAUDE_SHIM_TOKEN
(the container's ANTHROPIC_API_KEY is set to that token, not a real key).
Calls run one at a time, in an empty directory, with no tools, so CLAUDE.md,
hooks and MCP servers stay out of the summaries. Sampling params and
output_config are ignored.

Rollback: point the sleep container's ANTHROPIC_API_KEY back at the real key
and drop ANTHROPIC_BASE_URL; everything else stays as it was.
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ["CLAUDE_SHIM_TOKEN"]
PORT = int(os.environ.get("CLAUDE_SHIM_PORT", "8765"))
CLAUDE = str(Path.home() / ".local/bin/claude")
WORKDIR = Path.home() / ".local/share/claude-shim"
TIMEOUT = 600
LOCK = threading.Lock()
# The subscription, never the API: an ANTHROPIC_API_KEY in the environment
# would make `claude` bill the API instead.
CHILD_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ANTHROPIC_API_KEY", "CLAUDE_SHIM_TOKEN", "API_TOKEN", "TUNNEL_TOKEN")}


def alias(model):
    for name in ("opus", "sonnet", "haiku"):
        if name in (model or ""):
            return name
    return "opus"


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code, kind, msg):
        self._send(code, {"type": "error", "error": {"type": kind, "message": msg}})

    def _authed(self):
        if self.headers.get("x-api-key") != TOKEN:
            self._error(401, "authentication_error", "bad x-api-key")
            return False
        return True

    def do_GET(self):
        if not self._authed():
            return
        path = self.path.split("?")[0]
        if path.startswith("/v1/models/"):
            mid = path.rsplit("/", 1)[1]
            self._send(200, {"type": "model", "id": mid, "display_name": mid,
                             "created_at": "2026-01-01T00:00:00Z"})
        else:
            self._error(404, "not_found_error", path)

    def do_POST(self):
        if not self._authed():
            return
        if self.path.split("?")[0] != "/v1/messages":
            self._error(404, "not_found_error", self.path)
            return
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        parts = [text_of(m["content"]) for m in req.get("messages", []) if m.get("role") == "user"]
        prompt = "\n\n".join(parts)
        if req.get("system"):
            prompt = text_of(req["system"]) + "\n\n" + prompt
        model = req.get("model", "")
        t0 = time.time()
        with LOCK:
            p = subprocess.run(
                [CLAUDE, "-p", "--model", alias(model), "--output-format", "json"],
                input=prompt, cwd=WORKDIR, capture_output=True, text=True, timeout=TIMEOUT,
                env=CHILD_ENV)
        try:
            out = json.loads(p.stdout)
            if out.get("is_error"):
                raise ValueError(out.get("result"))
        except Exception as e:
            print(f"claude -p failed ({p.returncode}): {e} {p.stderr[-300:]}", flush=True)
            self._error(529, "overloaded_error", f"claude -p failed: {e}")
            return
        print(f"ok {alias(model)} {len(prompt)} chars in, {len(out.get('result') or '')} out, "
              f"{time.time() - t0:.0f}s", flush=True)
        self._send(200, {
            "id": "msg_shim_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant",
            "model": model, "content": [{"type": "text", "text": out.get("result") or ""}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    WORKDIR.mkdir(parents=True, exist_ok=True)
    print(f"claude-shim on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
