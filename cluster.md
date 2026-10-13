# Neo4j Enterprise Edition cluster on a single Ubuntu machine

This guide builds a three-member Neo4j 2026.09.0 Enterprise cluster on one remote Ubuntu server. Each member is a separate Neo4j instance with its own directory, ports, and systemd service.

The Debian package from the [Linux installation docs](https://neo4j.com/docs/operations-manual/current/installation/linux/) installs one instance with fixed paths and one service. A three-member cluster on one host therefore uses the [tarball install](https://neo4j.com/docs/operations-manual/current/installation/linux/tarball/) three times. The cluster settings come from [Deploy a basic cluster](https://neo4j.com/docs/operations-manual/current/clustering/setup/deploy/).

This is a test setup. All three members share one machine, so it shows how clustering behaves but gives no real fault tolerance.

## Layout

| Member | Directory | Bolt | HTTP | HTTPS | Cluster | Raft | Routing | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `/opt/neo4j-1` | 7687 | 7474 | 7473 | 6000 | 7000 | 7688 | 6362 |
| 2 | `/opt/neo4j-2` | 7697 | 7484 | 7483 | 6010 | 7010 | 7698 | 6372 |
| 3 | `/opt/neo4j-3` | 7707 | 7494 | 7493 | 6020 | 7020 | 7708 | 6382 |

## Requirements

- Ubuntu Server 22.04 or 24.04. Ubuntu 22.04 is deprecated as of 2026.05.
- At least 8 GB of RAM and 4 vCPUs, because three JVMs run side by side.
- An EXT4 or XFS filesystem. NFS is not supported.
- Java 21 or Java 25.
- The Neo4j tarball `neo4j-enterprise-2026.09.0-unix.tar.gz`, copied to the server in step 5.
- An x86_64 or ARM64 CPU. The Neo4j documentation lists support for only these two. IBM Z reports `s390x`, so it is outside the documented support.

## 1. Connect to the server

On your laptop, set the server address. Steps 1, 5, and 16 run on your laptop and use it.

```bash
export SERVER_IP=<server-ip>
```

Replace the key path and user with your own values.

```bash
ssh -i ~/.ssh/<your-key>.pem ubuntu@$SERVER_IP
```

## 2. Check memory and disk

```bash
free -h
```

```bash
df -h /opt
```

## 3. Install Java 21

Enable the `universe` repository first. Neo4j dependencies fail to resolve without it.

```bash
sudo add-apt-repository -y universe
```

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y openjdk-21-jre-headless curl
```

Confirm the default Java is version 21 or 25.

```bash
java -version
```

If several Java versions are installed, list them and set Java 21 as the default.

```bash
update-java-alternatives --list
```

```bash
sudo update-java-alternatives --jre --set <java21name>
```

## 4. Create the neo4j user and group

```bash
sudo groupadd neo4j
```

```bash
sudo useradd -g neo4j neo4j -s /bin/bash
```

## 5. Unpack Neo4j Enterprise

This guide installs from the tarball `neo4j-enterprise-2026.09.0-unix.tar.gz`. Download it from the [Neo4j Deployment Center](https://neo4j.com/deployment-center/?gdb-selfmanaged) and copy it to the server. Run this on your laptop, not on the server.

```bash
scp -i ~/.ssh/<your-key>.pem neo4j-enterprise-2026.09.0-unix.tar.gz ubuntu@$SERVER_IP:~/
```

On the server, unpack it into `/tmp`.

```bash
tar zxf ~/neo4j-enterprise-2026.09.0-unix.tar.gz -C /tmp
```

## 6. Create the three instance directories

This copies the unpacked install into `/opt/neo4j-1`, `/opt/neo4j-2`, and `/opt/neo4j-3`.

```bash
for i in 1 2 3; do sudo cp -a /tmp/neo4j-enterprise-2026.09.0 /opt/neo4j-$i; done
```

Give the neo4j user ownership of each directory. On Ubuntu the group is `adm`.

```bash
for i in 1 2 3; do sudo chown -R neo4j:adm /opt/neo4j-$i; done
```

```bash
ls -ld /opt/neo4j-*
```

## 7. Configure each member

Each command appends cluster settings to that member's `neo4j.conf`. Three settings are identical on every member:

- `dbms.cluster.endpoints` lists all three cluster ports so members can find each other.
- `initial.dbms.default_primaries_count=3` puts three primary copies of the default database on the cluster.
- `server.default_listen_address=127.0.0.1` keeps every port closed to the outside world. Use `0.0.0.0` instead only if you need direct remote access and have set up a firewall and TLS.

The heap and page cache values are small so three instances fit on one machine. Raise them if the server has more RAM. On a server with less than 8 GB, lower them, for example to a 512m heap and 128m page cache on a 4 GB server.

Member 1:

```bash
sudo tee -a /opt/neo4j-1/conf/neo4j.conf > /dev/null <<'EOF'

# Cluster settings
server.default_listen_address=127.0.0.1
server.default_advertised_address=localhost
dbms.cluster.endpoints=localhost:6000,localhost:6010,localhost:6020
initial.dbms.default_primaries_count=3

# Ports
server.bolt.listen_address=:7687
server.bolt.advertised_address=:7687
server.http.listen_address=:7474
server.http.advertised_address=:7474
server.https.listen_address=:7473
server.https.advertised_address=:7473
server.cluster.listen_address=:6000
server.cluster.advertised_address=:6000
server.cluster.raft.listen_address=:7000
server.cluster.raft.advertised_address=:7000
server.routing.listen_address=:7688
server.routing.advertised_address=:7688
server.backup.listen_address=127.0.0.1:6362

# Memory
server.memory.heap.initial_size=1g
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
EOF
```

Member 2:

```bash
sudo tee -a /opt/neo4j-2/conf/neo4j.conf > /dev/null <<'EOF'

# Cluster settings
server.default_listen_address=127.0.0.1
server.default_advertised_address=localhost
dbms.cluster.endpoints=localhost:6000,localhost:6010,localhost:6020
initial.dbms.default_primaries_count=3

# Ports
server.bolt.listen_address=:7697
server.bolt.advertised_address=:7697
server.http.listen_address=:7484
server.http.advertised_address=:7484
server.https.listen_address=:7483
server.https.advertised_address=:7483
server.cluster.listen_address=:6010
server.cluster.advertised_address=:6010
server.cluster.raft.listen_address=:7010
server.cluster.raft.advertised_address=:7010
server.routing.listen_address=:7698
server.routing.advertised_address=:7698
server.backup.listen_address=127.0.0.1:6372

# Memory
server.memory.heap.initial_size=1g
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
EOF
```

Member 3:

```bash
sudo tee -a /opt/neo4j-3/conf/neo4j.conf > /dev/null <<'EOF'

# Cluster settings
server.default_listen_address=127.0.0.1
server.default_advertised_address=localhost
dbms.cluster.endpoints=localhost:6000,localhost:6010,localhost:6020
initial.dbms.default_primaries_count=3

# Ports
server.bolt.listen_address=:7707
server.bolt.advertised_address=:7707
server.http.listen_address=:7494
server.http.advertised_address=:7494
server.https.listen_address=:7493
server.https.advertised_address=:7493
server.cluster.listen_address=:6020
server.cluster.advertised_address=:6020
server.cluster.raft.listen_address=:7020
server.cluster.raft.advertised_address=:7020
server.routing.listen_address=:7708
server.routing.advertised_address=:7708
server.backup.listen_address=127.0.0.1:6382

# Memory
server.memory.heap.initial_size=1g
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
EOF
```

## 8. Accept the license

Enterprise Edition requires a license agreement on every instance. This command accepts the evaluation agreement.

```bash
for i in 1 2 3; do sudo -u neo4j /opt/neo4j-$i/bin/neo4j-admin server license --accept-evaluation; done
```

If you hold a commercial license, use `--accept-commercial` instead.

## 9. Set the initial password

Every member must use the same initial password. Replace the value with your own. The password needs at least 8 characters.

```bash
export NEO4J_PW='<your-password>'
```

```bash
for i in 1 2 3; do sudo -u neo4j /opt/neo4j-$i/bin/neo4j-admin dbms set-initial-password "$NEO4J_PW"; done
```

Run this step before the first start. After a member has started once, the password lives in the `system` database and this command no longer applies.

## 10. Create a systemd service for the members

One template file serves all three members. The `%i` placeholder becomes `1`, `2`, or `3`.

```bash
sudo tee /etc/systemd/system/neo4j@.service > /dev/null <<'EOF'
[Unit]
Description=Neo4j Graph Database member %i
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/neo4j-%i/bin/neo4j console
Restart=on-abnormal
User=neo4j
Group=neo4j
Environment="NEO4J_CONF=/opt/neo4j-%i/conf" "NEO4J_HOME=/opt/neo4j-%i"
LimitNOFILE=60000
TimeoutSec=120

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
```

Optionally start all three members automatically at boot.

```bash
sudo systemctl enable neo4j@1 neo4j@2 neo4j@3
```

## 11. Start the cluster

Start order does not matter. The cluster forms once all three members find each other.

```bash
sudo systemctl start neo4j@1 neo4j@2 neo4j@3
```

```bash
systemctl status neo4j@1 neo4j@2 neo4j@3 --no-pager
```

Follow the startup of one member in its journal. A member can look unavailable while it joins the cluster.

```bash
journalctl -u neo4j@1 -f
```

Press `Ctrl+C` to stop following the log. The log files are also in `/opt/neo4j-1/logs/neo4j.log`.

## 12. Verify the cluster

List the servers. All three should show `Enabled` and `Available`.

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d system "SHOW SERVERS;"
```

Check that the `neo4j` database has one leader and two followers.

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d system "SHOW DATABASES;"
```

## 13. Test replication

Write a node through the routing driver. The driver sends the write to the leader.

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d neo4j "CREATE (:Test {msg: 'hello cluster'});"
```

Read the node directly from member 2 and member 3.

```bash
/opt/neo4j-1/bin/cypher-shell -a bolt://localhost:7697 -u neo4j -p "$NEO4J_PW" -d neo4j "MATCH (t:Test) RETURN t.msg;"
```

```bash
/opt/neo4j-1/bin/cypher-shell -a bolt://localhost:7707 -u neo4j -p "$NEO4J_PW" -d neo4j "MATCH (t:Test) RETURN t.msg;"
```

## 14. Test failover

Stop member 2.

```bash
sudo systemctl stop neo4j@2
```

Member 2 should now report as unavailable. The other two members keep a majority, so writes still succeed.

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d system "SHOW SERVERS;"
```

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d neo4j "CREATE (:Test {msg: 'written with one member down'});"
```

Bring member 2 back and confirm it catches up.

```bash
sudo systemctl start neo4j@2
```

```bash
/opt/neo4j-1/bin/cypher-shell -a bolt://localhost:7697 -u neo4j -p "$NEO4J_PW" -d neo4j "MATCH (t:Test) RETURN t.msg;"
```

## 15. Optional: create another database

Create a database with three primaries. Run this against the `system` database.

```bash
/opt/neo4j-1/bin/cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PW" -d system "CREATE DATABASE foo TOPOLOGY 3 PRIMARIES;"
```

## 16. Optional: open Neo4j Browser from your laptop

The members listen on `127.0.0.1` only, so use an SSH tunnel. Run this on your laptop, not on the server. It forwards the HTTP and Bolt ports of all three members.

```bash
ssh -i ~/.ssh/<your-key>.pem \
  -L 7474:localhost:7474 -L 7687:localhost:7687 \
  -L 7697:localhost:7697 -L 7707:localhost:7707 \
  ubuntu@$SERVER_IP
```

Open `http://localhost:7474` in a browser. Connect with the URL `neo4j://localhost:7687`, the username `neo4j`, and the password you set in step 9.

## Troubleshooting

Check the journal and log of a member that does not start.

```bash
journalctl -u neo4j@1 --no-pager -n 100
```

```bash
sudo tail -n 100 /opt/neo4j-1/logs/neo4j.log
```

Confirm that each expected port is listening.

```bash
sudo ss -ltnp | grep java
```

If a member fails with `Too many open files`, confirm the service limit is applied.

```bash
systemctl show neo4j@1 -p LimitNOFILE
```

## Reset the cluster

Use this to start over with empty databases. It deletes all data.

```bash
sudo systemctl stop neo4j@1 neo4j@2 neo4j@3
```

```bash
for i in 1 2 3; do sudo -u neo4j rm -rf /opt/neo4j-$i/data/databases /opt/neo4j-$i/data/transactions /opt/neo4j-$i/data/cluster-state; done
```

The old password is gone with the `system` database. Set it again before starting.

```bash
for i in 1 2 3; do sudo -u neo4j /opt/neo4j-$i/bin/neo4j-admin dbms set-initial-password "$NEO4J_PW"; done
```

```bash
sudo systemctl start neo4j@1 neo4j@2 neo4j@3
```

## Uninstall

```bash
sudo systemctl stop neo4j@1 neo4j@2 neo4j@3
```

```bash
sudo systemctl disable neo4j@1 neo4j@2 neo4j@3
```

```bash
sudo rm /etc/systemd/system/neo4j@.service
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo rm -rf /opt/neo4j-1 /opt/neo4j-2 /opt/neo4j-3
```
