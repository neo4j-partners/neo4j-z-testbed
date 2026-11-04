#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["neo4j>=5.28", "python-dotenv>=1.0"]
# ///
"""Write and read test data in Neo4j from your laptop.

Run it on your laptop from the root of this repository, not on the server:

    cp -n tests/.env.example tests/.env   # then set the values in tests/.env
    uv run tests/laptop-test.py           # VM cluster through an SSH tunnel
    uv run tests/laptop-test.py --target single
    uv run tests/laptop-test.py --via oc  # OpenShift through port forwards

The script loads .env from its own directory. Variables already set in your
shell take precedence over the file.

The script opens the tunnel or port forwards itself and closes them when it
finishes. LOCAL_BOLT_PORT is the laptop port for the first member. Each further
member uses 10 more than the last.
"""

import argparse
import functools
import random
import sys
import time
import uuid
from datetime import datetime, timezone

from neo4j import Driver, GraphDatabase, Session

import support
from access import Access, oc_access, ssh_access
from support import Check, kv, ms, neo4j_password, run_guarded, show_checks

LABEL = "LaptopTest"
DATABASE = "neo4j"
DATABASES = (DATABASE, "system")
TOTAL_STEPS = 8
SNIPPET_ROWS = 3
WORDS = [
    "graph",
    "node",
    "edge",
    "cluster",
    "raft",
    "leader",
    "follower",
    "bolt",
    "cypher",
    "index",
    "page",
    "cache",
    "heap",
    "replica",
    "primary",
    "routing",
    "bookmark",
    "commit",
    "write",
    "read",
    "shard",
    "store",
    "query",
]
section = functools.partial(support.section, total=TOTAL_STEPS)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


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


def show_connection(driver: Driver, members: int) -> list[Check]:
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
    kernel = next(rec for rec in records if rec["name"] == "Neo4j Kernel")
    edition = Check(
        "Version and edition",
        kernel["edition"] == "enterprise",
        f"{kernel['version']} {kernel['edition']}",
    )

    records, _, _ = driver.execute_query("SHOW SERVERS", database_="system")
    print()
    print("  SHOW SERVERS:")
    for num, rec in enumerate(records, start=1):
        print(f"    Server {num}")
        for key, value in rec.items():
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            print(f"      {key:<10} {value}")
    available = sum(
        rec["state"] == "Enabled" and rec["health"] == "Available" for rec in records
    )
    print()
    kv("Available servers", f"{available} of {len(records)}")
    servers = Check(
        "Servers",
        available == members == len(records),
        f"{available} of {members} enabled and available",
    )
    return [edition, servers]


def show_database(driver: Driver, database: str, members: int) -> bool:
    records, _, _ = driver.execute_query(
        "SHOW DATABASE $db "
        "YIELD serverID, address, role, writer, currentStatus, statusMessage",
        {"db": database},
        database_="system",
    )
    print(f"  Database '{database}':")
    online = 0
    for rec in records:
        # A member that is down has no address and may have no role.
        address = rec["address"] or "unavailable"
        role = rec["role"] or "-"
        if rec["currentStatus"] == "online":
            online += 1
            marker = "  <- writer" if rec["writer"] else ""
        else:
            marker = "  <- DOWN"
        print(
            f"    {address:<18} role={role:<10} status={rec['currentStatus']}{marker}"
        )
        if rec["currentStatus"] != "online":
            print(f"      server     {rec['serverID']}")
            print(f"      message    {rec['statusMessage'] or '-'}")
    writers = sum(bool(rec["writer"]) for rec in records)
    print()
    kv("Members online", f"{online} of {len(records)}")
    kv("Writers", writers)
    print()
    return online == members == len(records) and writers == 1


def show_topology(driver: Driver, members: int) -> Check:
    healthy = [
        database for database in DATABASES if show_database(driver, database, members)
    ]
    return Check(
        "Databases",
        len(healthy) == len(DATABASES),
        f"{len(healthy)} of {len(DATABASES)} online with one writer",
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
        description="Write and read test data in Neo4j from your laptop."
    )
    parser.add_argument(
        "--via",
        choices=["ssh", "oc"],
        default="ssh",
        help="How to reach Neo4j: ssh for the VM, oc for OpenShift (default: ssh).",
    )
    parser.add_argument(
        "--target",
        choices=["cluster", "single"],
        default="cluster",
        help="Install to test with --via ssh (default: cluster).",
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


def run_test(args: argparse.Namespace, access: Access, password: str) -> bool:
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    with GraphDatabase.driver(
        access.uri, auth=("neo4j", password), resolver=access.resolver
    ) as driver:
        section(
            3,
            "Connect",
            f"Connects the Neo4j Python driver to {access.uri}, reads the "
            "server version, and lists the servers with SHOW SERVERS.",
        )
        driver.verify_connectivity()
        checks = show_connection(driver, access.members)

        section(
            4,
            "Topology",
            "Shows where each database runs. The writer is the member that "
            "accepts writes for that database.",
        )
        checks.append(show_topology(driver, access.members))

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
                "Compares each row read back with the row written, field by field.",
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

    checks.append(
        Check(
            "Rows",
            len(written) == args.rows and matched == args.rows,
            f"{matched} of {args.rows} matched",
        )
    )
    passed = all(check.passed for check in checks)
    section(None, "Summary", f"Results for {run_id} on {access.uri}.")
    kv("Platform", args.via)
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
    show_checks(checks)
    print()
    kv("Result", "PASS" if passed else "FAIL")
    return passed


def run(args: argparse.Namespace) -> bool:
    if args.via == "oc" and args.target == "single":
        raise RuntimeError(
            "--via oc tests a cluster, so it cannot use --target single."
        )

    section(1, "Settings", "The values this run uses.")
    kv("Platform", args.via)
    kv("Target", args.target)
    kv("Rows / batch size", f"{args.rows} / {args.batch_size}")
    kv("Keep data", "yes" if args.keep else "no")
    password = neo4j_password()

    section(
        2,
        "Connection to Neo4j",
        "Forwards local ports on this laptop to the Bolt port of each member. "
        "The members are not open to the laptop, so this is the way in.",
    )
    if args.via == "oc":
        with oc_access() as access:
            return run_test(args, access, password)
    with ssh_access(args.target, args.ssh_user, args.ssh_key) as access:
        return run_test(args, access, password)


def main() -> int:
    args = parse_args()
    return run_guarded(lambda: run(args))


if __name__ == "__main__":
    sys.exit(main())
