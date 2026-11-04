"""How the laptop reaches Neo4j. Only this file knows about the platform.

Each function opens the way in, yields an Access, and closes it at the end.
A test needs only the Access, so one test runs on every platform.
"""

import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from neo4j import Address

from support import kv, required_setting

BOLT_PORT = 7687
SSH_BOLT_PORTS = {"single": [7687], "cluster": [7687, 7697, 7707]}
SSH_URI_SCHEME = {"single": "bolt", "cluster": "neo4j"}
DEFAULT_LOCAL_BOLT_PORT = 17687
LOCAL_PORT_STEP = 10
OPEN_TIMEOUT_SECONDS = 30
ASKPASS_SCRIPT = """#!/bin/sh
# Answers ssh password and passphrase prompts from SSH_PW. Refuses any other
# prompt, such as the yes/no question for an unknown host key.
case "$1" in
  *assword*|*assphrase*) printf '%s\\n' "$SSH_PW" ;;
  *) exit 1 ;;
esac
"""

Resolver = Callable[[Address], list[Address]]


@dataclass(frozen=True)
class Access:
    uri: str
    resolver: Resolver | None = None
    members: int = 1


def local_bolt_port() -> int:
    try:
        return int(os.environ.get("LOCAL_BOLT_PORT", DEFAULT_LOCAL_BOLT_PORT))
    except ValueError as err:
        raise RuntimeError(
            "LOCAL_BOLT_PORT must be a port number, for example 17687."
        ) from err


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_resolver(ports: dict[int, int]) -> Resolver:
    """Send the VM's member addresses to the local ends of the tunnel.

    The cluster tells the driver to reach its members at localhost:7687,
    7697, and 7707. Those are server ports, so map each one to its local port.
    """

    def resolve(address: Address) -> list[Address]:
        local = ports.get(address.port)
        return [Address(("localhost", local))] if local else [address]

    return resolve


def host_resolver(ports: dict[str, int]) -> Resolver:
    """Send pod addresses to the local end of each port forward.

    Every pod uses port 7687, so only the host tells the pods apart. The driver
    receives a DNS name that starts with the pod name, which the laptop cannot
    resolve. Any other address, such as the first localhost URI, passes through.
    """

    def resolve(address: Address) -> list[Address]:
        local = ports.get(address.host.split(".")[0])
        return [Address(("localhost", local))] if local else [address]

    return resolve


@contextlib.contextmanager
def forwards(
    commands: list[list[str]],
    ports: list[int],
    env: dict[str, str] | None = None,
    failure_hint: str = "",
) -> Iterator[None]:
    """Run the commands that open local ports, and stop them at the end."""
    busy = [port for port in ports if port_in_use(port)]
    if busy:
        raise RuntimeError(
            f"Local port(s) {busy} are already in use on this laptop. "
            "Set LOCAL_BOLT_PORT to a free port and try again."
        )

    procs: list[subprocess.Popen] = []
    try:
        for command in commands:
            kv("Command", " ".join(command))
            procs.append(subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL))
        deadline = time.monotonic() + OPEN_TIMEOUT_SECONDS
        while not all(port_in_use(port) for port in ports):
            for proc in procs:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"{proc.args[0]} exited with code "
                        f"{proc.returncode}.{failure_hint}"
                    )
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"The ports did not open within {OPEN_TIMEOUT_SECONDS} seconds."
                )
            time.sleep(0.25)
        kv("Local ports", "open, pids " + ", ".join(str(p.pid) for p in procs))
        yield
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print()
        print("Local ports closed.")


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
def ssh_access(target: str, user: str, key: str | None) -> Iterator[Access]:
    """Reach Neo4j on the VM through one SSH tunnel."""
    server = required_setting("SERVER_IP")
    base = local_bolt_port()
    remote_ports = SSH_BOLT_PORTS[target]
    ports = {remote: remote - BOLT_PORT + base for remote in remote_ports}
    clash = set(ports.values()) & set(remote_ports)
    if base != BOLT_PORT and clash:
        raise RuntimeError(
            f"LOCAL_BOLT_PORT={base} would reuse server port(s) "
            f"{sorted(clash)} for a different member. Pick another port."
        )

    use_ssh_pw = bool(os.environ.get("SSH_PW"))
    command = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes"]
    if use_ssh_pw:
        command += ["-o", "NumberOfPasswordPrompts=1"]
    if key:
        command += ["-i", key]
    for remote, local in ports.items():
        command += ["-L", f"{local}:localhost:{remote}"]
    command.append(f"{user}@{server}")
    hint = (
        " Check SSH_PW. If this is the first connection to the server, run ssh "
        "once by hand to accept its host key."
        if use_ssh_pw
        else ""
    )

    uri = f"{SSH_URI_SCHEME[target]}://localhost:{base}"
    kv("Server", f"{user}@{server}")
    kv("URI", uri)
    kv("SSH password", "from SSH_PW" if use_ssh_pw else "ssh prompts if needed")
    with askpass_env() as env, forwards([command], list(ports.values()), env, hint):
        yield Access(
            uri,
            port_resolver(ports) if target == "cluster" else None,
            len(remote_ports),
        )


def running_pods(namespace: str, selector: str) -> list[str]:
    result = subprocess.run(
        [
            "oc",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            selector,
            "--field-selector=status.phase=Running",
            "-o",
            "name",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"oc get pods failed: {result.stderr.strip()}")
    pods = [line.removeprefix("pod/") for line in result.stdout.split()]
    if not pods:
        raise RuntimeError(
            f"No running pods match {selector} in namespace {namespace}."
        )
    return pods


@contextlib.contextmanager
def oc_access() -> Iterator[Access]:
    """Reach Neo4j on OpenShift through one port forward per pod.

    This needs a logged-in oc, and OC_NAMESPACE and OC_POD_SELECTOR in .env.
    """
    namespace = required_setting("OC_NAMESPACE")
    selector = required_setting("OC_POD_SELECTOR")
    if not shutil.which("oc"):
        raise RuntimeError("The oc command is not installed on this laptop.")

    pods = running_pods(namespace, selector)
    base = local_bolt_port()
    ports = {pod: base + num * LOCAL_PORT_STEP for num, pod in enumerate(pods)}
    commands = [
        ["oc", "port-forward", "-n", namespace, f"pod/{pod}", f"{local}:{BOLT_PORT}"]
        for pod, local in ports.items()
    ]

    uri = f"neo4j://localhost:{base}"
    kv("Namespace", namespace)
    kv("Pods", ", ".join(pods))
    kv("URI", uri)
    with forwards(commands, list(ports.values())):
        yield Access(uri, host_resolver(ports), len(pods))
