# Neo4j Enterprise on IBM Z: testing and validation

**Goal:** This testing validates the Neo4j EE IntelliGraph bundle that Neo4j is preparing for IBM. The bundle includes Neo4j Enterprise Edition and Graph Data Science. The testing sets a baseline of what works in this package.

This repository tests whether Neo4j Enterprise Edition 2026.09.0 installs and runs on IBM Z. It holds the install scripts, the test tools, and the results, so you can repeat each test on your own machine.

Neo4j documents support only for x86_64 and ARM64 CPUs. IBM Z uses the `s390x` architecture, so it is outside that list. These tests show what works in practice. They are not a statement of support from Neo4j.

The testing covers these deployments:

- **VM single node:** One standalone Neo4j instance runs on an Ubuntu VM. This is the quickest way to check Java, the tarball, licensing, and networking.
- **VM cluster:** Three Neo4j members run on one Ubuntu VM. This shows cluster formation, replication, and failover.
- **OpenShift:** Testing on IBM Z OpenShift with the Neo4j Kubernetes operator is planned next.

## Contents

- [Test results](#test-results)
- [What is in this repository](#what-is-in-this-repository)
- [VM deployment](#vm-deployment)
  - [Requirements](#requirements)
  - [Prepare the server](#prepare-the-server)
  - [Single node](#single-node)
  - [Three-member cluster](#three-member-cluster)
  - [Reference](#reference)
- [OpenShift deployment (planned)](#openshift-deployment-planned)
- [References](#references)

## Test results

The VM tests passed on IBM Z, including a laptop test against the cluster and a Graph Data Science test on the single node. The test machine, what passed, and the warnings seen are in [IBMZ-VM-TEST-RESULTS.md](vm/IBMZ-VM-TEST-RESULTS.md).

One issue is open. The Java VM crashed three times on Java 21, on two cluster members and on the single node. The crash does not appear on every run, and the cause is not confirmed. The [crash details](vm/IBMZ-VM-TEST-RESULTS.md#java-vm-crash) are in the same file.

The single node also passed these tests on Java 25. That run does not show that Java 25 fixes the crash, as the [Java 25 comparison](vm/IBMZ-VM-TEST-RESULTS.md#java-25-comparison) explains.

| Deployment | Setup | Status |
| --- | --- | --- |
| VM | Single node | [Passed](vm/IBMZ-VM-TEST-RESULTS.md#single-node-test-results) |
| VM | Three-member cluster | [Passed](vm/IBMZ-VM-TEST-RESULTS.md#cluster-test-results) |
| VM | Graph Data Science on the single node | [Passed after one Java VM crash](vm/IBMZ-VM-TEST-RESULTS.md#graph-data-science-test-results) |
| OpenShift | Neo4j Kubernetes operator | Planned |

## What is in this repository

Two interactive scripts install Neo4j Enterprise Edition 2026.09.0 on a single Ubuntu server. One installs a single node. The other installs a three-member cluster, with all members on the same machine.

| File | Purpose |
| --- | --- |
| `vm/install-single.sh` | Installs one standalone node. Run it first to check Java, the tarball, licensing, and networking. |
| `vm/install-cluster.sh` | Installs a three-member cluster on one machine. It can also clean up earlier installs. |
| `vm/cluster.md` | The same cluster setup as manual steps, with one command per code block. |
| `tests/laptop-test.py` | Runs from your laptop. Writes test data, reads it back, and checks it, on the VM or on OpenShift. |
| `tests/gds-test.py` | Runs from your laptop. Checks Graph Data Science results on the VM single node against answers computed in Python. |
| `tests/access.py` | Opens the way from your laptop to Neo4j: an SSH tunnel for the VM, or `oc` port forwards for OpenShift. |
| `tests/support.py` | Output, settings, and error handling shared by the test scripts. |
| `tests/.env.example` | Sample settings for the test scripts. Copy it to `tests/.env`. |
| `vm/IBMZ-VM-TEST-RESULTS.md` | Results of the VM tests on IBM Z. |
| `vm/crash-reports/` | Java crash reports and compiler replay data from the Java VM crashes. |
| `vm/sample-output.md` | Full output from the cluster install and the laptop test on IBM Z, with addresses and the password redacted. |
| `openshift/coding-agent-guide.md` | Instructions for a coding agent to build and run the OpenShift tests. |
| `openshift/IBMZ-OPENSHIFT-TEST-RESULTS.md` | Template for the OpenShift test results on IBM Z. |

Both scripts install from the Neo4j tarball, not the Debian package. The Debian package supports only one instance per machine, so it cannot host three cluster members.

## VM deployment

### Requirements

- Ubuntu Server 22.04 or 24.04. Ubuntu 22.04 is deprecated as of Neo4j 2026.05.
- Root access or a user with `sudo`.
- The Neo4j tarball `neo4j-enterprise-2026.09.0-unix.tar.gz` on the server, next to the scripts. Download it from the [Neo4j Deployment Center](https://neo4j.com/deployment-center/?gdb-selfmanaged) and copy it over. The scripts do not download it.
- Access to the Ubuntu package mirrors. The scripts use `apt` to install Java and a few helper packages.
- An EXT4 or XFS filesystem, and at least 10 GB free in `/opt`.
- At least 2 GB of RAM for the single node and 8 GB for the cluster.
- An x86_64 or ARM64 CPU. The Neo4j documentation lists support for only these two. On any other architecture the scripts print a warning and continue. IBM Z reports `s390x`, so it triggers the warning.

Java 21 is installed by the scripts if no supported version is present.

### Prepare the server

Run these commands on your laptop from the root of this repository, with the tarball saved there.

Set the server address. The commands below that run on your laptop use it.

```bash
export SERVER_IP=<server-ip>
```

Copy the scripts and the tarball to the same directory on the server.

```bash
scp vm/install-single.sh vm/install-cluster.sh neo4j-enterprise-2026.09.0-unix.tar.gz ubuntu@$SERVER_IP:~/
```

The scripts look for the tarball in their own directory. To keep it somewhere else, set `TARBALL_PATH` when you run them.

Connect to the server.

```bash
ssh ubuntu@$SERVER_IP
```

Each script re-runs itself with `sudo` if you are not root. It explains every step and waits for Enter before running it.

### Single node

#### Set up the single node

Run this on the server to install and check the single node.

```bash
./install-single.sh
```

#### Connect to the single node from your laptop

The scripts listen on `127.0.0.1` by default, so no port is open to the network. Use an SSH tunnel. Run this on your laptop.

```bash
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 ubuntu@$SERVER_IP
```

Open `http://localhost:7474` in a browser. Connect with `bolt://localhost:7687`. Log in as `neo4j` with the password you chose.

If you listen on `0.0.0.0`, read the [security notes](#security-notes) first.

#### Test the single node from your laptop

`laptop-test.py` writes test data to Neo4j and reads it back from your laptop. It opens its own SSH tunnel and closes it when it finishes. Run it on your laptop from the root of this repository, not on the server. It needs [uv](https://docs.astral.sh/uv/), which installs the Neo4j Python driver on the first run.

Connect once with plain `ssh` first so the server's host key is saved.

Copy the sample settings file. The `-n` flag keeps any `tests/.env` you already have.

```bash
cp -n tests/.env.example tests/.env
```

Set `SERVER_IP` and `NEO4J_PW` in `tests/.env`. Git ignores this file.

Run the test.

```bash
uv run tests/laptop-test.py --target single
```

The [laptop test details](#laptop-test-details) cover the optional settings, the steps, and the options.

#### Test Graph Data Science from your laptop

`gds-test.py` runs Graph Data Science algorithms on the single node and checks each answer. It needs the plugin, so install the node with `ENABLE_GDS=yes`. Run this on the server.

```bash
ENABLE_GDS=yes ./install-single.sh
```

Then run the test on your laptop from the root of this repository. It uses the same `tests/.env` as `laptop-test.py`.

```bash
uv run tests/gds-test.py
```

To add load, use a generated graph with 100,000 relationships.

```bash
uv run tests/gds-test.py --rels 100000
```

The [GDS test details](#gds-test-details) cover the steps and the options.

#### What install-single.sh does

1. Checks the OS, architecture, memory, disk, filesystem, and that the ports are free.
2. Asks for the listen address and the license type.
3. Installs Java, creates the `neo4j` user, and unpacks the tarball.
4. Installs the node into `/opt/neo4j-single`, adds the Graph Data Science plugin if `ENABLE_GDS=yes`, and writes its configuration.
5. Accepts the license and sets the initial password.
6. Creates the `neo4j-single` systemd service and starts it.
7. Shows the version and edition, lists the databases, and runs a write and read test.

### Three-member cluster

#### Remove the single node

The single node and cluster member 1 use the same default ports. Remove the single node before you build the cluster. The `install` action also offers to do this. The [cleanup details](#what-cleanup-removes) list what it removes.

```bash
./install-cluster.sh cleanup
```

#### Set up the cluster

Run this on the server to build the cluster.

```bash
./install-cluster.sh
```

To run each step by hand instead, follow [cluster.md](vm/cluster.md).

#### Connect to the cluster from your laptop

The scripts listen on `127.0.0.1` by default, so no port is open to the network. Use an SSH tunnel. Run this on your laptop. It forwards the Bolt ports of all three members.

```bash
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 -L 7697:localhost:7697 -L 7707:localhost:7707 ubuntu@$SERVER_IP
```

Open `http://localhost:7474` in a browser. Connect with `neo4j://localhost:7687`. Log in as `neo4j` with the password you chose.

If you listen on `0.0.0.0`, read the [security notes](#security-notes) first.

#### Test the cluster from your laptop

`laptop-test.py` writes test data to Neo4j and reads it back from your laptop. It opens its own SSH tunnel and closes it when it finishes. Run it on your laptop from the root of this repository, not on the server. It needs [uv](https://docs.astral.sh/uv/), which installs the Neo4j Python driver on the first run.

Connect once with plain `ssh` first so the server's host key is saved.

Copy the sample settings file. The `-n` flag keeps any `tests/.env` you already have.

```bash
cp -n tests/.env.example tests/.env
```

Set `SERVER_IP` and `NEO4J_PW` in `tests/.env`. Git ignores this file.

Run the test.

```bash
uv run tests/laptop-test.py
```

The [laptop test details](#laptop-test-details) cover the optional settings, the steps, and the options.

#### What install-cluster.sh does

1. Offers to clean up earlier installs.
2. Runs the same checks, settings prompts, Java, user, and unpack steps as the single node script.
3. Creates `/opt/neo4j-1`, `/opt/neo4j-2`, and `/opt/neo4j-3` and writes cluster configuration for each.
4. Accepts the license and sets the same initial password on all members.
5. Creates the `neo4j@.service` template and starts `neo4j@1`, `neo4j@2`, and `neo4j@3`.
6. Waits until `SHOW SERVERS` reports three available members.
7. Runs a replication test and an optional failover test.

### Reference

#### Commands

Both scripts take an action and the `-y` flag. The default action is `install`.

```bash
./install-single.sh [install|verify|uninstall] [-y]
```

```bash
./install-cluster.sh [install|verify|reset|uninstall|cleanup] [-y]
```

| Action | Script | Effect |
| --- | --- | --- |
| `install` | both | Runs the guided install. |
| `verify` | both | Shows server and database status and runs the tests. The cluster script also offers a failover test. |
| `reset` | cluster | Deletes all data on all members, sets the password again, and restarts. |
| `uninstall` | both | Removes that script's install and its service. |
| `cleanup` | cluster | Removes every earlier Neo4j install on the machine. |

The `-y` flag skips the Enter pauses and takes the default answer to each question. Pair it with `NEO4J_PW` for an unattended run.

#### What cleanup removes

The `install` action runs the same check as `cleanup` first. It lists what it finds and offers to remove it.

- It defaults to removing the install when it finds the single node or an apt package, because those block the cluster ports.
- It defaults to keeping old cluster members, because re-running `install` reuses them.

Cleanup removes:

- The `neo4j-single` and `neo4j@` services and unit files.
- `/opt/neo4j-single`, `/opt/neo4j-1`, `/opt/neo4j-2`, and `/opt/neo4j-3`, including all data.
- Neo4j apt packages, if present.
- Java processes still running as the `neo4j` user.

Cleanup asks before it removes these, and the default answer is no:

- Leftover `/var/lib/neo4j`, `/var/log/neo4j`, and `/etc/neo4j` from apt packages.
- The unpacked copy in `/tmp/neo4j-cluster-install`. Your tarball is never deleted.
- The `neo4j` user and group.

With `-y`, these optional items are kept.

#### Settings

Set these environment variables before the command to skip a prompt or change a default.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEO4J_VERSION` | `2026.09.0` | Neo4j version to install. It sets the default tarball file name and the unpacked directory name. |
| `TARBALL_PATH` | next to the script | Full path to the Neo4j tarball. |
| `NEO4J_PW` | prompt | Initial password for the `neo4j` user. It needs at least 8 characters. |
| `BASE_DIR` | `/opt` | Parent directory for the installs. |
| `HEAP` | single: Neo4j chooses. Cluster: `1g`, or smaller on hosts under 7000 MB RAM | Heap size for each instance. |
| `PAGECACHE` | single: Neo4j chooses. Cluster: `512m`, or smaller on hosts under 7000 MB RAM | Page cache size for each instance. |
| `LISTEN_ADDRESS` | prompt | Use `127.0.0.1` for local only or `0.0.0.0` for all interfaces. |
| `ADVERTISED_ADDRESS` | `localhost` | Hostname or IP that clients and members use to reach the machine. |
| `NEO4J_LICENSE` | prompt | Use `eval` for the evaluation agreement or `commercial` for the commercial agreement. |
| `ENABLE_GDS` | `no` | Use `yes` to install the Graph Data Science plugin on the single node. `install-cluster.sh` ignores it. |

For example, this runs an unattended cluster install.

```bash
NEO4J_PW='<your-password>' NEO4J_LICENSE=eval LISTEN_ADDRESS=127.0.0.1 ./install-cluster.sh -y
```

#### Layout and ports

| Instance | Directory | Service | Bolt | HTTP | HTTPS | Cluster | Raft | Routing | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Single node | `/opt/neo4j-single` | `neo4j-single` | 7687 | 7474 | 7473 | 6000 | 7000 | 7688 | 6362 |
| Member 1 | `/opt/neo4j-1` | `neo4j@1` | 7687 | 7474 | 7473 | 6000 | 7000 | 7688 | 6362 |
| Member 2 | `/opt/neo4j-2` | `neo4j@2` | 7697 | 7484 | 7483 | 6010 | 7010 | 7698 | 6372 |
| Member 3 | `/opt/neo4j-3` | `neo4j@3` | 7707 | 7494 | 7493 | 6020 | 7020 | 7708 | 6382 |

The single node and member 1 share ports, so run only one of them at a time. The scripts write their settings between `BEGIN` and `END` marker lines in each `neo4j.conf`. Re-running a script replaces that block instead of duplicating it.

#### Laptop test details

`laptop-test.py` reads its settings from `tests/.env`. It loads that file from its own directory, so the test works from any directory. Variables already set in your shell take precedence over the file.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SERVER_IP` | required for `--via ssh` | Address of the server. |
| `NEO4J_PW` | prompt | Password for the `neo4j` user. |
| `LOCAL_BOLT_PORT` | `17687` | Local port for the first member. The default does not clash with a Neo4j already running on port `7687` on your laptop. |
| `SSH_PW` | ssh prompts | SSH password or SSH key passphrase. |
| `OC_NAMESPACE` | required for `--via oc` | Namespace of the Neo4j pods. |
| `OC_POD_SELECTOR` | required for `--via oc` | Label selector for the Neo4j pods, such as `app=neo4j`. |

Put a value in single quotes if it has special characters, so it is read exactly as written.

The script answers only password and passphrase prompts from `SSH_PW`. It does not accept an unknown host key for you.

The tunnel maps the local ports to the Bolt ports on the server.

| Target | Local port | Server port |
| --- | --- | --- |
| Single node | `LOCAL_BOLT_PORT` | 7687 |
| Cluster member 1 | `LOCAL_BOLT_PORT` | 7687 |
| Cluster member 2 | `LOCAL_BOLT_PORT` + 10 | 7697 |
| Cluster member 3 | `LOCAL_BOLT_PORT` + 20 | 7707 |

With `--via oc`, the script runs one `oc port-forward` for each running pod that matches `OC_POD_SELECTOR`. You must be logged in with `oc` first. The first pod uses `LOCAL_BOLT_PORT`, and each further pod uses 10 more than the last. The port forward path has run only against a stand-in for `oc`, not against a real cluster.

```bash
uv run tests/laptop-test.py --via oc
```

The script runs these steps and prints a section for each one.

1. **Settings:** The script shows the platform, target, and row counts.
2. **Connection to Neo4j:** The script checks that the local ports are free and opens the tunnel or port forwards.
3. **Connect:** The script connects the driver and shows the Neo4j version and edition. It also shows the full `SHOW SERVERS` output: each server's ID, address, state, health, and the databases it hosts.
4. **Topology:** The script shows where the `neo4j` and `system` databases run and which member accepts writes for each.
5. **Write:** The script creates 100 `:LaptopTest` nodes in batches of 25. It shows a few sample rows with long text cut short, then the time and server for each batch.
6. **Read:** The script reads the nodes back and shows sample rows. It also shows which server answered the read.
7. **Verify:** The script compares every row read with the row written. It counts the rows that match, differ, or are missing.
8. **Clean up:** The script deletes the test nodes.

A summary at the end shows the counts, times, servers, and a `PASS` or `FAIL` for each check. The checks cover the Enterprise edition, all servers enabled and available, each database online on every member with one writer, and every row matching. The script exits with code 1 on `FAIL` or on any error.

| Option | Default | Meaning |
| --- | --- | --- |
| `--via` | `ssh` | Use `ssh` for the VM or `oc` for OpenShift. |
| `--target` | `cluster` | Use `cluster` or `single`. This applies to `--via ssh` only. |
| `--rows` | `100` | Number of rows to write. |
| `--batch-size` | `25` | Rows per write transaction. |
| `--ssh-user` | `ubuntu` | SSH user on the server. |
| `--ssh-key` | none | Private key file passed to `ssh -i`. |
| `--keep` | off | Keep the test nodes after the run. |

#### GDS test details

`gds-test.py` reads the same `tests/.env` settings as `laptop-test.py` and opens its tunnel the same way. It connects to the single node only. The script computes the expected answers in pure Python on your laptop, then compares them with the GDS results.

Without `--rels`, the script uses a small graph with 8 nodes, 12 relationships, and two separate groups. With `--rels`, it generates a repeatable graph with seed 42 and one node for every five relationships.

The script runs these steps and prints a section for each one.

1. **Settings:** The script shows the graph it will use.
2. **SSH tunnel:** The script opens the tunnel and checks that the local port is free.
3. **Check GDS:** The script confirms that Neo4j loaded the plugin and shows what GDS reports about the machine.
4. **Create test data:** The script removes any `:GdsTest` nodes left by an earlier run, then creates the graph.
5. **Project:** The script estimates the memory for the graph, then loads it into GDS memory.
6. **WCC:** The script compares every connected group of nodes with the groups computed in Python.
7. **PageRank:** The script compares every score with the score computed in Python. The largest allowed difference is 1.00e-05.
8. **Dijkstra:** The script compares the cheapest path and its cost.
9. **Write back:** The script runs PageRank in write mode, reads the scores from the database, and compares them.
10. **Clean up:** The script drops the in-memory graph and deletes the test nodes.

A summary at the end shows each check and `PASS` or `FAIL`. The script exits with code 1 on `FAIL` or on any error. If Neo4j stops during a run, the summary shows `FAIL` and the test nodes stay in the database. The next run removes them.

| Option | Default | Meaning |
| --- | --- | --- |
| `--rels` | none | Use a generated graph with this many relationships. |
| `--ssh-user` | `ubuntu` | SSH user on the server. |
| `--ssh-key` | none | Private key file passed to `ssh -i`. |

#### Operating the services

Check the status of the single node.

```bash
systemctl status neo4j-single
```

Check the status of the cluster members.

```bash
systemctl status neo4j@1 neo4j@2 neo4j@3
```

Follow the log of a service.

```bash
journalctl -u neo4j@1 -f
```

Neo4j also writes `logs/neo4j.log` inside each instance directory.

#### Troubleshooting

**Ports already in use.** The preflight check names the busy ports. Stop the process that owns them, or run `./install-cluster.sh cleanup` if it is an earlier Neo4j install.

**The password does not work.** The initial password applies only before a member's first start. After that it lives in the `system` database. Use `reset` on the cluster, or `uninstall` and `install` on the single node, to start over.

**A member stays unavailable.** Give the cluster a few minutes to form after a start. Then read the journal of the member.

```bash
journalctl -u neo4j@1 --no-pager -n 100
```

**The default Java is the wrong version.** The scripts stop with a message if the default Java is not 21 or 25. List the installed versions, then set Java 21 as the default.

```bash
update-java-alternatives --list
```

```bash
sudo update-java-alternatives --jre --set <java21name>
```

**The tarball is not found or is not valid.** The unpack step stops with the path it looked for. Copy `neo4j-enterprise-2026.09.0-unix.tar.gz` next to the script, or set `TARBALL_PATH`. A "not a valid gzip tarball" message usually means the copy was cut short. Copy the file again and compare its size with the original. To install another version, download that tarball from the [Neo4j Deployment Center](https://neo4j.com/deployment-center/?gdb-selfmanaged) and set `NEO4J_VERSION` to match.

**The script warns about the architecture.** Neo4j documents support only for x86_64 and ARM64. The warning does not stop the install. If Neo4j fails to start on the machine, the journal shows why.

#### Security notes

- If you listen on `0.0.0.0`, set up a firewall and TLS first. The cluster port `6000` accepts unauthenticated replication traffic unless cluster SSL is configured.
- Both scripts pass the password to `neo4j-admin` as a command line argument. It is visible in `ps` for a moment, so use these scripts for test machines.
- The scripts never write the password to disk. `cypher-shell` receives it through an environment variable.
- A cluster on one machine shows how clustering behaves but gives no real fault tolerance. If the machine fails, all three members fail.

## OpenShift deployment (planned)

The next test runs Neo4j Enterprise Edition on IBM Z OpenShift with the Neo4j Kubernetes operator.

## References

- [Linux installation](https://neo4j.com/docs/operations-manual/current/installation/linux/)
- [Install from a tarball](https://neo4j.com/docs/operations-manual/current/installation/linux/tarball/)
- [Deploy a basic cluster](https://neo4j.com/docs/operations-manual/current/clustering/setup/deploy/)
- [Ports](https://neo4j.com/docs/operations-manual/current/configuration/ports/)
- [System requirements](https://neo4j.com/docs/operations-manual/current/installation/requirements/)
