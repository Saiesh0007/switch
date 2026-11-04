"""Create the owners, people, agents and rooms. Safe to re-run: existing things are reused.

Ownership is the security boundary. Switch lets a room's owner, an admin, or an existing
member change who is in a room, and an agent inherits its owner's rights. So every party
gets its own non-admin owner: if the Negotiator and the chamber shared an owner, the
Negotiator could simply invite itself in. `python -m counterpart.verify_isolation` proves
this on a live server.
"""
from __future__ import annotations

import asyncio
import json
import secrets

import httpx

from .config import API_URL, CREDENTIALS, MATTERMOST_URL, STATE, load_credential, load_env, save_credential, save_rooms
from .switch_client import SwitchAgent, register_agent

PEOPLE = {
    "priya": ("Priya", "Nair", "General Counsel, Acme Cloud"),
    "daniel": ("Daniel", "Okafor", "General Counsel, Bolt Retail"),
    "arjun": ("Arjun", "Mehta", "Junior Counsel, Acme Cloud. No signing authority."),
}
OWNERS = {
    "acme-legal": "Acme Legal",
    "acme-dealdesk": "Acme Deal Desk",
    "bolt-legal": "Bolt Legal",
    "bolt-dealdesk": "Bolt Deal Desk",
    "clerk-office": "Deal Clerk Office",
}
# agent -> (owner, display name, description)
AGENTS = {
    "acme-negotiator": ("acme-dealdesk", "Acme Negotiator", "Argues Acme's position in the deal room. Holds no limits."),
    "acme-counsel": ("acme-legal", "Acme Counsel", "Checks proposals against Acme's private playbook."),
    "bolt-negotiator": ("bolt-dealdesk", "Bolt Negotiator", "Argues Bolt's position in the deal room. Holds no limits."),
    "bolt-counsel": ("bolt-legal", "Bolt Counsel", "Checks proposals against Bolt's private playbook."),
    "clerk": ("clerk-office", "Deal Clerk", "Neutral. Keeps the agenda and the record in the deal room."),
}
# room -> (creating agent, member agents, people, description)
ROOMS = {
    "deal-room": (
        "clerk",
        ["clerk", "acme-negotiator", "bolt-negotiator"],
        ["priya", "daniel"],
        "Shared negotiation. Both companies can read everything here.",
    ),
    "acme-wire": (
        "acme-counsel",
        ["acme-counsel", "acme-negotiator"],
        ["priya"],
        "Acme only. Counsel sends the Negotiator verdicts, and nothing else.",
    ),
    "acme-chamber": (
        "acme-counsel",
        ["acme-counsel"],
        ["priya", "arjun"],
        "Acme only. Counsel and the General Counsel. The Negotiator is not a member.",
    ),
    "bolt-wire": (
        "bolt-counsel",
        ["bolt-counsel", "bolt-negotiator"],
        ["daniel"],
        "Bolt only. Counsel sends the Negotiator verdicts, and nothing else.",
    ),
    "bolt-chamber": (
        "bolt-counsel",
        ["bolt-counsel"],
        ["daniel"],
        "Bolt only. Counsel and the General Counsel. The Negotiator is not a member.",
    ),
}


def ensure_people(env: dict[str, str]) -> None:
    with httpx.Client(base_url=f"{MATTERMOST_URL}/api/v4", timeout=30) as mm:
        login = mm.post(
            "/users/login",
            json={"login_id": env["MATTERMOST_ADMIN_USER"], "password": env["MATTERMOST_ADMIN_PASSWORD"]},
        )
        login.raise_for_status()
        mm.headers["Authorization"] = f"Bearer {login.headers['Token']}"
        team = mm.get(f"/teams/name/{env['MATTERMOST_TEAM_NAME']}").json()["id"]
        for username, (first, last, position) in PEOPLE.items():  # one account per person
            response = mm.get(f"/users/username/{username}")
            if response.status_code == 200:
                user = response.json()
            else:
                created = mm.post(
                    "/users",
                    json={
                        "username": username,
                        "email": f"{username}@counterpart.example.com",
                        "password": env["MATTERMOST_USER_PASSWORD"],
                        "first_name": first,
                        "last_name": last,
                        "position": position,
                    },
                )
                created.raise_for_status()
                user = created.json()
            mm.post(f"/teams/{team}/members", json={"team_id": team, "user_id": user["id"]}).raise_for_status()
            print(f"person   {username}")


