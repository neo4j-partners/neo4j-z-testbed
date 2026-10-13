# Sample output from IBM Z

These are the full outputs from one test run on IBM Z. The server hostname, the server IP address, and the password are redacted.

## Cluster install on the server

```text
ubuntu@<server-hostname>:~$ ./install-cluster.sh install
This script needs root. Re-running with sudo...
Neo4j 2026.09.0 Enterprise: three-member cluster on one machine
This script walks through each step and explains what it does before running it.
Press Enter to move to the next step.

==> Step 1: Check for earlier installs
    Looks for a single node, old cluster members, or apt packages left from earlier tests.
    OK No earlier install found.

==> Step 2: Preflight checks
    Checks the OS, memory, disk space, and that the ports we need are free.
    Press Enter to continue (Ctrl+C to quit) 
    OK Ubuntu 24.04 is supported.
    WARN Architecture s390x. Neo4j documents support only for x86_64 and ARM, so this platform is unsupported.
    WARN Only 3997 MB RAM detected. Three members need about 8 GB with the default memory settings.
    WARN Using HEAP=512m PAGECACHE=128m per member. Set HEAP and PAGECACHE to override.
    Continue anyway? [y/N] y
    OK 94 GB free in /opt.
    OK Filesystem is ext4.
    OK All required ports are free.

==> Step 3: Choose network and license settings
    Listening on 127.0.0.1 keeps every port closed to the network. Use an SSH tunnel to reach it.
    Listening on 0.0.0.0 opens the ports to anything that can reach this machine. Add a firewall and TLS first.
    Listen on localhost only (recommended)? [Y/n] y
    OK Listen address: 127.0.0.1, advertised address: localhost.
    Enterprise Edition needs a license agreement. 'eval' accepts the Neo4j Evaluation Agreement.
    'commercial' accepts the commercial agreement.
    Accept the evaluation license? [Y/n] y
    OK License: eval.

==> Step 4: Install Java
    Neo4j 2026.09.0 needs Java 21 or Java 25. The 'universe' apt repository must be enabled.
    Press Enter to continue (Ctrl+C to quit) 
    OK Java 21 is already the default.

==> Step 5: Create the neo4j user and group
    Neo4j runs as an unprivileged 'neo4j' user.
    Press Enter to continue (Ctrl+C to quit) 
    OK User and group 'neo4j' exist.

==> Step 6: Unpack Neo4j Enterprise 2026.09.0
    Unpacks /home/ubuntu/neo4j-enterprise-2026.09.0-unix.tar.gz to /tmp/neo4j-cluster-install.
    Press Enter to continue (Ctrl+C to quit) 
    OK Unpacked to /tmp/neo4j-cluster-install/neo4j-enterprise-2026.09.0.

==> Step 7: Create the three instance directories
    Copies the unpacked install to /opt/neo4j-1, /opt/neo4j-2, and /opt/neo4j-3.
    Each member gets its own binaries, config, data, and logs.
    Press Enter to continue (Ctrl+C to quit) 
    OK Created /opt/neo4j-1.
    OK Created /opt/neo4j-2.
    OK Created /opt/neo4j-3.

==> Step 8: Write the cluster configuration
    Appends a managed block to each member's conf/neo4j.conf. Re-running replaces that block.
    All members share the same discovery list and ask for 3 primaries.
    Ports are offset by 10 per member so the three instances do not collide.
    Press Enter to continue (Ctrl+C to quit) 
    OK Configured member 1 (bolt 7687, http 7474, cluster 6000).
    OK Configured member 2 (bolt 7697, http 7484, cluster 6010).
    OK Configured member 3 (bolt 7707, http 7494, cluster 6020).

==> Step 9: Accept the Enterprise license
    Runs 'neo4j-admin server license' on each member.
    Press Enter to continue (Ctrl+C to quit) 
WARNING: Using incubator modules: jdk.incubator.vector
Evaluation license accepted.

Thank you for installing Neo4j. This is a time limited trial of 30 days.

This is a time limited trial. You have 30 days remaining out of 30 days.
Please contact https://neo4j.com/contact-us/ if you require more time.
WARNING: Using incubator modules: jdk.incubator.vector
Evaluation license accepted.

Thank you for installing Neo4j. This is a time limited trial of 30 days.

This is a time limited trial. You have 30 days remaining out of 30 days.
Please contact https://neo4j.com/contact-us/ if you require more time.
WARNING: Using incubator modules: jdk.incubator.vector
Evaluation license accepted.

Thank you for installing Neo4j. This is a time limited trial of 30 days.

This is a time limited trial. You have 30 days remaining out of 30 days.
Please contact https://neo4j.com/contact-us/ if you require more time.
    OK License accepted on all members.

==> Step 10: Set the initial password
    All members need the same initial password, set before the first start.
    Once a member has started, the password lives in the system database and this step is skipped.
    Press Enter to continue (Ctrl+C to quit) <redacted>
    Choose the neo4j password (8+ characters): 
    Confirm password: 
WARNING: Using incubator modules: jdk.incubator.vector
    OK Password set on member 1.
WARNING: Using incubator modules: jdk.incubator.vector
    OK Password set on member 2.
WARNING: Using incubator modules: jdk.incubator.vector
    OK Password set on member 3.

==> Step 11: Create the systemd service
    One template unit /etc/systemd/system/neo4j@.service runs every member. neo4j@1 uses /opt/neo4j-1, and so on.
    Press Enter to continue (Ctrl+C to quit) 
    OK Service template installed.
    Start the cluster automatically at boot? [Y/n] Y
    OK Enabled at boot.

==> Step 12: Start the cluster
    Start order does not matter. The cluster forms once all three members find each other.
    Press Enter to continue (Ctrl+C to quit) 
    Waiting for 3 available servers.....
    OK 3 servers are Enabled and Available.

==> Step 13: Verify the cluster
    Lists the servers and the databases they host.
    Press Enter to continue (Ctrl+C to quit) 

name, address, state, health, hosting
"16649b85-1eff-4d21-aa0a-09317a6c98df", "localhost:7687", "Enabled", "Available", ["neo4j", "system"]
"333dac3b-6a90-43d1-bb37-f07f5a223156", "localhost:7707", "Enabled", "Available", ["neo4j", "system"]
"95b5672e-d2d8-4e6a-a98e-4c1326c1fd17", "localhost:7697", "Enabled", "Available", ["neo4j", "system"]

name, type, aliases, access, address, role, writer, requestedStatus, currentStatus, statusMessage, default, home, constituents
"neo4j", "standard", [], "read-write", "localhost:7707", "primary", FALSE, "online", "online", "", TRUE, TRUE, []
"neo4j", "standard", [], "read-write", "localhost:7697", "primary", TRUE, "online", "online", "", TRUE, TRUE, []
"neo4j", "standard", [], "read-write", "localhost:7687", "primary", FALSE, "online", "online", "", TRUE, TRUE, []
"system", "system", [], "read-write", "localhost:7697", "primary", FALSE, "online", "online", "", FALSE, FALSE, []
"system", "system", [], "read-write", "localhost:7687", "primary", FALSE, "online", "online", "", FALSE, FALSE, []
"system", "system", [], "read-write", "localhost:7707", "primary", TRUE, "online", "online", "", FALSE, FALSE, []


==> Step 14: Replication test
    Writes a node through the routing driver, then reads it directly from members 2 and 3.
    Run the replication test? [Y/n] Y
    OK Member 2 returned the node written through member 1.
    OK Member 3 returned the node written through member 1.

==> Step 15: Failover test
    Stops member 2, confirms writes still work with 2 of 3 members, then restarts it.
    Run the failover test? [y/N] y
    OK Stopped neo4j@2.
    OK Write succeeded with one member down.
    OK Restarted neo4j@2.
    Waiting for 3 available servers..
    OK 3 servers are Enabled and Available.
    OK Member 2 caught up and has the node written while it was down.

Done. Your three-member cluster is running.

  Bolt:     neo4j://localhost:7687  (members on 7697 and 7707)
  Browser:  http://localhost:7474
  User:     neo4j

From your laptop, tunnel the ports and open Neo4j Browser:
  ssh -L 7474:localhost:7474 -L 7687:localhost:7687 \
      -L 7697:localhost:7697 -L 7707:localhost:7707 <user>@<server-ip>

Useful commands:
  systemctl status neo4j@1 neo4j@2 neo4j@3
  journalctl -u neo4j@1 -f
  ./install-cluster.sh verify | reset | uninstall
```

