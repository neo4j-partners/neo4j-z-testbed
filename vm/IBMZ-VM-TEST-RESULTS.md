# Neo4j Enterprise on an IBM Z VM: test results

**Goal:** This testing validates the Neo4j EE IntelliGraph bundle that Neo4j is preparing for IBM. The bundle includes Neo4j Enterprise Edition and Graph Data Science. The testing sets a baseline of what works in this package.

These are the results of running Neo4j Enterprise Edition 2026.09.0 on an Ubuntu VM on IBM Z. The steps to repeat the tests are in the [README](../README.md).

| Test | Result |
| --- | --- |
| [Single node](#single-node-test-results) | Passed |
| [Three-member cluster](#cluster-test-results) | Passed |
| [Laptop test against the cluster](#laptop-test-results) | Passed |
| [Graph Data Science on the single node](#graph-data-science-test-results) | Passed after one Java VM crash |
| [Java VM crash](#java-vm-crash) | Open |

## Single node test results

The single node installed on IBM Z and passed its tests. The repository holds no recorded output for this run.

A rebuilt single node also passed `laptop-test.py --target single` on 2026-11-04. All 100 rows matched.

## Cluster test results

The three-member cluster installed on IBM Z and passed every test. The full output of the install and the laptop test is in [sample-output.md](sample-output.md).

### Test machine

- **Architecture:** The machine is a VM on IBM Z and reports `s390x`.
- **Operating system:** The machine runs Ubuntu 24.04.
- **Memory:** The machine has 4 GB of RAM. Each member ran with a 512 MB heap and a 128 MB page cache to fit in that space.
- **Disk:** The `/opt` directory had 94 GB free on an ext4 filesystem.
- **Java:** Java 21 was already installed and set as the default.
- **Network:** All members listened on `127.0.0.1` only.
- **License:** The test used the 30-day evaluation license.

### What passed

- **Cluster formation:** All three servers reached the `Enabled` and `Available` state.
- **Databases:** The `neo4j` and `system` databases came online on all three members. Each member hosted both databases as a primary.
- **Writer election:** The cluster picked one writer for each database. Member 2 led `neo4j` and member 3 led `system`.
- **Replication:** The test wrote a node through member 1. Members 2 and 3 both returned that node when read directly.
- **Failover:** The test stopped member 2. Writes still worked with two of three members running. After restart, member 2 rejoined and returned the node written while it was down.

### Warnings seen

- **Unsupported architecture:** The script warned that `s390x` is outside Neo4j's documented support. The install continued and worked.
- **Low memory:** The script warned that 4 GB is below the 8 GB it recommends for three members. The smaller memory settings were enough for these tests. Larger data sets need more memory.
- **Java incubator module:** Each `neo4j-admin` command printed `WARNING: Using incubator modules: jdk.incubator.vector`. Java prints this because Neo4j loads the incubating Java Vector API. The warning did not affect any test.

## Laptop test results

`laptop-test.py` ran from a laptop against the cluster and passed. It reached the cluster through an SSH tunnel.

- **Connection:** The Python driver connected to Neo4j 2026.09.0 Enterprise over Bolt protocol 6.1.
- **Cluster health:** All three servers were `Enabled` and `Available`. The `neo4j` database was online on all three members.
- **Writer:** Member 3 was the writer for `neo4j` during this run. The writer moved off member 2 when the failover test stopped it.
- **Write:** The test wrote 100 nodes in 4 batches of 25. The driver sent every batch to the writer. The writes took 2,145 ms in total, about 47 rows per second.
- **Read:** The test read all 100 nodes back in one transaction. The driver sent the read to member 2, which is not the writer. The read took 1,888 ms.
- **Verify:** All 100 rows matched what was written, field by field. No rows were different or missing.
- **Clean up:** The test deleted all 100 nodes.
- **Timing:** These times include the round trip through the SSH tunnel. They do not measure Neo4j performance on IBM Z.

## Graph Data Science test results

The Graph Data Science plugin loaded on IBM Z, and `gds-test.py` passed on a small graph and a generated graph. The Java VM crashed during the first run on the small graph. The test passed when it was run again after a restart with no configuration change. The [Java VM crash](#java-vm-crash) section has the details.

The test ran from a laptop through an SSH tunnel. IBM Z is big-endian, so a plain count could miss a byte order fault. The laptop computed the expected answers in pure Python, and the test compared them with the GDS results.

### GDS test setup

- **Machine:** The test used the same VM as the cluster test, with Java 21.
- **Neo4j:** A single node ran with a 2 GB heap and a 512 MB page cache.
- **GDS version:** The plugin was version 2026.09.0, from the `products/` directory of the Neo4j tarball.
- **GDS edition:** GDS reported its edition as `Unlicensed`.
- **Resources:** GDS reported 2 available CPUs, a 2,048 MiB heap, and 493 procedures.

### GDS results

| Check | Small graph | Generated graph, seed 42 |
| --- | --- | --- |
| Nodes | 8 | 20,000 |
| Relationships | 12 | 100,000 |
| Projection time | 1,241 ms | 854 ms |
| WCC components | 2 | 1 |
| WCC time | 582 ms | 7,887 ms |
| PageRank largest difference | 1.58e-06 | 3.79e-06 |
| PageRank time | 897 ms | 10,264 ms |
| Dijkstra path length | 4 nodes | 14 nodes |
| Dijkstra cost | 4.000000000 | 50.865721903 |
| Dijkstra time | 900 ms | 546 ms |
| Scores written back | 8 | 20,000 |
| Write back iterations | 88 | 86 |
| Write back time | 777 ms | 1,542 ms |
| Result | PASS | PASS |

- **WCC:** Every group of nodes matched the groups computed in Python.
- **PageRank:** Every score was within the allowed difference of 1.00e-05. The highest scoring node matched.
- **Dijkstra:** The path and its cost matched exactly as printed, to 9 decimal places.
- **Write back:** PageRank converged, and the scores read back from the database stayed within the allowed difference.
- **Clean up:** Each run ended with no graphs left in memory and no test nodes left.
- **Stability:** The generated graph ran once. Neo4j stayed up and wrote no new crash report during that run.
- **Timing:** These times include the round trip through the SSH tunnel. They do not measure GDS performance on IBM Z.

### Not tested

- **Cluster:** GDS ran on the single node only. GDS on a cluster needs a Secondary member and an Enterprise license.
- **Other algorithms:** The test covered WCC, PageRank, and Dijkstra. It did not cover other GDS algorithms.

## Java VM crash

The Java VM crashed three times on 2026-11-04, within about 42 minutes. It crashed on cluster member 3, then cluster member 2, then the single node. The cause is not confirmed.

| Time (UTC) | Instance | Heap | Uptime | Method being compiled | Memory free |
| --- | --- | --- | --- | --- | --- |
| 03:58:01 | Cluster member 3 | 512 MB | About 29 minutes | `GossipMemberStateMarshaller::unmarshall` | About 538 MB |
| 04:31:11 | Cluster member 2 | 512 MB | 6 minutes 17 seconds | `LighthouseMemberIdMarshaller::unmarshall` | About 604 MB |
| 04:39:58 | Single node | 2 GB | 76 seconds | `BitmapIndexedSetNode::removed` | About 1.1 GB |

- **Failure:** Each time, the Java VM stopped with a `SIGSEGV` in its C2 compiler thread, during the `PhaseOutput` stage.
- **Crash location:** The first two crashes stopped in `PhaseOutput::Process_OopMap_Node`. The third stopped in `PhaseOutput::FillLocArray`, which `Process_OopMap_Node` calls.
- **Java version:** The VM was OpenJDK 21.0.12 on `linux-s390x`.
- **Pattern:** The three compiled methods are unrelated, and none of them is GDS code. The crash hit a cluster and a single node, with both small and larger heaps. It does not look specific to GDS, clustering, or low memory.
- **Memory:** No out-of-memory kill was seen. The machine had no swap.
- **Timing:** Neo4j passed the same tests after restarts, so the crash does not appear on every run. The first crash happened with no laptop test running.
- **Known bugs:** A web search found no published JDK bug with this signature.
- **Recovery:** Member 3 and the single node started again after a manual `systemctl start`. On the single node, the `Restart=on-abnormal` setting did not restart the service after the crash.
- **Evidence:** The Java crash reports and compiler replay data are in [crash-reports](crash-reports/).

### Java 25 comparison

The same test loop ran on Java 21 and on Java 25 on the single node, with GDS installed. Each round restarted Neo4j, then ran `gds-test.py`, `gds-test.py --rels 100000`, and `laptop-test.py --target single`.

| | OpenJDK 21.0.12 | OpenJDK 25.0.4.1 |
| --- | --- | --- |
| Rounds | 5 | 10 |
| Rounds with all three tests passing | 5 | 10 |
| New crash reports | 0 | 0 |
| Median WCC time, generated graph | 7,521 ms | 6,545 ms |
| Median PageRank time, generated graph | 10,334 ms | 10,512 ms |

- **Java 25:** Neo4j and GDS ran correctly on Java 25 on IBM Z, and the timing was about the same as Java 21.
- **Crash fix:** This loop does not show that Java 25 fixes the crash. The loop did not reproduce the crash on Java 21 either, so a clean run on Java 25 is weak evidence.
- **Compiler replay:** The three crashing compiles were replayed on Java 21, twice each, and none crashed. The classes that Neo4j generates at runtime were missing, and the output does not confirm that the compiles finished. This is a weak hint that the crash is not simply deterministic.
