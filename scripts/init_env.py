#!/usr/bin/env python3
"""Generate deploy/.env with fresh secrets. Safe to re-run: never overwrites."""
import secrets
import sys
from pathlib import Path

SWITCH_VERSION = sys.argv[1] if len(sys.argv) > 1 else "0.31.0"
ENV = Path(__file__).resolve().parent.parent / "deploy" / ".env"


def hex24() -> str:
    return secrets.token_hex(24)


def main() -> None:
    if ENV.exists():
        print(f"{ENV} already exists; leaving it alone.")
        return
    values = {
        "SWITCH_VERSION": SWITCH_VERSION,
        "COMPOSE_PROJECT_NAME": "counterpart",
        "COMPOSE_PROFILES": "collab,gateway",
        "SWITCH_BIND_ADDR": "127.0.0.1",
        "API_HOST_PORT": "8000",
        "GATEWAY_HOST_PORT": "3000",
        "MATTERMOST_HOST_PORT": "8065",
        "POSTGRES_HOST_PORT": "5433",
        "DB_USER": "switch_app",
        "DB_PASSWORD": hex24(),
        "DB_OWNER_USER": "postgres",
        "DB_OWNER_PASSWORD": hex24(),
        "DB_NAME": "switch",
        "AGENT_REGISTRATION_TOKEN": hex24(),
        "SECRET_KEYS": f"local:{secrets.token_hex(32)}",
        "GATEWAY_ADMIN_EMAIL": "admin@switch.local",
        "GATEWAY_ADMIN_PASSWORD": hex24(),
        "GATEWAY_COOKIE_SECURE": "false",
        "FRONTEND_BASE_URL": "http://localhost:3000",
        "MATTERMOST_ADMIN_USER": "admin",
        "MATTERMOST_ADMIN_PASSWORD": hex24(),
        "MATTERMOST_TEAM_NAME": "counterpart",
        "MATTERMOST_USER": "user",
        "MATTERMOST_USER_PASSWORD": hex24(),
        "TELEMETRY_ENABLED": "false",
    }
    ENV.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    print(f"Wrote {ENV}")


if __name__ == "__main__":
    main()
