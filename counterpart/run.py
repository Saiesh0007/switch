"""Start all five agents as separate operating-system processes.

Separate processes make the boundary real: only a Counsel process is told where its own limits
live, and each process loads a single agent's credential.

    python -m counterpart.run
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from .config import ROOT, STATE

COMMANDS = {
    "clerk": ["counterpart.clerk"],
    "acme-counsel": ["counterpart.counsel", "acme"],
    "bolt-counsel": ["counterpart.counsel", "bolt"],
    "acme-negotiator": ["counterpart.negotiator", "acme"],
    "bolt-negotiator": ["counterpart.negotiator", "bolt"],
}


def main() -> None:
    logs = STATE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    processes: dict[str, subprocess.Popen] = {}
    for name, module in COMMANDS.items():
        env = {k: v for k, v in os.environ.items() if k != "COUNTERPART_LIMITS"}
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        if name.endswith("-counsel"):
            env["COUNTERPART_LIMITS"] = str(ROOT / "private" / module[1] / "playbook.yaml")
        log = (logs / f"{name}.log").open("a", encoding="utf-8")
        processes[name] = subprocess.Popen(
            [sys.executable, "-m", *module], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        print(f"started {name} (pid {processes[name].pid})")
    print(f"Logs are in {logs}. Press Ctrl+C to stop.")
    try:
        while True:
            for name, process in processes.items():
                if process.poll() is not None:
                    print(f"{name} exited with code {process.returncode}. See its log.")
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        for process in processes.values():
            process.terminate()


if __name__ == "__main__":
    main()
