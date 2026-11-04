"""Output and SSH tunnel helpers shared by the laptop test scripts."""

import contextlib
import os
import socket
import subprocess
import tempfile
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

ENV_FILE = Path(__file__).resolve().with_name(".env")
WIDTH = 72
ASKPASS_SCRIPT = """#!/bin/sh
# Answers ssh password and passphrase prompts from SSH_PW. Refuses any other
# prompt, such as the yes/no question for an unknown host key.
case "$1" in
  *assword*|*assphrase*) printf '%s\\n' "$SSH_PW" ;;
  *) exit 1 ;;
esac
"""


def section(step: int | None, title: str, what: str, *, total: int) -> None:
    label = f"[{step}/{total}] {title}" if step else title
    print()
    print("=" * WIDTH)
    print(label)
    print("=" * WIDTH)
    print(textwrap.fill(what, WIDTH))
    print()


def kv(label: str, value: object) -> None:
    print(f"  {label:<24} {value}")


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def askpass_env() -> Iterator[dict[str, str] | None]:
    """Let ssh read its password from SSH_PW, if it is set.

    ssh has no option for a password, so point SSH_ASKPASS at a small helper
    that prints SSH_PW. The helper holds no secret; it reads the variable.
    """
    if not os.environ.get("SSH_PW"):
        yield None
        return
    with tempfile.TemporaryDirectory() as tmp:
        helper = Path(tmp) / "askpass.sh"
        helper.write_text(ASKPASS_SCRIPT)
        helper.chmod(0o700)
        yield {
            **os.environ,
            "SSH_ASKPASS": str(helper),
            "SSH_ASKPASS_REQUIRE": "force",
        }


@contextlib.contextmanager
def ssh_tunnel(
    server: str, user: str, key: str | None, port_map: dict[int, int]
) -> Iterator[None]:
    local_ports = list(port_map.values())
    busy = [port for port in local_ports if port_in_use(port)]
    if busy:
        raise RuntimeError(
            f"Local port(s) {busy} are already in use on this laptop. "
            "Set LOCAL_BOLT_PORT to a free port and try again."
        )

    use_ssh_pw = bool(os.environ.get("SSH_PW"))
    cmd = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes"]
    if use_ssh_pw:
        cmd += ["-o", "NumberOfPasswordPrompts=1"]
    if key:
        cmd += ["-i", key]
    for remote, local in port_map.items():
        cmd += ["-L", f"{local}:localhost:{remote}"]
    cmd.append(f"{user}@{server}")
    kv("Command", " ".join(cmd))

    with askpass_env() as env:
        proc = subprocess.Popen(cmd, env=env)
        try:
            deadline = time.monotonic() + 30
            while not all(port_in_use(port) for port in local_ports):
                if proc.poll() is not None:
                    hint = (
                        " Check SSH_PW. If this is the first connection to "
                        "the server, run ssh once by hand to accept its "
                        "host key."
                        if use_ssh_pw
                        else ""
                    )
                    raise RuntimeError(f"ssh exited with code {proc.returncode}.{hint}")
                if time.monotonic() > deadline:
                    raise RuntimeError("The SSH tunnel did not open within 30 seconds.")
                time.sleep(0.25)
            kv("Tunnel", f"open, ssh pid {proc.pid}")
            yield
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print()
            print(f"SSH tunnel closed (pid {proc.pid}).")
