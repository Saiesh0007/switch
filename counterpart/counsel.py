"""Counsel: holds the company's limits and enforces them with plain code. It contains no AI.

It accepts only exact tags from its own Negotiator, sends back only verdicts, and asks the General
Counsel when a decision is beyond its authority. Only the General Counsel's verified account can
give that authority, and every decision is written to a log in the chamber.

    python -m counterpart.counsel acme
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .clauses import CLAUSES, describe, parse_value, show
from .config import ROOT, load_credential, load_rooms
from .playbook import ACCEPT, ASK_ACCEPT, ASK_OFFER, COUNTER, HOLD, Playbook
from .protocol import parse, render
from .switch_client import Message, SwitchAgent

log = logging.getLogger("counsel")

COMMAND = re.compile(r"^\s*(approve|decline|counter)\s+([a-z_]+)(?:\s+(.{1,24}?))?\s*$", re.IGNORECASE)
HUMAN_PREFIX = "@switch-mattermost-"


@dataclass
class Pending:
    action: str
    value: float | str
    their_value: float | str


class Counsel:
    def __init__(self, side: str, playbook: Playbook):
        self.side = side
        self.playbook = playbook
        self.name = f"{side}-counsel"
        self.negotiator = f"{side}-negotiator"
        self.client = SwitchAgent(load_credential(self.name))
        rooms = load_rooms()
        self.wire = rooms[f"{side}-wire"]
        self.chamber = rooms[f"{side}-chamber"]
        self.pending: dict[str, Pending] = {}
        self.authority_id = ""
        self.ledger: list[str] = []

    async def resolve_authority(self) -> None:
        """Pin the exact identity allowed to sign off. A lookalike username will not match."""
        bridges = await self.client.op("list_bridges")
        bridge = (bridges[0] if isinstance(bridges, list) else bridges["bridges"][0])
        bridge_id = bridge.get("id") or bridge.get("bridge_id")
        self.authority_id = f"{HUMAN_PREFIX}{bridge_id}-{self.playbook.authority}:localhost"

    def is_authority(self, message: Message) -> bool:
        return message.sender == self.authority_id

    def record(self, entry: str) -> None:
        self.ledger.append(f"- {time.strftime('%Y-%m-%d %H:%M:%S')} {entry}")

    async def verdict(self, clause: str, value: float | str, action: str) -> None:
        await self.client.post(self.wire, render("VERDICT", clause, value, action))

    async def on_wire(self, message: Message) -> None:
        if message.sender_name != self.negotiator or message.sender.startswith(HUMAN_PREFIX):
            return
        for tag in parse(message.body):
            if tag.verb == "RESET":
                self.playbook.reset()
                self.pending = {}
                self.ledger = []
            elif tag.verb == "SEALED":
                await self.write_log()
            elif tag.verb == "OPENING" and tag.clause:
                decision = self.playbook.opening(tag.clause)
                await self.verdict(tag.clause, decision.value, COUNTER)
            elif tag.verb == "REVIEW" and tag.clause and tag.value is not None:
                await self.review(tag.clause, tag.value)

    async def review(self, clause: str, value: float | str) -> None:
        decision = self.playbook.review(clause, value)
        if decision.action == ACCEPT:
            self.record(f"{clause}: Counsel accepted {show(clause, value)} under delegated authority.")
            await self.verdict(clause, decision.value, ACCEPT)
        elif decision.action == COUNTER:
            self.record(f"{clause}: Counsel countered at {show(clause, decision.value)}.")
            await self.verdict(clause, decision.value, COUNTER)
        elif decision.action == HOLD:
            self.record(f"{clause}: Counsel held at {show(clause, decision.value)}. Nothing further is authorised.")
            await self.client.post(
                self.chamber,
                f"**Heads up: {CLAUSES[clause].title}.** The other side is at **{describe(clause, value)}**, "
                "beyond every limit in the playbook. Counsel is holding. "
                f"Reply `counter {clause} <value>` if you want to change that.",
            )
            self.pending[clause] = Pending(HOLD, decision.value, value)
            await self.verdict(clause, decision.value, HOLD)
        else:
            self.pending[clause] = Pending(decision.action, decision.value, value)
            await self.ask(clause, decision.action, decision.value, value)
            # No value here: the position being asked about isn't authorised, so it stays in the chamber.
            await self.client.post(self.wire, render("VERDICT", clause, extra="PENDING"))

    async def ask(self, clause: str, action: str, value: float | str, theirs: float | str) -> None:
        policy = self.playbook.policies[clause]
        request = (
            f"The other side proposes **{describe(clause, value)}**. Accept it?"
            if action == ASK_ACCEPT
            else f"The other side is at **{describe(clause, theirs)}**. Authorise moving to "
            f"**{describe(clause, value)}**?"
        )
        await self.client.post(
            self.chamber,
            f"**Decision needed: {CLAUSES[clause].title}**\n{request}\n"
            f"Counsel's delegated authority ends at {describe(clause, policy.auto_through)}. "
            f"Yours runs to {describe(clause, policy.signoff_through)}.\n"
            f"Context: {policy.rationale}\n"
            f"Reply `approve {clause}`, `decline {clause}`, or `counter {clause} <value>`.",
        )

    async def on_chamber(self, message: Message) -> None:
        if not message.sender.startswith(HUMAN_PREFIX):
            return
        match = COMMAND.match(message.body)
        if not match:
            return
        command, clause, raw = match.group(1).lower(), match.group(2), match.group(3)
        if clause not in self.pending:
            await self.client.post(self.chamber, f"Nothing is waiting on `{clause}` right now.")
            return
        if not self.is_authority(message):
            self.record(f"{clause}: REFUSED {command} from {message.sender_name}, who has no signing authority.")
            await self.client.post(
                self.chamber,
                f"{message.sender_name}, only @{self.playbook.authority} can decide this. "
                "Your request is logged and the clause is still waiting.",
            )
            return
        pending = self.pending[clause]
        who = message.sender_name
        if command == "approve" and pending.action == ASK_ACCEPT:
            del self.pending[clause]
            self.record(f"{clause}: {who} APPROVED accepting {show(clause, pending.value)}.")
            await self.client.post(self.chamber, f"Recorded: {who} approved {describe(clause, pending.value)}.")
            await self.verdict(clause, pending.value, ACCEPT)
        elif command == "approve" and pending.action == ASK_OFFER:
            del self.pending[clause]
            self.playbook.record_offer(clause, pending.value)
            self.record(f"{clause}: {who} APPROVED offering {show(clause, pending.value)}.")
            await self.client.post(self.chamber, f"Recorded: {who} authorised {describe(clause, pending.value)}.")
            await self.verdict(clause, pending.value, COUNTER)
        elif command == "counter":
            await self.gc_counter(clause, raw, who)
        elif command == "decline":
            del self.pending[clause]
            current = self.playbook.current_offer(clause)
            self.record(f"{clause}: {who} DECLINED. Holding at {show(clause, current)}.")
            await self.client.post(self.chamber, f"Recorded: {who} declined. Holding at {describe(clause, current)}.")
            await self.verdict(clause, current, HOLD)
        else:
            await self.client.post(self.chamber, f"`{command}` doesn't apply here. Try `counter {clause} <value>`.")

    async def gc_counter(self, clause: str, raw: str | None, who: str) -> None:
        try:
            value = parse_value(clause, (raw or "").strip())
        except ValueError:
            await self.client.post(self.chamber, f"I couldn't read that value for `{clause}`.")
            return
        del self.pending[clause]
        self.playbook.record_offer(clause, value)
        self.record(f"{clause}: {who} directed a counter at {show(clause, value)}.")
        await self.client.post(self.chamber, f"Recorded: {who} directed a counter at {describe(clause, value)}.")
        await self.verdict(clause, value, COUNTER)

    async def write_log(self) -> None:
        """Keep the signing record in Switch itself, where only this company can read it."""
        body = "\n".join(self.ledger) or "- No decisions recorded."
        await self.client.op("connect_to_room", connection=True, room_id=self.chamber)
        await self.client.op(
            "create_room_document",
            connection=True,
            name=f"authority-log-{time.strftime('%Y%m%d-%H%M%S')}",
            description=f"Who authorised what for {self.playbook.company}.",
            instructions="Private record of decisions. Do not share outside this room.",
            content=f"# {self.playbook.company}: authority log\n\n{body}\n",
        )
        await self.client.post(self.chamber, f"Deal sealed. The authority log is filed in this room.\n\n{body}")

    async def run(self) -> None:
        await self.resolve_authority()
        log.info("%s online, signing authority: %s", self.name, self.playbook.authority)
        async for message in self.client.events([self.wire, self.chamber]):
            try:
                if message.room_id == self.wire:
                    await self.on_wire(message)
                elif message.room_id == self.chamber:
                    await self.on_chamber(message)
            except Exception:
                log.exception("%s: failed handling a message", self.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    company = sys.argv[1]
    path = Path(os.environ.get("COUNTERPART_LIMITS", ROOT / "private" / company / "playbook.yaml"))
    asyncio.run(Counsel(company, Playbook.load(path)).run())
