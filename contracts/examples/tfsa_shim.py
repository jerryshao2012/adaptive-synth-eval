#!/usr/bin/env python3
"""Payload bridge between the eval harness and the TFSA AgentCore endpoint.

The harness POSTs {conversation_id, session_id, turn_id, user_message, query, ...}
and reads the reply from "response"/"answer"/"text". The TFSA agent instead wants
{"prompt": "..."} and returns whatever tfsa_agentcore.py emits. This shim sits in
between: it forwards the user's turn as {"prompt": ...} to the agent and re-wraps
the agent's reply as {"response": <text>}.

    Real agent:   localhost:8080/invocations   (your tfsa_agentcore)
    This shim:    localhost:8081/invocations   (point CHATBOT_ENDPOINT here)

Run it alongside the agent, no extra deps (stdlib only):

    python contracts/unified/tfsa_shim.py
    # or:  TFSA_UPSTREAM=http://localhost:8080/invocations SHIM_PORT=8081 python ...
"""
from __future__ import annotations

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.getenv("TFSA_UPSTREAM", "http://localhost:8080/invocations")
PORT = int(os.getenv("SHIM_PORT", "8081"))

# Keys the agent's reply might use, in priority order.
_REPLY_KEYS = ("response", "answer", "result", "output", "completion", "content", "text", "message")


def _extract_text(body: object) -> str:
    """Best-effort: pull a string answer out of whatever AgentCore returned."""
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return "\n".join(_extract_text(item) for item in body)
    if isinstance(body, dict):
        for key in _REPLY_KEYS:
            if body.get(key) is not None:
                return _extract_text(body[key])
        return json.dumps(body)  # unknown shape — hand the judge the raw JSON
    return "" if body is None else str(body)


def _forward(prompt: str) -> str:
    req = urllib.request.Request(
        UPSTREAM,
        data=json.dumps({"prompt": prompt}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    try:
        return _extract_text(json.loads(raw))
    except json.JSONDecodeError:
        return raw  # agent returned plain text


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        prompt = payload.get("query") or payload.get("user_message") or payload.get("prompt") or ""

        try:
            text = _forward(prompt)
            out, status = {"response": text}, 200
        except Exception as exc:  # surface upstream failures to the harness
            out, status = {"response": "", "error": f"{type(exc).__name__}: {exc}"}, 502

        body = json.dumps(out).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # quiet the per-request stderr spam
        pass


if __name__ == "__main__":
    print(f"TFSA shim: :{PORT}/invocations  ->  {UPSTREAM}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
