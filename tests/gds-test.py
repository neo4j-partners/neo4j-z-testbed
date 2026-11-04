#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["neo4j>=5.28", "python-dotenv>=1.0"]
# ///
"""Check Graph Data Science results on a single Neo4j node from your laptop.

Run it on your laptop from the root of this repository, not on the server. The
node must be installed with ENABLE_GDS=yes:

    uv run tests/gds-test.py                 # small graph with known answers
    uv run tests/gds-test.py --rels 100000   # generated graph, for load

The script loads .env from its own directory and opens its own SSH tunnel.

It computes every expected answer in Python, on this laptop, and compares
those answers with the results from GDS. A failed comparison means GDS returned
a wrong answer, even if every query ran without an error.
"""

import argparse
import heapq
import random
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import ServiceUnavailable

import support
from access import ssh_access
from support import Check, kv, ms, neo4j_password, run_guarded, show_checks

DATABASE = "neo4j"
LABEL = "GdsTest"
REL_TYPE = "GDS_TEST_LINK"
INDEX = "gds_test_seq"
SCORE_PROPERTY = "pagerank"
RELATIONSHIP_PROJECTION = {REL_TYPE: {"properties": "cost"}}
TOTAL_STEPS = 10
BATCH_SIZE = 5_000
SEED = 42
NODES_PER_REL = 0.2
TOP_SCORES = 3

DAMPING_FACTOR = 0.85
MAX_ITERATIONS = 100
GDS_TOLERANCE = 1e-7
REFERENCE_TOLERANCE = 1e-10
SCORE_TOLERANCE = 1e-5
COST_TOLERANCE = 1e-9
PAGERANK_CONFIG = {
    "dampingFactor": DAMPING_FACTOR,
    "maxIterations": MAX_ITERATIONS,
    "tolerance": GDS_TOLERANCE,
}
SYS_INFO_KEYS = (
    "gdsVersion",
    "gdsEdition",
    "neo4jVersion",
    "availableCPUs",
    "physicalCPUs",
    "heapMax",
)

# Nodes 0 to 4 form one group with node 0 as the hub. Nodes 5 to 7 form a
# second group. The direct link from 1 to 3 costs more than the path through 2.
SMALL_NODE_COUNT = 8
SMALL_RELS = [
    (1, 0, 1.0),
    (2, 0, 1.0),
    (3, 0, 1.0),
    (4, 0, 1.0),
    (0, 1, 1.0),
    (1, 2, 1.0),
    (2, 3, 2.5),
    (1, 3, 5.0),
    (3, 4, 0.5),
    (5, 6, 1.0),
    (6, 7, 1.0),
    (7, 5, 1.0),
]

Rel = tuple[int, int, float]


def section(step: int | None, title: str, what: str) -> None:
    support.section(step, title, what, total=TOTAL_STEPS)


@dataclass(frozen=True)
class Dataset:
    description: str
    node_count: int
    rels: list[Rel]

    @property
    def source(self) -> int:
        return self.rels[0][0]


def small_dataset() -> Dataset:
    return Dataset("small graph", SMALL_NODE_COUNT, SMALL_RELS)


def generated_dataset(rel_count: int) -> Dataset:
    """Build a repeatable random graph with no self loops or duplicate links."""
    rng = random.Random(SEED)
    node_count = max(int(rel_count * NODES_PER_REL), 2)
    pairs: set[tuple[int, int]] = set()
    while len(pairs) < rel_count:
        start, end = rng.randrange(node_count), rng.randrange(node_count)
        if start != end:
            pairs.add((start, end))
    rels = [(start, end, rng.uniform(0.1, 10.0)) for start, end in sorted(pairs)]
    rng.shuffle(rels)
    return Dataset(f"generated graph, seed {SEED}", node_count, rels)


# ---------------------------------------------------------------------------
# Expected answers, computed in Python
# ---------------------------------------------------------------------------


def expected_components(node_count: int, rels: list[Rel]) -> set[frozenset[int]]:
    parent = list(range(node_count))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for start, end, _ in rels:
        parent[find(start)] = find(end)
    groups: dict[int, set[int]] = defaultdict(set)
    for node in range(node_count):
        groups[find(node)].add(node)
    return {frozenset(group) for group in groups.values()}


