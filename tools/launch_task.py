#!/usr/bin/env python3
"""Start a fresh agent-server conversation from a prompt file.

Usage:  launch_task.py <prompt-file> [--title TITLE] [--max-iters N]

Reads the LLM settings from the installed default profile (no credentials are
printed).  Prints the new conversation id and appends it to
/root/brother/native/.delegated_agents (one "id<TAB>title" per line).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000/api/conversations"
PROFILE = Path("/root/.openhands/profiles/default.json")
LEDGER = Path("/root/brother/native/.delegated_agents")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    prompt_file = Path(sys.argv[1])
    if not prompt_file.is_file():
        print(f"FEHLER: {prompt_file} fehlt")
        return 2

    title = None
    max_iters = 400
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--title" and i + 1 < len(args):
            title = args[i + 1]
        elif a == "--max-iters" and i + 1 < len(args):
            max_iters = int(args[i + 1])

    text = prompt_file.read_text()
    prof = json.loads(PROFILE.read_text())
    payload = {
        "workspace": {"working_dir": "/root/brother", "kind": "LocalWorkspace"},
        "initial_message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "agent_settings": {"llm": prof},
        "max_iterations": max_iters,
        "confirmation_policy": {"kind": "NeverConfirm"},
    }
    if title:
        payload["title"] = title

    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:800]}")
        return 1

    cid = body.get("id") or body.get("conversation_id")
    print(f"Conversation gestartet: {cid}")
    print(f"Status: {body.get('execution_status')}")
    if cid:
        with LEDGER.open("a") as fh:
            fh.write(f"{cid}\t{title or prompt_file.name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
