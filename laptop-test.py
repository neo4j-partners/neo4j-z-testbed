#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["neo4j>=5.28"]
# ///
"""Write and read test data in Neo4j from your laptop through an SSH tunnel.

Run it on your laptop, not on the server:

    export SERVER_IP=<server-ip>
    export LOCAL_BOLT_PORT=17687         # optional, this is the default
    export NEO4J_PW='<your-password>'    # prompts if not set
    export SSH_PW='<ssh-password>'       # optional, ssh prompts if not set
    uv run laptop-test.py                # cluster, neo4j://localhost:17687
    uv run laptop-test.py --target single

The script opens the SSH tunnel itself and closes it when it finishes.
LOCAL_BOLT_PORT is the laptop end of the tunnel for the server's port 7687.
The cluster also uses LOCAL_BOLT_PORT + 10 and + 20 for members 2 and 3.
"""

import argparse
import contextlib
import getpass
import os
import random
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from neo4j import Address, Driver, GraphDatabase, Session
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

BOLT_PORTS = {"single": [7687], "cluster": [7687, 7697, 7707]}
DEFAULT_LOCAL_BOLT_PORT = 17687
URI_SCHEME = {"single": "bolt", "cluster": "neo4j"}
LABEL = "LaptopTest"
DATABASE = "neo4j"
TOTAL_STEPS = 8
WIDTH = 72
SNIPPET_ROWS = 3
ASKPASS_SCRIPT = """#!/bin/sh
# Answers ssh password and passphrase prompts from SSH_PW. Refuses any other
# prompt, such as the yes/no question for an unknown host key.
case "$1" in
  *assword*|*assphrase*) printf '%s\\n' "$SSH_PW" ;;
  *) exit 1 ;;
esac
"""
WORDS = (
    "graph node edge cluster raft leader follower bolt cypher index page cache "
    "heap replica primary routing bookmark commit write read shard store query"
).split()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def section(step: int | None, title: str, what: str) -> None:
    label = f"[{step}/{TOTAL_STEPS}] {title}" if step else title
    print()
    print("=" * WIDTH)
    print(label)
    print("=" * WIDTH)
    print(textwrap.fill(what, WIDTH))
    print()


def kv(label: str, value: object) -> None:
    print(f"  {label:<24} {value}")


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def snippet(row: dict) -> str:
    tags = ",".join(row["tags"])
    payload = truncate(row["payload"], 32)
    return (
        f"  seq={row['seq']:<4} name={row['name']:<14} value={row['value']:>9.3f} "
        f'tags=[{tags}] payload="{payload}" ({len(row["payload"])} chars)'
    )


def show_snippets(rows: list[dict]) -> None:
    for row in rows[:SNIPPET_ROWS]:
        print(snippet(row))
    if len(rows) > SNIPPET_ROWS:
        print(f"  ... {len(rows) - SNIPPET_ROWS} more rows")


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


# ---------------------------------------------------------------------------
# SSH tunnel
# ---------------------------------------------------------------------------


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
                    raise RuntimeError(
                        f"ssh exited with code {proc.returncode}.{hint}"
                    )
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "The SSH tunnel did not open within 30 seconds."
                    )
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


def tunnel_resolver(port_map: dict[int, int]):
    """Send the cluster's member addresses to the local ends of the tunnel.

    The cluster tells the driver to reach its members at localhost:7687,
    7697, and 7707. Those are server ports, so map each one to its local port.
    """

    def resolve(address: Address) -> list[Address]:
        local = port_map.get(address.port)
        return [Address(("localhost", local))] if local else [address]

    return resolve


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------


def make_rows(run_id: str, count: int) -> list[dict]:
    created = datetime.now(timezone.utc).isoformat()
    rows = []
    for seq in range(1, count + 1):
        payload = " ".join(random.choices(WORDS, k=random.randint(20, 60)))
        rows.append(
            {
                "run_id": run_id,
                "seq": seq,
                "name": f"item-{seq:05d}",
                "value": round(random.uniform(0, 10_000), 3),
                "tags": random.sample(WORDS, 2),
                "payload": payload,
                "created": created,
            }
        )
    return rows


def show_connection(driver: Driver) -> None:
    info = driver.get_server_info()
    kv("Connected to", info.address)
    kv("Server agent", info.agent)
    kv("Bolt protocol", ".".join(map(str, info.protocol_version)))
    records, _, _ = driver.execute_query(
        "CALL dbms.components() YIELD name, versions, edition "
        "RETURN name, versions[0] AS version, edition",
        database_="system",
    )
    for rec in records:
        kv("Neo4j", f"{rec['name']} {rec['version']} {rec['edition']}")

    records, _, _ = driver.execute_query("SHOW SERVERS", database_="system")
    print()
    print("  SHOW SERVERS:")
    for num, rec in enumerate(records, start=1):
        print(f"    Server {num}")
        for key, value in rec.items():
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            print(f"      {key:<10} {value}")
    available = sum(rec["health"] == "Available" for rec in records)
    print()
    kv("Available servers", f"{available} of {len(records)}")