def expected_pagerank(node_count: int, rels: list[Rel]) -> list[float]:
    """Run PageRank to convergence, with no scaling of the scores.

    GDS starts each node at 1 - d, and each node then scores 1 - d plus d times
    the share it receives from its neighbors. Nodes with no outgoing links pass
    nothing on.
    """
    out_degree = [0] * node_count
    for start, _, _ in rels:
        out_degree[start] += 1
    base = 1 - DAMPING_FACTOR
    scores = [base] * node_count
    while True:
        received = [0.0] * node_count
        for start, end, _ in rels:
            received[end] += scores[start] / out_degree[start]
        updated = [base + DAMPING_FACTOR * value for value in received]
        change = max(abs(new - old) for new, old in zip(updated, scores))
        scores = updated
        if change < REFERENCE_TOLERANCE:
            return scores


def expected_shortest_path(
    node_count: int, rels: list[Rel], source: int
) -> tuple[list[int], float]:
    """Return the path from source to its farthest reachable node, and its cost."""
    neighbors: list[list[tuple[int, float]]] = [[] for _ in range(node_count)]
    for start, end, cost in rels:
        neighbors[start].append((end, cost))

    distance = {source: 0.0}
    previous: dict[int, int] = {}
    queue = [(0.0, source)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > distance[node]:
            continue
        for neighbor, step_cost in neighbors[node]:
            total = cost + step_cost
            if total < distance.get(neighbor, float("inf")):
                distance[neighbor] = total
                previous[neighbor] = node
                heapq.heappush(queue, (total, neighbor))

    target = max(distance, key=distance.__getitem__)
    path = [target]
    while path[-1] != source:
        path.append(previous[path[-1]])
    return path[::-1], distance[target]


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def batches(rows: list, size: int) -> Iterable[list]:
    return (rows[i : i + size] for i in range(0, len(rows), size))


def count_nodes(driver: Driver) -> int:
    records, _, _ = driver.execute_query(
        f"MATCH (n:{LABEL}) RETURN count(n) AS count", database_=DATABASE
    )
    return records[0]["count"]


def remove_data(driver: Driver) -> None:
    with driver.session(database=DATABASE) as session:
        session.run(
            f"MATCH (n:{LABEL}) CALL (n) {{ DETACH DELETE n }} "
            "IN TRANSACTIONS OF 2000 ROWS"
        ).consume()
    driver.execute_query(f"DROP INDEX {INDEX} IF EXISTS", database_=DATABASE)


def create_data(driver: Driver, dataset: Dataset) -> None:
    driver.execute_query(
        f"CREATE INDEX {INDEX} IF NOT EXISTS FOR (n:{LABEL}) ON (n.seq)",
        database_=DATABASE,
    )
    driver.execute_query("CALL db.awaitIndexes(300)", database_=DATABASE)
    for seqs in batches(list(range(dataset.node_count)), BATCH_SIZE):
        driver.execute_query(
            f"UNWIND $seqs AS seq CREATE (:{LABEL} {{seq: seq}})",
            {"seqs": seqs},
            database_=DATABASE,
        )
    for rels in batches(dataset.rels, BATCH_SIZE):
        driver.execute_query(
            "UNWIND $rels AS rel "
            f"MATCH (a:{LABEL} {{seq: rel[0]}}), (b:{LABEL} {{seq: rel[1]}}) "
            f"CREATE (a)-[:{REL_TYPE} {{cost: rel[2]}}]->(b)",
            {"rels": [list(rel) for rel in rels]},
            database_=DATABASE,
        )


# ---------------------------------------------------------------------------
# GDS steps
# ---------------------------------------------------------------------------


def show_gds(driver: Driver) -> str:
    records, _, _ = driver.execute_query(
        "RETURN gds.version() AS version", database_=DATABASE
    )
    version = records[0]["version"]
    kv("Connected to", driver.get_server_info().address)
    kv("Server agent", driver.get_server_info().agent)
    kv("GDS version", version)
    records, _, _ = driver.execute_query(
        "CALL gds.debug.sysInfo() YIELD key, value RETURN key, value",
        database_=DATABASE,
    )
    info = {rec["key"]: rec["value"] for rec in records}
    for key in SYS_INFO_KEYS:
        if key in info:
            kv(key, info[key])
    records, _, _ = driver.execute_query(
        "CALL gds.list() YIELD name RETURN count(name) AS count", database_=DATABASE
    )
    kv("GDS procedures", records[0]["count"])
    return version


def project(driver: Driver, graph: str, dataset: Dataset) -> Check:
    records, _, _ = driver.execute_query(
        "CALL gds.graph.project.estimate($label, $rels) "
        "YIELD requiredMemory RETURN requiredMemory",
        {"label": LABEL, "rels": RELATIONSHIP_PROJECTION},
        database_=DATABASE,
    )
    kv("Estimated memory", records[0]["requiredMemory"])
    start = time.perf_counter()
    records, _, _ = driver.execute_query(
        "CALL gds.graph.project($graph, $label, $rels) "
        "YIELD nodeCount, relationshipCount "
        "RETURN nodeCount, relationshipCount",
        {"graph": graph, "label": LABEL, "rels": RELATIONSHIP_PROJECTION},
        database_=DATABASE,
    )
    nodes, rels = records[0]["nodeCount"], records[0]["relationshipCount"]
    kv("Projected nodes", nodes)
    kv("Projected relationships", rels)
    kv("Time", ms(time.perf_counter() - start))
    passed = (nodes, rels) == (dataset.node_count, len(dataset.rels))
    return Check("Projection", passed, f"{nodes} nodes, {rels} relationships")


def run_wcc(driver: Driver, graph: str, dataset: Dataset) -> Check:
    expected = expected_components(dataset.node_count, dataset.rels)
    start = time.perf_counter()
    records, _, _ = driver.execute_query(
        "CALL gds.wcc.stream($graph) YIELD nodeId, componentId "
        "RETURN gds.util.asNode(nodeId).seq AS seq, componentId",
        {"graph": graph},
        database_=DATABASE,
    )
    elapsed = time.perf_counter() - start
    groups: dict[int, set[int]] = defaultdict(set)
    for rec in records:
        groups[rec["componentId"]].add(rec["seq"])
    found = {frozenset(group) for group in groups.values()}
    kv("Components found", len(found))
    kv("Components expected", len(expected))
    kv("Largest component", max(map(len, found)))
    kv("Time", ms(elapsed))
    return Check(
        "WCC",
        found == expected,
        f"{len(found)} components, expected {len(expected)}",
    )


def largest_difference(found: dict[int, float], expected: list[float]) -> float:
    if set(found) != set(range(len(expected))):
        return float("inf")
    return max(abs(score - expected[seq]) for seq, score in found.items())


def run_pagerank(driver: Driver, graph: str, expected: list[float]) -> Check:
    start = time.perf_counter()
    records, _, _ = driver.execute_query(
        "CALL gds.pageRank.stream($graph, $config) YIELD nodeId, score "
        "RETURN gds.util.asNode(nodeId).seq AS seq, score",
        {"graph": graph, "config": PAGERANK_CONFIG},
        database_=DATABASE,
    )
    elapsed = time.perf_counter() - start
    found = {rec["seq"]: rec["score"] for rec in records}
    ranked = sorted(found, key=found.__getitem__, reverse=True)
    print("  Highest scores:")
    for seq in ranked[:TOP_SCORES]:
        print(f"    node {seq:<8} GDS {found[seq]:.7f}  Python {expected[seq]:.7f}")
    print()
    difference = largest_difference(found, expected)
    kv("Largest difference", f"{difference:.2e}")
    kv("Allowed difference", f"{SCORE_TOLERANCE:.2e}")
    kv("Time", ms(elapsed))
    top_expected = max(range(len(expected)), key=expected.__getitem__)
    passed = difference <= SCORE_TOLERANCE and ranked[0] == top_expected
    return Check(
        "PageRank",
        passed,
        f"top node {ranked[0]}, largest difference {difference:.2e}",
    )


def run_dijkstra(driver: Driver, graph: str, dataset: Dataset) -> Check:
    source = dataset.source
    path, cost = expected_shortest_path(dataset.node_count, dataset.rels, source)
    start = time.perf_counter()
    records, _, _ = driver.execute_query(
        f"MATCH (source:{LABEL} {{seq: $source}}), (target:{LABEL} {{seq: $target}}) "
        "CALL gds.shortestPath.dijkstra.stream($graph, {"
        "sourceNode: source, targetNode: target, "
        "relationshipWeightProperty: 'cost'}) "
        "YIELD totalCost, nodeIds "
        "RETURN totalCost, [n IN gds.util.asNodes(nodeIds) | n.seq] AS path",
        {"graph": graph, "source": source, "target": path[-1]},
        database_=DATABASE,
    )
    elapsed = time.perf_counter() - start
    if not records:
        return Check("Dijkstra", False, f"no path from {source} to {path[-1]}")
    found_path, found_cost = records[0]["path"], records[0]["totalCost"]
    kv("Path found", " -> ".join(map(str, found_path)))
    kv("Path expected", " -> ".join(map(str, path)))
    kv("Cost found", f"{found_cost:.9f}")
    kv("Cost expected", f"{cost:.9f}")
    kv("Time", ms(elapsed))
    passed = found_path == path and abs(found_cost - cost) <= COST_TOLERANCE
    return Check("Dijkstra", passed, f"{len(found_path)} nodes, cost {found_cost:.6f}")


def write_scores(
    driver: Driver, graph: str, dataset: Dataset, expected: list[float]
) -> Check:
    start = time.perf_counter()
    records, _, _ = driver.execute_query(
        "CALL gds.pageRank.write($graph, $config) "
        "YIELD nodePropertiesWritten, ranIterations, didConverge "
        "RETURN nodePropertiesWritten, ranIterations, didConverge",
        {
            "graph": graph,
            "config": {**PAGERANK_CONFIG, "writeProperty": SCORE_PROPERTY},
        },
        database_=DATABASE,
    )
    elapsed = time.perf_counter() - start
    written = records[0]["nodePropertiesWritten"]
    iterations = records[0]["ranIterations"]
    converged = records[0]["didConverge"]
    records, _, _ = driver.execute_query(
        f"MATCH (n:{LABEL}) RETURN n.seq AS seq, n.{SCORE_PROPERTY} AS score",
        database_=DATABASE,
    )
    found = {rec["seq"]: rec["score"] for rec in records}
    difference = largest_difference(found, expected)
    kv("Properties written", written)
    kv("Iterations", iterations)
    kv("Converged", converged)
    kv("Largest difference", f"{difference:.2e}")
    kv("Time", ms(elapsed))
    passed = (
        written == dataset.node_count and converged and difference <= SCORE_TOLERANCE
    )
    return Check(
        "Write back", passed, f"{written} scores, largest difference {difference:.2e}"
    )


def clean_up(driver: Driver, graph: str) -> Check:
    driver.execute_query(
        "CALL gds.graph.drop($graph, false) YIELD graphName RETURN graphName",
        {"graph": graph},
        database_=DATABASE,
    )
    remove_data(driver)
    records, _, _ = driver.execute_query(
        "CALL gds.graph.list() YIELD graphName RETURN count(graphName) AS count",
        database_=DATABASE,
    )
    graphs, nodes = records[0]["count"], count_nodes(driver)
    kv("Graphs left in memory", graphs)
    kv("Test nodes left", nodes)
    return Check(
        "Clean up", graphs == 0 and nodes == 0, f"{graphs} graphs, {nodes} nodes"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_steps(
    driver: Driver, graph: str, dataset: Dataset, expected: list[float]
) -> Iterator[Check]:
    section(
        5,
        "Project",
        "Estimates the memory for the graph, then loads the nodes and "
        "relationships from the store into GDS memory.",
    )
    yield project(driver, graph, dataset)

    section(
        6,
        "WCC",
        "Finds the connected groups of nodes and compares every group with "
        "the groups computed in Python.",
    )
    yield run_wcc(driver, graph, dataset)

    section(
        7,
        "PageRank",
        "Scores every node and compares each score with PageRank computed in "
        "Python. These are floating point results, so they show byte order "
        "faults that a count would miss.",
    )
    yield run_pagerank(driver, graph, expected)

    section(
        8,
        "Dijkstra",
        f"Finds the cheapest path from node {dataset.source} to the farthest "
        "node it reaches, and compares the path and its cost.",
    )
    yield run_dijkstra(driver, graph, dataset)

    section(
        9,
        "Write back",
        f"Runs PageRank in write mode, which stores each score in the "
        f"'{SCORE_PROPERTY}' property. Then reads the scores from the database.",
    )
    yield write_scores(driver, graph, dataset, expected)


def run_test(uri: str, password: str, dataset: Dataset) -> bool:
    graph = f"gds-test-{uuid.uuid4().hex[:8]}"
    checks: list[Check] = []

    # The first run queries a label that does not exist yet. That is expected.
    with GraphDatabase.driver(
        uri, auth=("neo4j", password), notifications_min_severity="OFF"
    ) as driver:
        section(
            3,
            "Check GDS",
            "Confirms that Neo4j loaded the plugin, and shows what GDS reports "
            "about this machine.",
        )
        driver.verify_connectivity()
        version = show_gds(driver)

        section(
            4,
            "Create test data",
            f"Removes any :{LABEL} nodes left by an earlier run, then creates "
            f"the {dataset.description}. Computes the expected answers in "
            "Python.",
        )
        leftover = count_nodes(driver)
        kv("Nodes from earlier runs", leftover)
        if leftover:
            remove_data(driver)
        start = time.perf_counter()
        expected = expected_pagerank(dataset.node_count, dataset.rels)
        kv("Python answers", ms(time.perf_counter() - start))
        start = time.perf_counter()
        create_data(driver, dataset)
        kv("Nodes created", dataset.node_count)
        kv("Relationships created", len(dataset.rels))
        kv("Time", ms(time.perf_counter() - start))

        server_up = True
        try:
            for check in run_steps(driver, graph, dataset, expected):
                checks.append(check)
                print()
                kv("Check", "PASS" if check.passed else "FAIL")
        except ServiceUnavailable:
            server_up = False
            print("  Neo4j stopped responding.")
            checks.append(Check("Server", False, "Neo4j stopped responding"))
        finally:
            if server_up:
                section(
                    10,
                    "Clean up",
                    f"Drops the in-memory graph and deletes the :{LABEL} nodes.",
                )
                checks.append(clean_up(driver, graph))

    passed = all(check.passed for check in checks)
    section(None, "Summary", f"Results for {dataset.description}, graph {graph}.")
    kv("GDS version", version)
    kv("Nodes", dataset.node_count)
    kv("Relationships", len(dataset.rels))
    print()
    show_checks(checks)
    print()
    kv("Result", "PASS" if passed else "FAIL")
    return passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Graph Data Science results through an SSH tunnel."
    )
    parser.add_argument(
        "--rels",
        type=int,
        help="Use a generated graph with this many relationships, not the small "
        "graph. It has one node for every five relationships.",
    )
    parser.add_argument(
        "--ssh-user", default="ubuntu", help="SSH user (default: ubuntu)."
    )
    parser.add_argument("--ssh-key", help="Private key for ssh -i, if needed.")
    return parser.parse_args()


def run(args: argparse.Namespace) -> bool:
    dataset = generated_dataset(args.rels) if args.rels else small_dataset()

    section(1, "Settings", "The values this run uses.")
    kv("Graph", dataset.description)
    password = neo4j_password()

    section(
        2,
        "SSH tunnel",
        "Forwards a local port on this laptop to the Bolt port on the server.",
    )
    with ssh_access("single", args.ssh_user, args.ssh_key) as access:
        return run_test(access.uri, password, dataset)


def main() -> int:
    args = parse_args()
    return run_guarded(lambda: run(args))


if __name__ == "__main__":
    sys.exit(main())
