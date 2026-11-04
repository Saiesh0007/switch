"""Minimal client for the Switch agent protocol (HTTP operations and WebSocket events)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

from .config import API_URL

log = logging.getLogger(__name__)

INTEGRATION_PROFILE = {
    "connection_model": "always_on",
    "message_exchange": True,
    "pre_invocation_mediation": [],
    "post_invocation_mediation": [],
    "event_reporting": [],
}


class SwitchError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def register_agent(registration_token: str, name: str, description: str, display_name: str) -> dict[str, str]:
    """Register once. Overwrite issues a new key and invalidates the old one."""
    response = httpx.post(
        f"{API_URL}/agents",
        headers={"Authorization": f"Bearer {registration_token}"},
        json={
            "name": name,
            "display_name": display_name,
            "description": description,
            "connector_type": "counterpart",
            "integration_profile": INTEGRATION_PROFILE,
            "overwrite": True,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise SwitchError(response.status_code, response.text)
    body = response.json()
    return {"name": name, "id": body["id"], "api_key": body["api_key"]}


@dataclass
class Message:
    room_id: str
    sender: str
    sender_name: str
    body: str
    message_id: str
    thread_id: str | None
    addressed: bool
    sequence: int


class SwitchAgent:
    """One agent identity. Holds exactly one credential and sees only its own rooms."""

    def __init__(self, credential: dict[str, str]):
        self.name = credential["name"]
        self.id = credential["id"]
        self._key = credential["api_key"]
        self.connection_id = str(uuid.uuid4())
        self._http = httpx.AsyncClient(
            base_url=API_URL, headers={"Authorization": f"Bearer {self._key}"}, timeout=60
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def op(self, operation: str, connection: bool = False, **args: Any) -> Any:
        headers = {"X-Switch-Connection-Id": self.connection_id} if connection else {}
        response = await self._http.post(f"/agents/{self.id}/ops/{operation}", json=args, headers=headers)
        if response.status_code >= 400:
            raise SwitchError(response.status_code, response.text)
        return response.json().get("result")

    async def post(self, room_id: str, content: str) -> None:
        response = await self._http.post(f"/agents/{self.id}/message", json={"room_id": room_id, "content": content})
        if response.status_code >= 400:
            raise SwitchError(response.status_code, response.text)

    async def events(self, rooms: list[str]) -> AsyncIterator[Message]:
        """Yield messages from this agent's rooms forever.

        The socket has its own task, because Switch evicts a connection that misses heartbeats
        for six seconds, and handling a message can take longer than that when a model is involved.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue()
        reader = asyncio.create_task(self._read_socket(rooms, queue))
        seen: set[str] = set()  # a resumed connection can replay messages
        try:
            while True:
                message = await queue.get()
                if message.message_id and message.message_id in seen:
                    continue
                seen.add(message.message_id)
                yield message
        finally:
            reader.cancel()

    async def _read_socket(self, rooms: list[str], queue: "asyncio.Queue[Message]") -> None:
        """Keep one connection alive, answer heartbeats, and queue every message."""
        cursor: int | None = None
        generation: int | None = None
        ws_base = API_URL.replace("http://", "ws://").replace("https://", "wss://")
        while True:
            query = [("connection_id", self.connection_id), ("scope", "all"), ("filter", "all")]
            query += [("rooms", room) for room in rooms]
            if cursor is not None:
                query.append(("start_from", str(cursor)))
            if generation is not None:
                query.append(("expected_generation", str(generation)))
            url = f"{ws_base}/agents/{self.id}/connection/ws?{httpx.QueryParams(query)}"
            try:
                async with websockets.connect(
                    url, additional_headers={"Authorization": f"Bearer {self._key}"}, ping_interval=None
                ) as ws:
                    async for raw in ws:
                        frame = json.loads(raw)
                        kind = frame.get("type") or frame.get("event")
                        if kind == "connection_state":
                            state = frame.get("data", frame)
                            generation = state.get("generation", generation)
                        elif kind == "ping":
                            pong: dict[str, Any] = {"type": "pong"}
                            if cursor is not None:
                                pong["cursor"] = cursor
                            await ws.send(json.dumps(pong))
                        elif kind == "message":
                            data = frame["data"]
                            cursor = data.get("sequence", frame.get("id", cursor))
                            payload = data["payload"]
                            queue.put_nowait(
                                Message(
                                    room_id=data["room_id"],
                                    sender=payload.get("sender", ""),
                                    sender_name=payload.get("sender_name", ""),
                                    body=payload.get("body", ""),
                                    message_id=payload.get("message_id", ""),
                                    thread_id=payload.get("thread_id"),
                                    addressed=bool(payload.get("addressed")),
                                    sequence=cursor or 0,
                                )
                            )
                        elif kind in {"evicted", "refused"}:
                            log.warning("%s: %s %s", self.name, kind, frame)
                        elif frame.get("id") is not None:
                            cursor = frame["id"]
            except (OSError, websockets.WebSocketException) as exc:
                log.warning("%s: connection lost (%s); reconnecting", self.name, exc)
            await asyncio.sleep(1)