def show_topology(driver: Driver) -> None:
    records, _, _ = driver.execute_query(
        "SHOW DATABASE $db YIELD address, role, writer, currentStatus",
        {"db": DATABASE},
        database_="system",
    )
    print(f"  Database '{DATABASE}':")
    for rec in records:
        writer = "  <- writer" if rec["writer"] else ""
        print(
            f"    {rec['address']:<18} role={rec['role']:<10} "
            f"status={rec['currentStatus']}{writer}"
        )


def write_rows(session: Session, rows: list[dict], batch_size: int) -> tuple:
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    created = 0
    servers = set()
    start = time.perf_counter()
    for num, batch in enumerate(batches, start=1):
        batch_start = time.perf_counter()
        summary = session.execute_write(
            lambda tx, b=batch: tx.run(
                f"UNWIND $rows AS row CREATE (n:{LABEL}) SET n = row", rows=b
            ).consume()
        )
        created += summary.counters.nodes_created
        servers.add(str(summary.server.address))
        print(
            f"  batch {num}/{len(batches)}  "
            f"{summary.counters.nodes_created} nodes  "
            f"{ms(time.perf_counter() - batch_start)}  "
            f"server={summary.server.address}"
        )
    return created, time.perf_counter() - start, servers


def read_rows(session: Session, run_id: str) -> tuple:
    def work(tx):
        result = tx.run(
            f"MATCH (n:{LABEL} {{run_id: $run_id}}) "
            "RETURN n {.*} AS row ORDER BY row.seq",
            run_id=run_id,
        )
        rows = [rec["row"] for rec in result]
        return rows, result.consume()

    start = time.perf_counter()
    rows, summary = session.execute_read(work)
    return rows, time.perf_counter() - start, str(summary.server.address)


def compare(written: list[dict], read: list[dict]) -> tuple[int, int, int]:
    read_by_seq = {row["seq"]: row for row in read}
    matched = sum(read_by_seq.get(row["seq"]) == row for row in written)
    missing = sum(row["seq"] not in read_by_seq for row in written)
    return matched, len(written) - matched - missing, missing


def delete_rows(driver: Driver, run_id: str) -> int:
    _, summary, _ = driver.execute_query(
        f"MATCH (n:{LABEL} {{run_id: $run_id}}) DELETE n",
        {"run_id": run_id},
        database_=DATABASE,
    )
    return summary.counters.nodes_deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write and read test data in Neo4j through an SSH tunnel."
    )
    parser.add_argument(
        "--target",
        choices=["cluster", "single"],
        default="cluster",
        help="Install to test (default: cluster).",
    )
    parser.add_argument(
        "--rows", type=int, default=100, help="Rows to write (default: 100)."
    )
    parser.add_argument(
        "--batch-size", type=int, default=25, help="Rows per write (default: 25)."
    )
    parser.add_argument(
        "--ssh-user", default="ubuntu", help="SSH user (default: ubuntu)."
    )
    parser.add_argument("--ssh-key", help="Private key for ssh -i, if needed.")
    parser.add_argument(
        "--keep", action="store_true", help="Keep the test data after the run."
    )
    return parser.parse_args()


