# Neo4j Enterprise on an IBM Z VM: test results

These are the results of running Neo4j Enterprise Edition 2026.09.0 on an Ubuntu VM on IBM Z. The steps to repeat the tests are in the [README](../README.md).

| Test | Result |
| --- | --- |
| [Single node](#single-node-test-results) | Passed |
| [Three-member cluster](#cluster-test-results) | Passed |
| [Laptop test against the cluster](#laptop-test-results) | Passed |
| [Member 3 crash](#java-vm-crash-on-member-3) | Open |

## Single node test results

The single node installed on IBM Z and passed its tests. The repository holds no recorded output for this run.

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

### Java VM crash on member 3

Member 3 crashed on 2026-11-04, about 29 minutes after it started on a fresh cluster install. No laptop test was running at the time. The cause is not confirmed, and it is not yet known whether the crash repeats.

- **Failure:** The Java VM stopped with a `SIGSEGV` in its C2 compiler thread, at `PhaseOutput::Process_OopMap_Node`.
- **Compile task:** C2 was compiling `com.neo4j.lighthouse.gossip.memberset.protocolclient.GossipMemberStateMarshaller::unmarshall`.
- **Java version:** The VM was OpenJDK 21.0.12 on `linux-s390x`.
- **Memory:** The kernel logged no out-of-memory kill. The machine had about 538 MB free and no swap.
- **Recovery:** Member 3 started again after a manual `systemctl start neo4j@3`.
- **Evidence:** The Java crash report and compiler replay data are in [crash-reports](crash-reports/).

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