def ensure_owners(env: dict[str, str]) -> dict[str, str]:
    """Create one non-admin Switch user per party and mint each a registration key."""
    path = STATE / "owners.json"
    keys: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    missing = [owner for owner in OWNERS if owner not in keys]
    if not missing:
        return keys
    with httpx.Client(base_url=API_URL, timeout=30) as admin:
        admin.post(
            "/gateway/auth/login",
            json={"email": env["GATEWAY_ADMIN_EMAIL"], "password": env["GATEWAY_ADMIN_PASSWORD"]},
        ).raise_for_status()
        for owner in missing:
            email = f"{owner}@counterpart.example.com"
            password = secrets.token_urlsafe(24)
            admin.post(
                "/gateway/users", json={"name": OWNERS[owner], "email": email, "password": password, "role": "user"}
            ).raise_for_status()
            with httpx.Client(base_url=API_URL, timeout=30) as user:
                user.post("/gateway/auth/login", json={"email": email, "password": password}).raise_for_status()
                created = user.post("/gateway/api-keys", json={"label": "counterpart"})
                created.raise_for_status()
                keys[owner] = created.json()["key"]
            print(f"owner    {owner}")
    STATE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return keys


def ensure_agents(keys: dict[str, str]) -> None:
    for name, (owner, display, description) in AGENTS.items():
        if not (CREDENTIALS / f"{name}.json").exists():
            save_credential(name, register_agent(keys[owner], name, description, display))
        print(f"agent    {name} (owner: {owner})")


async def ensure_rooms() -> dict[str, str]:
    rooms: dict[str, str] = {}
    for room, (creator, agents, people, description) in ROOMS.items():
        client = SwitchAgent(load_credential(creator))
        try:
            existing = await client.op("list_rooms")
            match = next((r for r in existing if r["name"] == room), None)
            if match:
                rooms[room] = match["room_id"]
                await client.op("add_users_to_room", room_id=rooms[room], user_names=people)
            else:
                created = await client.op(
                    "create_room",
                    name=room,
                    description=description,
                    agent_names=agents,
                    user_names=people,
                    channel_type="channel_private",
                    read_visibility="private",
                    write_visibility="private",
                )
                if created.get("failed_attachments"):
                    print(f"warning  {room}: {created['failed_attachments']}")
                rooms[room] = created["id"]
            print(f"room     {room} {rooms[room]}")
        finally:
            await client.close()
    save_rooms(rooms)
    return rooms


def tighten_channels(env: dict[str, str]) -> None:
    """Remove the seeded demo account, which Mattermost adds to each channel the bridge creates.

    Only the people named in ROOMS belong in a room. The bridge's admin account has to stay,
    because Switch signs in with it to operate the channels.
    """
    with httpx.Client(base_url=f"{MATTERMOST_URL}/api/v4", timeout=30) as mm:
        login = mm.post(
            "/users/login",
            json={"login_id": env["MATTERMOST_ADMIN_USER"], "password": env["MATTERMOST_ADMIN_PASSWORD"]},
        )
        login.raise_for_status()
        mm.headers["Authorization"] = f"Bearer {login.headers['Token']}"
        team = mm.get(f"/teams/name/{env['MATTERMOST_TEAM_NAME']}").json()["id"]
        seeded = mm.get(f"/users/username/{env['MATTERMOST_USER']}").json()["id"]
        channels = mm.get(f"/teams/{team}/channels/private", params={"per_page": 200}).json()
        for channel in channels:
            if channel["display_name"] in ROOMS:
                removed = mm.delete(f"/channels/{channel['id']}/members/{seeded}")
                if removed.status_code == 200:
                    print(f"removed  seeded account from {channel['display_name']}")


def main() -> None:
    env = load_env()
    ensure_people(env)
    keys = ensure_owners(env)
    ensure_agents(keys)
    asyncio.run(ensure_rooms())
    tighten_channels(env)
    print("Bootstrap complete.")
    print(f"Sign in at {MATTERMOST_URL} as priya, daniel or arjun.")
    print("Their shared demo password is MATTERMOST_USER_PASSWORD in deploy/.env.")


if __name__ == "__main__":
    main()
