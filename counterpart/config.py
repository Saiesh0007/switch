"""Paths and settings. Credentials are per agent and never shared between agents."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".counterpart"
CREDENTIALS = STATE / "credentials"
ENV_FILE = ROOT / "deploy" / ".env"

API_URL = os.environ.get("SWITCH_API_URL", "http://127.0.0.1:8000")
MATTERMOST_URL = os.environ.get("MATTERMOST_URL", "http://127.0.0.1:8065")


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def load_credential(agent: str) -> dict[str, str]:
    return json.loads((CREDENTIALS / f"{agent}.json").read_text(encoding="utf-8"))


def save_credential(agent: str, data: dict[str, str]) -> None:
    CREDENTIALS.mkdir(parents=True, exist_ok=True)
    (CREDENTIALS / f"{agent}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_rooms() -> dict[str, str]:
    return json.loads((STATE / "rooms.json").read_text(encoding="utf-8"))


def save_rooms(rooms: dict[str, str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "rooms.json").write_text(json.dumps(rooms, indent=2), encoding="utf-8")
