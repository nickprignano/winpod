#!/usr/bin/env python3
"""Lightweight persona switcher, QMP/QGA controller, and RDP launcher for winpod."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
from pathlib import Path


def load_profiles(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError(f"No profiles defined in {path}")
    return profiles


def qmp_command(sock_path: Path, execute: str, arguments: dict | None = None) -> dict:
    """Send a single QMP command over a QEMU Unix socket."""
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("AF_UNIX sockets require a POSIX/Linux host")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5.0)
        sock.connect(str(sock_path))
        reader = sock.makefile("r", encoding="utf-8")
        reader.readline()  # QMP greeting
        sock.sendall(b'{"execute":"qmp_capabilities"}\n')
        reader.readline()  # capabilities ack
        payload = {"execute": execute}
        if arguments is not None:
            payload["arguments"] = arguments
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        resp = reader.readline()
        return json.loads(resp) if resp else {}


def qga_sync_time(sock_path: Path) -> dict:
    """Resync guest OS clock via QEMU Guest Agent (call on laptop wake)."""
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("AF_UNIX sockets require a POSIX/Linux host")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5.0)
        sock.connect(str(sock_path))
        reader = sock.makefile("r", encoding="utf-8")
        sock.sendall(b'{"execute":"guest-set-time"}\n')
        resp = reader.readline()
        return json.loads(resp) if resp else {}


def find_freerdp_bin() -> str:
    for candidate in ("wlfreerdp", "xfreerdp3", "xfreerdp"):
        if shutil.which(candidate):
            return candidate
    return "xfreerdp"


def build_freerdp_cmd(port: int, username: str = "User", fullscreen: bool = True) -> list[str]:
    cmd = [
        find_freerdp_bin(),
        f"/v:127.0.0.1:{port}",
        f"/u:{username}",
        "/dynamic-resolution",
        "/multimon",
        "/sound",
        "/clipboard",
        "/cert:ignore",
    ]
    if fullscreen:
        cmd.append("/f")
    return cmd


def docker_container_state(container_name: str, runner=subprocess.run) -> str:
    res = runner(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.stdout.strip() if res.returncode == 0 else "missing"


def switch_profile(
    profiles: dict[str, dict],
    target: str,
    *,
    root_dir: Path,
    launch_rdp: bool = True,
    runner=subprocess.run,
    qmp_fn=qmp_command,
) -> dict:
    """Pause other running personas, start/unpause target, and attach RDP."""
    if target not in profiles:
        raise KeyError(f"Unknown profile '{target}'")

    paused = []
    for name, cfg in profiles.items():
        if name == target:
            continue
        container = cfg.get("container", f"winpod-{name}")
        if docker_container_state(container, runner=runner) == "running":
            qmp_sock = root_dir / "state" / name / "qmp.sock"
            if qmp_sock.exists():
                qmp_fn(qmp_sock, "stop")
            runner(["docker", "pause", container], check=True)
            paused.append(name)

    target_cfg = profiles[target]
    target_container = target_cfg.get("container", f"winpod-{target}")
    state = docker_container_state(target_container, runner=runner)

    if state == "paused":
        runner(["docker", "unpause", target_container], check=True)
        qmp_sock = root_dir / "state" / target / "qmp.sock"
        if qmp_sock.exists():
            qmp_fn(qmp_sock, "cont")
        action = "resumed"
    elif state == "running":
        action = "attached"
    elif state in ("exited", "created"):
        runner(["docker", "start", target_container], check=True)
        action = "started"
    else:
        raise RuntimeError(
            f"Container '{target_container}' is not created yet; provision it with docker compose up -d"
        )

    rdp_cmd = build_freerdp_cmd(
        int(target_cfg.get("rdp_port", 3389)),
        username=target_cfg.get("username", "User"),
    )
    if launch_rdp:
        runner(rdp_cmd, check=False)

    return {"target": target, "action": action, "paused": paused, "rdp_cmd": rdp_cmd}


def wake_all(
    profiles: dict[str, dict],
    *,
    root_dir: Path,
    runner=subprocess.run,
    qga_fn=qga_sync_time,
) -> list[str]:
    """Resync guest clocks for all running personas after host resume."""
    synced = []
    for name, cfg in profiles.items():
        container = cfg.get("container", f"winpod-{name}")
        if docker_container_state(container, runner=runner) == "running":
            qga_sock = root_dir / "state" / name / "qga.sock"
            if qga_sock.exists():
                qga_fn(qga_sock)
                synced.append(name)
    return synced


def interactive_menu(profiles: dict[str, dict], *, root_dir: Path) -> int:
    names = list(profiles.keys())
    while True:
        print("\n=== winpod persona switcher ===")
        for idx, name in enumerate(names, start=1):
            cfg = profiles[name]
            container = cfg.get("container", f"winpod-{name}")
            state = docker_container_state(container)
            print(f"  [{idx}] {name} (combo={cfg.get('combo', '?')}, state={state})")
        print("  [q] quit")
        choice = input("Select persona: ").strip().lower()
        if choice == "q":
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            switch_profile(profiles, names[int(choice) - 1], root_dir=root_dir)
        else:
            print("Invalid selection.")


def main() -> int:
    parser = argparse.ArgumentParser(description="winpod persona switcher")
    parser.add_argument("--profiles", type=Path, default=Path("/etc/winpod/profiles.json"))
    parser.add_argument("--root", type=Path, default=Path("/var/lib/winpod"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    sw = sub.add_parser("switch", help="Switch active persona and attach RDP")
    sw.add_argument("profile")
    sw.add_argument("--no-rdp", action="store_true")

    sub.add_parser("wake", help="Resync guest clocks via QGA after host resume")
    sub.add_parser("menu", help="Interactive kiosk persona picker")

    args = parser.parse_args()
    profiles = load_profiles(args.profiles)

    if args.cmd == "switch":
        res = switch_profile(
            profiles, args.profile, root_dir=args.root, launch_rdp=not args.no_rdp
        )
        print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "wake":
        synced = wake_all(profiles, root_dir=args.root)
        print(json.dumps({"synced": synced}, indent=2))
        return 0
    return interactive_menu(profiles, root_dir=args.root)


if __name__ == "__main__":
    raise SystemExit(main())