## Laptop test against the cluster

```text
% uv run laptop-test.py

========================================================================
[1/8] Settings
========================================================================
The values this run uses.

  Server                   ubuntu@<server-ip>
  Target                   cluster
  URI                      neo4j://localhost:17687
  Forwarded ports          17687 -> 7687, 17697 -> 7697, 17707 -> 7707
  Rows / batch size        100 / 25
  Keep data                no
  SSH password             from SSH_PW

========================================================================
[2/8] SSH tunnel
========================================================================
Forwards local ports on this laptop to the Bolt ports on the server. The
server listens on 127.0.0.1 only, so the tunnel is the way in.

  Command                  ssh -N -o ExitOnForwardFailure=yes -o NumberOfPasswordPrompts=1 -L 17687:localhost:7687 -L 17697:localhost:7697 -L 17707:localhost:7707 ubuntu@<server-ip>
  Tunnel                   open, ssh pid 39372

========================================================================
[3/8] Connect
========================================================================
Connects the Neo4j Python driver to neo4j://localhost:17687, reads the
server version, and lists the servers with SHOW SERVERS.

  Connected to             [::1]:17697
  Server agent             Neo4j/2026.09.0
  Bolt protocol            6.1
  Neo4j                    Neo4j Kernel 2026.09.0 enterprise
  Neo4j                    Cypher 5 

  SHOW SERVERS:
    Server 1
      name       16649b85-1eff-4d21-aa0a-09317a6c98df
      address    localhost:7687
      state      Enabled
      health     Available
      hosting    neo4j, system
    Server 2
      name       333dac3b-6a90-43d1-bb37-f07f5a223156
      address    localhost:7707
      state      Enabled
      health     Available
      hosting    neo4j, system
    Server 3
      name       95b5672e-d2d8-4e6a-a98e-4c1326c1fd17
      address    localhost:7697
      state      Enabled
      health     Available
      hosting    neo4j, system

  Available servers        3 of 3

========================================================================
[4/8] Topology
========================================================================
Shows where the 'neo4j' database runs. The writer is the member that
accepts writes.

  Database 'neo4j':
    localhost:7707     role=primary    status=online  <- writer
    localhost:7697     role=primary    status=online
    localhost:7687     role=primary    status=online

  Members online           3 of 3

========================================================================
[5/8] Write
========================================================================
Creates 100 :LaptopTest nodes tagged run_id=run-2f4e2b3f, in batches of
25. Each batch is one write transaction.

  Sample of the rows being written:
  seq=1    name=item-00001     value= 5243.746 tags=[commit,primary] payload="replica raft cache raft page ..." (230 chars)
  seq=2    name=item-00002     value= 2969.690 tags=[raft,edge] payload="raft heap edge read index rea..." (262 chars)
  seq=3    name=item-00003     value= 7913.320 tags=[leader,node] payload="cluster replica read cluster ..." (314 chars)
  ... 97 more rows

  batch 1/4  25 nodes  478 ms  server=[::1]:17707
  batch 2/4  25 nodes  476 ms  server=[::1]:17707
  batch 3/4  25 nodes  552 ms  server=[::1]:17707
  batch 4/4  25 nodes  639 ms  server=[::1]:17707

  Nodes created            100
  Write time               2145 ms
  Rows per second          47

========================================================================
[6/8] Read
========================================================================
Reads back every node with run_id=run-2f4e2b3f in one read transaction.
On a cluster the driver may route it to a member other than the writer.

  Sample of the rows read back:
  seq=1    name=item-00001     value= 5243.746 tags=[commit,primary] payload="replica raft cache raft page ..." (230 chars)
  seq=2    name=item-00002     value= 2969.690 tags=[raft,edge] payload="raft heap edge read index rea..." (262 chars)
  seq=3    name=item-00003     value= 7913.320 tags=[leader,node] payload="cluster replica read cluster ..." (314 chars)
  ... 97 more rows

  Rows read                100
  Read time                1888 ms
  Served by                [::1]:17697

========================================================================
[7/8] Verify
========================================================================
Compares each row read back with the row written, field by field.

  Rows matched             100 of 100
  Rows different           0
  Rows missing             0

========================================================================
[8/8] Clean up
========================================================================
Deletes the nodes with run_id=run-2f4e2b3f.

  Nodes deleted            100

========================================================================
Summary
========================================================================
Results for run-2f4e2b3f on neo4j://localhost:17687.

  Target                   cluster
  Rows written             100
  Rows read                100
  Rows matched             100
  Rows different           0
  Rows missing             0
  Nodes deleted            100
  Write time               2145 ms
  Read time                1888 ms
  Writes served by         [::1]:17707
  Read served by           [::1]:17697

  Result                   PASS

SSH tunnel closed (pid 39372).
```
