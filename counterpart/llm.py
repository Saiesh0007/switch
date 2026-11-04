"""The model layer. Used only by Negotiators, only to write prose from public facts.

Tags, not prose, carry the terms, and a model has no tools, so bad output cannot change a deal.
Every prompt is logged, so anyone can audit exactly what each model was ever shown.

COUNTERPART_LLM selects the backend:
  anthropic   Anthropic SDK, needs ANTHROPIC_API_KEY.
  claude-cli  The local `claude` command, using whatever account it is signed in to.
  offline     Fixed sentences. No account needed, and the deal still completes.
  auto        (default) anthropic if a key is set, else claude-cli if installed, else offline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time

from .config import STATE

log = logging.getLogger(__name__)

MODEL = os.environ.get("COUNTERPART_MODEL", "claude-opus-5-5")
LOGS = STATE / "llm"


def backend() -> str:
    choice = os.environ.get("COUNTERPART_LLM", "auto")
    if choice != "auto":
        return choice
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "claude-cli" if shutil.which("claude") else "offline"


def _call_anthropic(system: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model refused")
    return "".join(block.text for block in response.content if block.type == "text")


def _call_claude_cli(system: str, prompt: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_AGENT"))}
    command = [
        shutil.which("claude") or "claude",
        "-p",
        "--output-format",
        "text",
        "--tools",
        "",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--system-prompt",
        system,
    ]
    if os.environ.get("COUNTERPART_CLAUDE_MODEL"):
        command += ["--model", os.environ["COUNTERPART_CLAUDE_MODEL"]]
    with tempfile.TemporaryDirectory() as empty:  # nothing nearby for it to read
        done = subprocess.run(
            command, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=90, cwd=empty, env=env
        )
    if done.returncode != 0:
        raise RuntimeError(f"claude exited {done.returncode}: {done.stderr[:200]}")
    return done.stdout


def only_allowed_numbers(text: str, allowed: set[str]) -> bool:
    """Reject prose that states a number we did not give it, such as an invented concession."""
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    return all(number in allowed for number in numbers)


async def write(agent: str, system: str, prompt: str, fallback: str, allowed_numbers: set[str]) -> str:
    """Return model prose if it is usable, otherwise the fallback. Never blocks the deal."""
    which = backend()
    started = time.time()
    text = fallback
    outcome = "offline"
    if which != "offline":
        call = _call_anthropic if which == "anthropic" else _call_claude_cli
        try:
            reply = (await asyncio.to_thread(call, system, prompt)).strip()
            if not reply:
                outcome = "empty, used fallback"
            elif not only_allowed_numbers(reply, allowed_numbers):
                outcome = "stated an unapproved number, used fallback"
            else:
                text, outcome = reply, "model"
        except Exception as exc:  # any model failure must not stop a negotiation
            log.warning("%s: model call failed: %s", agent, exc)
            outcome = f"failed, used fallback: {type(exc).__name__}"
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / f"{agent}.jsonl").open("a", encoding="utf-8") as handle:
        record = {
            "time": started,
            "backend": which,
            "system": system,
            "prompt": prompt,
            "reply": text,
            "outcome": outcome,
        }
        handle.write(json.dumps(record) + "\n")
    return text
