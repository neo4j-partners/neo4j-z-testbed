# Neo4j Enterprise install scripts

Two interactive scripts install Neo4j Enterprise Edition 2026.09.0 on a single Ubuntu server. One installs a single node. The other installs a three-member cluster, with all members on the same machine.

| File | Purpose |
| --- | --- |
| `install-single.sh` | Installs one standalone node. Run it first to check Java, the tarball, licensing, and networking. |
| `install-cluster.sh` | Installs a three-member cluster on one machine. It can also clean up earlier installs. |
| `cluster.md` | The same cluster setup as manual steps, with one command per code block. |
| `laptop-test.py` | Runs from your laptop. Writes test data through an SSH tunnel, reads it back, and checks it. |

Both scripts install from the Neo4j tarball, not the Debian package. The Debian package supports only one instance per machine, so it cannot host three cluster members.

## Requirements

- Ubuntu Server 22.04 or 24.04. Ubuntu 22.04 is deprecated as of Neo4j 2026.05.
- Root access or a user with `sudo`.
- The Neo4j tarball `neo4j-enterprise-2026.09.0-unix.tar.gz` on the server, next to the scripts. Download it from the [Neo4j Deployment Center](https://neo4j.com/deployment-center/?gdb-selfmanaged) and copy it over. The scripts do not download it.
- Access to the Ubuntu package mirrors. The scripts use `apt` to install Java and a few helper packages.
- An EXT4 or XFS filesystem, and at least 10 GB free in `/opt`.
- At least 2 GB of RAM for the single node and 8 GB for the cluster.
- An x86_64 or ARM64 CPU. The Neo4j documentation lists support for only these two. On any other architecture the scripts print a warning and continue. IBM Z reports `s390x`, so it triggers the warning.

Java 21 is installed by the scripts if no supported version is present.

## Quick start

On your laptop, set the server address. The commands below that run on your laptop use it.

```bash
export SERVER_IP=<server-ip>
```

Copy the scripts and the tarball to the same directory on the server.

```bash
scp install-single.sh install-cluster.sh neo4j-enterprise-2026.09.0-unix.tar.gz ubuntu@$SERVER_IP:~/
```

```bash
scp install-single.sh install-cluster.sh ubuntu@$SERVER_IP:~/
```

The scripts look for the tarball in their own directory. To keep it somewhere else, set `TARBALL_PATH` when you run them.

Connect to the server.

```bash
ssh ubuntu@$SERVER_IP
```

Install and check the single node first.

```bash
./install-single.sh
```

Then build the cluster. The script offers to remove the single node before it starts.

```bash
./install-cluster.sh
```

Each script re-runs itself with `sudo` if you are not root. It explains every step and waits for Enter before running it.

## What each script does

### install-single.sh

1. Checks the OS, architecture, memory, disk, filesystem, and that the ports are free.
2. Asks for the listen address and the license type.
3. Installs Java, creates the `neo4j` user, and unpacks the tarball.
4. Installs the node into `/opt/neo4j-single` and writes its configuration.
5. Accepts the license and sets the initial password.
6. Creates the `neo4j-single` systemd service and starts it.
7. Shows the version and edition, lists the databases, and runs a write and read test.

### install-cluster.sh

1. Offers to clean up earlier installs.
2. Runs the same checks, settings prompts, Java, user, and unpack steps as the single node script.
3. Creates `/opt/neo4j-1`, `/opt/neo4j-2`, and `/opt/neo4j-3` and writes cluster configuration for each.
4. Accepts the license and sets the same initial password on all members.
5. Creates the `neo4j@.service` template and starts `neo4j@1`, `neo4j@2`, and `neo4j@3`.
6. Waits until `SHOW SERVERS` reports three available members.
7. Runs a replication test and an optional failover test.

## Commands

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

## Clean up before building the cluster

The single node and cluster member 1 use the same default ports. Remove the single node before you build the cluster.

```bash
./install-cluster.sh cleanup
```

The `install` action also runs this check first. It lists what it finds and offers to remove it.

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

## Settings

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

For example, this runs an unattended cluster install.

```bash
NEO4J_PW='<your-password>' NEO4J_LICENSE=eval LISTEN_ADDRESS=127.0.0.1 ./install-cluster.sh -y
```

## Layout and ports

| Instance | Directory | Service | Bolt | HTTP | HTTPS | Cluster | Raft | Routing | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Single node | `/opt/neo4j-single` | `neo4j-single` | 7687 | 7474 | 7473 | 6000 | 7000 | 7688 | 6362 |
| Member 1 | `/opt/neo4j-1` | `neo4j@1` | 7687 | 7474 | 7473 | 6000 | 7000 | 7688 | 6362 |
| Member 2 | `/opt/neo4j-2` | `neo4j@2` | 7697 | 7484 | 7483 | 6010 | 7010 | 7698 | 6372 |
| Member 3 | `/opt/neo4j-3` | `neo4j@3` | 7707 | 7494 | 7493 | 6020 | 7020 | 7708 | 6382 |

The single node and member 1 share ports, so run only one of them at a time. The scripts write their settings between `BEGIN` and `END` marker lines in each `neo4j.conf`. Re-running a script replaces that block instead of duplicating it.

## Connect from your laptop

The scripts listen on `127.0.0.1` by default, so no port is open to the network. Use an SSH tunnel. Run this on your laptop for the single node.

```bash
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 ubuntu@$SERVER_IP
```

For the cluster, forward the Bolt ports of all three members as well.

```bash
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 -L 7697:localhost:7697 -L 7707:localhost:7707 ubuntu@$SERVER_IP
```

Open `http://localhost:7474` in a browser. Connect with `neo4j://localhost:7687` for the cluster or `bolt://localhost:7687` for the single node. Log in as `neo4j` with the password you chose.

If you listen on `0.0.0.0`, set up a firewall and TLS first. The cluster port `6000` accepts unauthenticated replication traffic unless cluster SSL is configured.

## Test from your laptop

`laptop-test.py` writes test data to Neo4j and reads it back from your laptop. It opens its own SSH tunnel and closes it when it finishes. Run it on your laptop, not on the server. It needs [uv](https://docs.astral.sh/uv/), which installs the Neo4j Python driver on the first run.

Set the server address.

```bash
export SERVER_IP=<server-ip>
```

Optionally, set the local port for the tunnel. The default is `17687`, so the test does not clash with a Neo4j already running on port `7687` on your laptop.

```bash
export LOCAL_BOLT_PORT=17687
```

Set the password for the `neo4j` user. If `NEO4J_PW` is not set, the script prompts for it.

```bash
export NEO4J_PW='<your-password>'
```

If the server uses a password for SSH, or your SSH key has a passphrase, set it. If `SSH_PW` is not set, ssh prompts as usual.

```bash
export SSH_PW='<ssh-password>'
```

The script answers only password and passphrase prompts from `SSH_PW`. It does not accept an unknown host key for you. Connect once with plain `ssh` first so the server's host key is saved.

Test the cluster.

```bash
uv run laptop-test.py
```

Test the single node.

```bash
uv run laptop-test.py --target single
```

The tunnel maps the local ports to the Bolt ports on the server.

| Target | Local port | Server port |
| --- | --- | --- |
| Single node | `LOCAL_BOLT_PORT` | 7687 |
| Cluster member 1 | `LOCAL_BOLT_PORT` | 7687 |
| Cluster member 2 | `LOCAL_BOLT_PORT` + 10 | 7697 |
| Cluster member 3 | `LOCAL_BOLT_PORT` + 20 | 7707 |

The script runs these steps and prints a section for each one.

1. **Settings:** The script shows the server, target, URI, and port mapping.
2. **SSH tunnel:** The script opens the tunnel and checks that the local ports are free.
3. **Connect:** The script connects the driver and shows the Neo4j version and edition. It also shows the full `SHOW SERVERS` output: each server's ID, address, state, health, and the databases it hosts.
4. **Topology:** The script shows where the `neo4j` database runs and which member accepts writes.
5. **Write:** The script creates 100 `:LaptopTest` nodes in batches of 25. It shows a few sample rows with long text cut short, then the time and server for each batch.
6. **Read:** The script reads the nodes back and shows sample rows. It also shows which server answered the read.
7. **Verify:** The script compares every row read with the row written. It counts the rows that match, differ, or are missing.
8. **Clean up:** The script deletes the test nodes.

A summary at the end shows the counts, times, servers, and `PASS` or `FAIL`. The script exits with code 1 on `FAIL` or on any error.

| Option | Default | Meaning |
| --- | --- | --- |
| `--target` | `cluster` | Use `cluster` or `single`. |
| `--rows` | `100` | Number of rows to write. |
| `--batch-size` | `25` | Rows per write transaction. |
| `--ssh-user` | `ubuntu` | SSH user on the server. |
| `--ssh-key` | none | Private key file passed to `ssh -i`. |
| `--keep` | off | Keep the test nodes after the run. |

## Operating the services

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

## Troubleshooting

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

## Security notes

- Both scripts pass the password to `neo4j-admin` as a command line argument. It is visible in `ps` for a moment, so use these scripts for test machines.
- The scripts never write the password to disk. `cypher-shell` receives it through an environment variable.
- A cluster on one machine shows how clustering behaves but gives no real fault tolerance. If the machine fails, all three members fail.

## References

- [Linux installation](https://neo4j.com/docs/operations-manual/current/installation/linux/)
- [Install from a tarball](https://neo4j.com/docs/operations-manual/current/installation/linux/tarball/)
- [Deploy a basic cluster](https://neo4j.com/docs/operations-manual/current/clustering/setup/deploy/)
- [Ports](https://neo4j.com/docs/operations-manual/current/configuration/ports/)
- [System requirements](https://neo4j.com/docs/operations-manual/current/installation/requirements/)
