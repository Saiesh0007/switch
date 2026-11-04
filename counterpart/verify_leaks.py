"""After a deal, search everything the other side or a model could have seen for secret material.

Checks the shared deal room, both Negotiator wires, and every prompt ever sent to a model. It uses
each company's limits file only as the list of things that must not appear.

    python -m counterpart.verify_leaks
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

from .config import ROOT, STATE, load_credential, load_rooms
from .playbook import Playbook
from .protocol import parse
from .switch_client import SwitchAgent


def find_secrets(text: str, playbook: Playbook) -> list[str]:
    """Secret strings present in the text: the canary, and each private rationale."""
    secrets = [playbook.canary] + [policy.rationale for policy in playbook.policies.values() if policy.rationale]
    return [secret for secret in secrets if secret and secret in text]


def stray_numbers(posts: list[str]) -> list[str]:
    """Numbers stated in prose that were never formally proposed, which could reveal a limit."""
    tabled = {str(tag.value) for post in posts for tag in parse(post) if tag.value is not None}
    tabled |= {value[:-2] for value in tabled if value.endswith(".0")}
    stray = []
    for post in posts:
        prose = re.sub(r"`[^`]*`", "", post)  # hashes and tags are not prose
        stray += [number for number in re.findall(r"\b\d+(?:\.\d+)?\b", prose) if number not in tabled]
    return stray


def flatten(context: dict, only_senders: set[str] | None = None) -> list[str]:
    posts = []
    for thread in context.get("threads", []):
        for entry in [thread["root"], *thread.get("replies", [])]:
            if entry.get("kind") == "message" and (only_senders is None or entry.get("sender_name") in only_senders):
                posts.append(entry.get("body", ""))
    return posts


async def read_room(agent_name: str, room: str, only_senders: set[str] | None = None) -> list[str]:
    client = SwitchAgent(load_credential(agent_name))
    try:
        return flatten(await client.op("read_context", room_id=load_rooms()[room]), only_senders)
    finally:
        await client.close()


async def run() -> int:
    books = {side: Playbook.load(ROOT / "private" / side / "playbook.yaml") for side in ("acme", "bolt")}
    surfaces: dict[str, str] = {}
    deal_posts = await read_room("clerk", "deal-room")
    surfaces["deal room"] = "\n".join(deal_posts)
    surfaces["acme wire"] = "\n".join(await read_room("acme-negotiator", "acme-wire"))
    surfaces["bolt wire"] = "\n".join(await read_room("bolt-negotiator", "bolt-wire"))
    for path in sorted((STATE / "llm").glob("*.jsonl")) if (STATE / "llm").exists() else []:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        surfaces[f"{path.stem} model prompts ({len(records)})"] = "\n".join(
            record["system"] + record["prompt"] + record["reply"] for record in records
        )

    failures = 0
    for surface, text in surfaces.items():
        found = [secret for book in books.values() for secret in find_secrets(text, book)]
        print(f"  {'LEAK ' if found else 'clean'}  {surface}")
        for secret in found:
            print(f"         {secret}")
        failures += len(found)

    # Only a Negotiator can give away a position. People and the Clerk use numbers freely.
    negotiator_posts = await read_room("clerk", "deal-room", {"acme-negotiator", "bolt-negotiator"})
    stray = stray_numbers(negotiator_posts)
    print(f"  {'WARN ' if stray else 'clean'}  Negotiators state no number outside a formal proposal ({len(negotiator_posts)} posts)")
    if stray:
        print(f"         {sorted(set(stray))}")
        failures += 1

    print()
    print(f"Scanned {sum(len(text) for text in surfaces.values())} characters across {len(surfaces)} surfaces.")
    print(f"RESULT: {'PASS, nothing leaked' if not failures else 'FAIL'}")
    return 1 if failures else 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
