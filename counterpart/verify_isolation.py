"""Attack the room boundaries on a live Switch server, using each agent's real credential.

Every attack must be refused by the server. Controls must succeed, so that a server that
refuses everything cannot pass. If an attack succeeds, the damage is undone and the run fails.

    python -m counterpart.verify_isolation
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from .bootstrap import ROOMS
from .config import MATTERMOST_URL, load_credential, load_env, load_rooms
from .switch_client import SwitchAgent, SwitchError

PRIVATE_ROOMS = ("acme-chamber", "bolt-chamber", "acme-wire", "bolt-wire")


def check_channel_members() -> int:
    """Compare each channel's human members with the intended list in the room definitions."""
    env = load_env()
    problems = 0
    with httpx.Client(base_url=f"{MATTERMOST_URL}/api/v4", timeout=30) as mm:
        login = mm.post(
            "/users/login",
            json={"login_id": env["MATTERMOST_ADMIN_USER"], "password": env["MATTERMOST_ADMIN_PASSWORD"]},
        )
        login.raise_for_status()
        mm.headers["Authorization"] = f"Bearer {login.headers['Token']}"
        team = mm.get(f"/teams/name/{env['MATTERMOST_TEAM_NAME']}").json()["id"]
        channels = {c["display_name"]: c["id"] for c in mm.get(f"/teams/{team}/channels/private", params={"per_page": 200}).json()}
        for room, (_, _, people, _) in ROOMS.items():
            members = mm.get(f"/channels/{channels[room]}/members", params={"per_page": 200}).json()
            users = mm.post("/users/ids", json=[m["user_id"] for m in members]).json()
            humans = {u["username"] for u in users if not u.get("is_bot")} - {env["MATTERMOST_ADMIN_USER"]}
            extra = humans - set(people)
            if extra:
                problems += 1
                print(f"  BREACH         {room} also contains {sorted(extra)}")
            else:
                print(f"  EXACT          {room}: {sorted(humans)}")
    return problems


async def run() -> int:
    rooms = load_rooms()
    agents = {
        name: SwitchAgent(load_credential(name))
        for name in ("acme-negotiator", "acme-counsel", "bolt-negotiator", "bolt-counsel", "clerk")
    }
    failures = 0

    async def attack(label: str, call, undo=None) -> None:
        nonlocal failures
        try:
            await call()
        except (SwitchError, RuntimeError) as exc:
            status = getattr(exc, "status", "?")
            print(f"  REFUSED ({status})  {label}")
            return
        failures += 1
        print(f"  BREACH         {label}")
        if undo:
            await undo()

    async def control(label: str, call) -> None:
        nonlocal failures
        try:
            await call()
            print(f"  ALLOWED        {label}")
        except SwitchError as exc:
            failures += 1
            print(f"  BROKEN ({exc.status})   {label}")

    def invite(attacker: str, room: str, target: str):
        return lambda: agents[attacker].op("invite_agent_to_room", room_id=rooms[room], agent_name=target)

    def evict(room: str, target: str, by: str):
        return lambda: agents[by].op("remove_agent_from_room", room_id=rooms[room], agent_name=target)

    def read(agent: str, room: str):
        return lambda: agents[agent].op("read_context", room_id=rooms[room])

    def post(agent: str, room: str):
        return lambda: agents[agent].post(rooms[room], "isolation probe")

    print("A Negotiator tries to reach its own company's chamber")
    await attack("acme-negotiator reads acme-chamber", read("acme-negotiator", "acme-chamber"))
    await attack("acme-negotiator posts in acme-chamber", post("acme-negotiator", "acme-chamber"))
    await attack(
        "acme-negotiator invites itself to acme-chamber",
        invite("acme-negotiator", "acme-chamber", "acme-negotiator"),
        evict("acme-chamber", "acme-negotiator", "acme-counsel"),
    )

    print("The other side tries to reach Acme's private rooms")
    for room in ("acme-chamber", "acme-wire"):
        await attack(f"bolt-negotiator reads {room}", read("bolt-negotiator", room))
        await attack(f"bolt-negotiator posts in {room}", post("bolt-negotiator", room))
        await attack(
            f"bolt-negotiator invites itself to {room}",
            invite("bolt-negotiator", room, "bolt-negotiator"),
            evict(room, "bolt-negotiator", "acme-counsel"),
        )
    await attack("bolt-counsel reads acme-chamber", read("bolt-counsel", "acme-chamber"))
    await attack(
        "bolt-negotiator sees details of acme-chamber",
        lambda: agents["bolt-negotiator"].op("get_room_detail", room_id=rooms["acme-chamber"]),
    )

    print("Acme tries to reach Bolt's private rooms")
    await attack("acme-negotiator reads bolt-chamber", read("acme-negotiator", "bolt-chamber"))
    await attack(
        "acme-negotiator invites itself to bolt-chamber",
        invite("acme-negotiator", "bolt-chamber", "acme-negotiator"),
        evict("bolt-chamber", "acme-negotiator", "bolt-counsel"),
    )

    print("The neutral Clerk tries to reach a private room")
    await attack("clerk reads acme-chamber", read("clerk", "acme-chamber"))
    await attack("clerk reads bolt-wire", read("clerk", "bolt-wire"))

    # Switch 0.31.0 documents list_all_rooms as listing every room on the server, and the next
    # release narrows it. So a name and description may show here, which is why they stay generic.
    # This check still fails if the listing ever exposes anything more than that.
    print("Room listing exposes names and descriptions at most (known limit of Switch 0.31.0)")
    listing = await agents["bolt-negotiator"].op("list_all_rooms")
    entries = listing["rooms"] if isinstance(listing, dict) else listing
    allowed_fields = {"room_id", "name", "description", "archived"}
    for room in ("acme-chamber", "acme-wire"):
        entry = next((r for r in entries if r["name"] == room), None)
        if entry is None:
            print(f"  HIDDEN         {room} is not listed for bolt-negotiator")
        elif set(entry) <= allowed_fields:
            print(f"  NAME ONLY      {room} is listed for bolt-negotiator, with no contents")
        else:
            failures += 1
            print(f"  BREACH         listing of {room} exposes {sorted(set(entry) - allowed_fields)}")

    print("Only the intended people are in each private channel")
    failures += check_channel_members()

    print("Controls: legitimate access still works")
    await control("acme-counsel reads acme-chamber", read("acme-counsel", "acme-chamber"))
    await control("acme-negotiator reads acme-wire", read("acme-negotiator", "acme-wire"))
    await control("bolt-negotiator reads deal-room", read("bolt-negotiator", "deal-room"))
    await control("clerk reads deal-room", read("clerk", "deal-room"))

    for agent in agents.values():
        await agent.close()

    print()
    print(f"RESULT: {'PASS, no breaches' if failures == 0 else f'FAIL, {failures} problem(s)'}")
    return 1 if failures else 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
