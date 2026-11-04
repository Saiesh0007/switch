"""The Clerk: a neutral agent that runs the agenda and keeps the record in the deal room.

It trusts only tags from the two Negotiators and signatures from the two General Counsels'
verified accounts. It sees what both companies can see, and nothing more.

    python -m counterpart.clerk
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from .clauses import AGENDA, CLAUSES, describe
from .config import load_credential, load_rooms
from .protocol import parse, render
from .switch_client import Message, SwitchAgent, SwitchError

log = logging.getLogger("clerk")

HUMAN_PREFIX = "@switch-mattermost-"
NEGOTIATORS = {"acme-negotiator", "bolt-negotiator"}
SIGNATORIES = {"priya": "Priya Nair, Acme Cloud", "daniel": "Daniel Okafor, Bolt Retail"}
MAX_ROUNDS = 12


class Clerk:
    def __init__(self):
        self.client = SwitchAgent(load_credential("clerk"))
        self.room = load_rooms()["deal-room"]
        self.signatory_ids: dict[str, str] = {}
        self.clear()

    def clear(self) -> None:
        self.active = False
        self.queue: list[str] = []
        self.current: str | None = None
        self.last: tuple[str, float | str] | None = None
        self.rounds = 0
        self.agreed: dict[str, float | str] = {}
        self.deadlocked: list[str] = []
        self.awaiting_signatures = False
        self.signed: set[str] = set()
        self.seal = ""

    async def resolve_signatories(self) -> None:
        bridges = await self.client.op("list_bridges")
        bridge = bridges[0] if isinstance(bridges, list) else bridges["bridges"][0]
        bridge_id = bridge.get("id") or bridge.get("bridge_id")
        self.signatory_ids = {f"{HUMAN_PREFIX}{bridge_id}-{name}:localhost": name for name in SIGNATORIES}

    async def start(self) -> None:
        self.clear()
        self.active = True
        self.queue = list(AGENDA)
        agenda = "\n".join(f"{i}. {CLAUSES[key].title}" for i, key in enumerate(AGENDA, 1))
        await self.client.post(
            self.room,
            "**Master Services Agreement: Acme Cloud and Bolt Retail**\n"
            "Both companies' agents negotiate here. Each agent's limits stay with its own company, "
            f"and anything beyond an agent's authority goes to that company's General Counsel.\n\n{agenda}\n"
            f"{render('DEAL', extra='START')}",
        )
        await self.next_clause()

    async def next_clause(self) -> None:
        self.current = self.queue.pop(0) if self.queue else None
        self.last = None
        self.rounds = 0
        if self.current:
            await self.client.post(self.room, f"**Now open: {CLAUSES[self.current].title}** {render('OPEN', self.current)}")
        else:
            await self.ask_for_signatures()

    def terms(self) -> str:
        lines = []
        for key in AGENDA:
            if key in self.agreed:
                wording = CLAUSES[key].wording.format(value=describe(key, self.agreed[key]).split(" ")[0])
                if CLAUSES[key].kind == "choice":
                    wording = CLAUSES[key].wording.format(value=self.agreed[key])
                lines.append(f"**{CLAUSES[key].title}.** {wording}")
        return "\n".join(lines)

    async def ask_for_signatures(self) -> None:
        if self.deadlocked:
            names = ", ".join(CLAUSES[key].title for key in self.deadlocked)
            await self.client.post(
                self.room,
                f"**Deadlocked:** {names}. These need @priya and @daniel to talk directly.\n\n"
                f"Agreed so far:\n{self.terms()}",
            )
            self.active = False
            return
        self.awaiting_signatures = True
        await self.client.post(
            self.room,
            f"**All clauses agreed.**\n\n{self.terms()}\n\n"
            "Agents cannot sign. @priya and @daniel, type `sign` if you accept these terms.",
        )

    async def on_negotiator(self, message: Message) -> None:
        party = message.sender_name
        for tag in parse(message.body):
            if tag.clause != self.current or tag.value is None:
                continue
            if tag.verb == "PROPOSE":
                self.last = (party, tag.value)
                self.rounds += 1
                if self.rounds >= MAX_ROUNDS:
                    self.deadlocked.append(tag.clause)
                    await self.client.post(self.room, f"No movement on {CLAUSES[tag.clause].title}. Marked as deadlocked.")
                    await self.next_clause()
            elif tag.verb == "ACCEPT":
                if self.last and self.last[0] != party and self.last[1] == tag.value:
                    self.agreed[tag.clause] = tag.value
                    summary = describe(tag.clause, tag.value)
                    await self.client.post(self.room, f"**Agreed: {CLAUSES[tag.clause].title}, {summary}.**")
                    await self.next_clause()
                else:
                    log.warning("ignored an acceptance that matches no open proposal: %s", message.body)

    async def on_signature(self, name: str) -> None:
        self.signed.add(name)
        waiting = [person for person in SIGNATORIES if person not in self.signed]
        if waiting:
            await self.client.post(self.room, f"Signed by {SIGNATORIES[name]}. Waiting for @{waiting[0]}.")
            return
        await self.seal_deal()

    async def seal_deal(self) -> None:
        canonical = json.dumps({key: self.agreed[key] for key in AGENDA}, sort_keys=True)
        self.seal = hashlib.sha256(canonical.encode()).hexdigest()
        self.awaiting_signatures = False
        self.active = False
        signed_by = "\n".join(f"- {person}" for person in SIGNATORIES.values())
        record = (
            f"# Master Services Agreement\n\nAcme Cloud and Bolt Retail, {time.strftime('%Y-%m-%d')}\n\n"
            f"{self.terms()}\n\nSigned by:\n{signed_by}\n\nSHA-256 of agreed terms: {self.seal}\n"
        )
        filed = "The signed agreement is filed in this room."
        try:
            await self.client.op("connect_to_room", connection=True, room_id=self.room)
            await self.client.op(
                "create_room_document",
                connection=True,
                name=f"agreement-{time.strftime('%Y%m%d-%H%M%S')}-{self.seal[:8]}",
                description="Final agreed terms, signed by both General Counsels.",
                instructions="The executed record of this negotiation.",
                content=record,
            )
        except SwitchError as exc:
            # Both people have signed, so the deal stands. Say plainly that filing failed.
            log.error("could not file the agreement: %s", exc)
            filed = f"Filing the document failed, so here is the record:\n\n{record}"
        await self.client.post(
            self.room,
            f"**Deal sealed.** {filed}\nSHA-256 of agreed terms: `{self.seal}` {render('SEALED')}",
        )

    async def on_message(self, message: Message) -> None:
        if message.sender_name == "clerk":
            return
        if message.sender_name in NEGOTIATORS and not message.sender.startswith(HUMAN_PREFIX):
            await self.on_negotiator(message)
            return
        name = self.signatory_ids.get(message.sender)
        if name is None:
            return
        text = message.body.strip().lower().lstrip("@").replace("clerk", "").strip()
        if text == "start" and not self.active and not self.awaiting_signatures:
            await self.start()
        elif text == "sign" and self.awaiting_signatures:
            await self.on_signature(name)

    async def run(self) -> None:
        await self.resolve_signatories()
        log.info("clerk online")
        async for message in self.client.events([self.room]):
            try:
                await self.on_message(message)
            except Exception:
                log.exception("clerk: failed handling a message")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(Clerk().run())
