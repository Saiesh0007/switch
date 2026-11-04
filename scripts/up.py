#!/usr/bin/env python3
"""Bring up the Switch server and create the people, agents and rooms.

    python scripts/up.py           # start, or reuse what is already running
    python scripts/up.py --reset   # delete this project's containers and data, then start clean
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
COMPOSE = ["docker", "compose", "--env-file", ".env"]


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([*COMPOSE, *args], cwd=DEPLOY, check=check, text=True, capture_output=True)


def wait_for(description: str, test, seconds: int = 300) -> None:
    print(f"Waiting for {description}...", flush=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        if test():
            return
        time.sleep(3)
    sys.exit(f"Timed out waiting for {description}. Run `docker compose logs` in deploy/ to see why.")


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except OSError:
        return False


def setup_finished() -> bool:
    result = compose("ps", "-a", "--format", "json", "setup", check=False)
    for line in result.stdout.splitlines():
        try:
            service = json.loads(line)
        except json.JSONDecodeError:
            continue
        if service.get("State") == "exited":
            if service.get("ExitCode") == 0:
                return True
            sys.exit("Switch's setup job failed. Run `docker compose logs setup` in deploy/.")
    return False


def pull_images() -> None:
    env = {}
    for line in (DEPLOY / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    version = env["SWITCH_VERSION"]
    present = subprocess.run(
        ["docker", "image", "inspect", f"ghcr.io/sandbox-quantum/switch-core:{version}"], capture_output=True
    )
    if present.returncode == 0:
        return
    print("Pulling images. The first run downloads a few GB...", flush=True)
    pulled = compose("pull", check=False)
    if pulled.returncode != 0:
        sys.exit(
            f"{pulled.stderr[-500:]}\n\nCould not pull the images. If this says 'denied' for ghcr.io, "
            "run: bash scripts/load_images_workaround.sh"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete this project's containers and data first")
    args = parser.parse_args()

    if not shutil.which("docker"):
        sys.exit("Docker is required.")
    if subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True).returncode != 0:
        sys.exit("Docker is installed but not running. Start Docker Desktop and try again.")

    subprocess.run([sys.executable, str(ROOT / "scripts" / "init_env.py")], check=True)
    if args.reset:
        print("Removing this project's containers and data...", flush=True)
        compose("down", "-v", check=False)
        shutil.rmtree(ROOT / ".counterpart", ignore_errors=True)

    pull_images()
    print("Starting Switch, Mattermost and Postgres...", flush=True)
    compose("up", "-d")
    wait_for("Switch", lambda: answers("http://127.0.0.1:8000/health"))
    wait_for("Mattermost", lambda: answers("http://127.0.0.1:8065/api/v4/system/ping"))
    wait_for("Switch's setup job", setup_finished)
    subprocess.run([sys.executable, "-m", "counterpart.bootstrap"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