def run_test(
    args: argparse.Namespace, uri: str, password: str, port_map: dict[int, int]
) -> bool:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    resolver = tunnel_resolver(port_map) if args.target == "cluster" else None

    with GraphDatabase.driver(
        uri, auth=("neo4j", password), resolver=resolver
    ) as driver:
        section(
            3,
            "Connect",
            f"Connects the Neo4j Python driver to {uri}, reads the server "
            "version, and lists the servers with SHOW SERVERS.",
        )
        driver.verify_connectivity()
        show_connection(driver)

        section(
            4,
            "Topology",
            f"Shows where the '{DATABASE}' database runs. The writer is the "
            "member that accepts writes.",
        )
        show_topology(driver)

        rows = make_rows(run_id, args.rows)
        written = read = []
        write_time = read_time = 0.0
        write_servers: set[str] = set()
        read_server = "-"
        deleted = 0
        try:
            # One session carries the write bookmark into the read, so the
            # read waits until it can see the writes, even on another member.
            with driver.session(database=DATABASE) as session:
                section(
                    5,
                    "Write",
                    f"Creates {args.rows} :{LABEL} nodes tagged run_id="
                    f"{run_id}, in batches of {args.batch_size}. Each "
                    "batch is one write transaction.",
                )
                print("  Sample of the rows being written:")
                show_snippets(rows)
                print()
                created, write_time, write_servers = write_rows(
                    session, rows, args.batch_size
                )
                written = rows
                print()
                kv("Nodes created", created)
                kv("Write time", ms(write_time))
                kv("Rows per second", f"{created / write_time:.0f}")

                section(
                    6,
                    "Read",
                    f"Reads back every node with run_id={run_id} in one read "
                    "transaction. On a cluster the driver may route it to a "
                    "member other than the writer.",
                )
                read, read_time, read_server = read_rows(session, run_id)
                print("  Sample of the rows read back:")
                show_snippets(read)
                print()
                kv("Rows read", len(read))
                kv("Read time", ms(read_time))
                kv("Served by", read_server)

            section(
                7,
                "Verify",
                "Compares each row read back with the row written, field by "
                "field.",
            )
            matched, different, missing = compare(written, read)
            kv("Rows matched", f"{matched} of {len(written)}")
            kv("Rows different", different)
            kv("Rows missing", missing)
        finally:
            if args.keep:
                section(
                    8,
                    "Clean up",
                    f"Skipped because of --keep. Delete the data later with: "
                    f"MATCH (n:{LABEL} {{run_id: '{run_id}'}}) DELETE n",
                )
            else:
                section(8, "Clean up", f"Deletes the nodes with run_id={run_id}.")
                deleted = delete_rows(driver, run_id)
                kv("Nodes deleted", deleted)

    passed = len(written) == args.rows and matched == args.rows
    section(None, "Summary", f"Results for {run_id} on {uri}.")
    kv("Target", args.target)
    kv("Rows written", len(written))
    kv("Rows read", len(read))
    kv("Rows matched", matched)
    kv("Rows different", different)
    kv("Rows missing", missing)
    kv("Nodes deleted", "kept (--keep)" if args.keep else deleted)
    kv("Write time", ms(write_time))
    kv("Read time", ms(read_time))
    kv("Writes served by", ", ".join(sorted(write_servers)))
    kv("Read served by", read_server)
    print()
    kv("Result", "PASS" if passed else "FAIL")
    return passed


def main() -> int:
    args = parse_args()
    server = os.environ.get("SERVER_IP")
    if not server:
        print("Set SERVER_IP first, for example: export SERVER_IP=<server-ip>")
        return 1

    try:
        base = int(os.environ.get("LOCAL_BOLT_PORT", DEFAULT_LOCAL_BOLT_PORT))
    except ValueError:
        print("LOCAL_BOLT_PORT must be a port number, for example 17687.")
        return 1
    remote_ports = BOLT_PORTS[args.target]
    port_map = {remote: remote - 7687 + base for remote in remote_ports}
    clash = set(port_map.values()) & set(remote_ports)
    if base != 7687 and clash:
        print(
            f"LOCAL_BOLT_PORT={base} would reuse server port(s) "
            f"{sorted(clash)} for a different member. Pick another port."
        )
        return 1
    uri = f"{URI_SCHEME[args.target]}://localhost:{base}"

    section(1, "Settings", "The values this run uses.")
    kv("Server", f"{args.ssh_user}@{server}")
    kv("Target", args.target)
    kv("URI", uri)
    kv(
        "Forwarded ports",
        ", ".join(f"{local} -> {remote}" for remote, local in port_map.items()),
    )
    kv("Rows / batch size", f"{args.rows} / {args.batch_size}")
    kv("Keep data", "yes" if args.keep else "no")
    kv(
        "SSH password",
        "from SSH_PW" if os.environ.get("SSH_PW") else "ssh prompts if needed",
    )
    password = os.environ.get("NEO4J_PW") or getpass.getpass(
        "  Password for neo4j: "
    )

    section(
        2,
        "SSH tunnel",
        "Forwards local ports on this laptop to the Bolt ports on the server. "
        "The server listens on 127.0.0.1 only, so the tunnel is the way in.",
    )
    try:
        with ssh_tunnel(server, args.ssh_user, args.ssh_key, port_map):
            passed = run_test(args, uri, password, port_map)
    except AuthError as err:
        print(f"\nLogin failed: {err.message}")
        return 1
    except ServiceUnavailable as err:
        print(f"\nCannot reach Neo4j through the tunnel: {err}")
        return 1
    except Neo4jError as err:
        print(f"\nNeo4j error {err.code}: {err.message}")
        return 1
    except RuntimeError as err:
        print(f"\n{err}")
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
