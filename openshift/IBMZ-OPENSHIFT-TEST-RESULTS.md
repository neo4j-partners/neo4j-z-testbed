# Neo4j Enterprise on IBM Z OpenShift: test results

**Goal:** This testing validates the Neo4j EE IntelliGraph bundle that Neo4j is preparing for IBM. The bundle includes Neo4j Enterprise Edition and Graph Data Science. The testing sets a baseline of what works in this package.

This template records the results of running Neo4j Enterprise Edition on OpenShift on IBM Z with the Neo4j Kubernetes operator. No tests have run yet. Replace each `<placeholder>` and `Not run` as the tests finish.

The VM results are in [IBMZ-VM-TEST-RESULTS.md](../vm/IBMZ-VM-TEST-RESULTS.md).

## Summary

| Area | Tests passed | Result |
| --- | --- | --- |
| [Platform](#platform) | 0 of 4 | Not run |
| [Operator](#operator) | 0 of 3 | Not run |
| [Cluster](#cluster) | 0 of 7 | Not run |
| [Resilience](#resilience) | 0 of 4 | Not run |
| [Operations](#operations) | 0 of 3 | Not run |
| [Graph Data Science](#graph-data-science) | 0 of 3 | Not run |

Use one of these results for each test: `Not run`, `Passed`, `Failed`, `Blocked`, or `Skipped`.

## Test environment

| Item | Value |
| --- | --- |
| Test date | `<date>` |
| IBM Z machine type | `<machine-type>` |
| OpenShift version | `<version>` |
| Kubernetes version | `<version>` |
| Worker node count | `<count>` |
| CPU and memory per worker | `<cpu>`, `<memory>` |
| Node operating system | `<os-and-version>` |
| Storage class | `<storage-class>` |
| Storage backend | `<backend>` |
| Neo4j version | `<version>` |
| Neo4j image | `<image-and-digest>` |
| Java version in the image | `<version>` |
| Neo4j Kubernetes operator version | `<version>` |
| Neo4j license | `<license-type>` |
| GDS version and edition | `<version>`, `<edition>` |

## Tests to run

Run the tests in order, with two exceptions. Check the Neo4j pods for O2 after C1, because they do not exist before it. Run O3 last, because the later areas need the operator. A failure in an earlier area can block the areas after it.

### Platform

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| P1 | Check the node architecture | All worker nodes report `s390x`. | Not run | |
| P2 | Check image availability | A Neo4j image for `s390x` pulls and its entrypoint starts. Record the source of the image. | Not run | |
| P3 | Check the operator image | An operator image for `s390x` pulls and starts. Record the source of the image. | Not run | |
| P4 | Check storage | A persistent volume claim binds on the chosen storage class, and a test pod writes to it and reads it back. | Not run | |

### Operator

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| O1 | Install the operator | The operator pod reaches `Running` and its custom resource definitions are present. | Not run | |
| O2 | Check security constraints | The operator and Neo4j pods run under the intended OpenShift security context constraint. Record any extra permissions they need. | Not run | |
| O3 | Remove the operator | Run this test last. Uninstalling leaves no operator pods, and the result for data volumes is recorded. | Not run | |

### Cluster

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| C1 | Deploy a three-member cluster | All three pods reach `Ready`. | Not run | |
| C2 | Check cluster formation | `SHOW SERVERS` lists three servers as `Enabled` and `Available`. | Not run | |
| C3 | Check databases | `neo4j` and `system` are online on all three members, and each has one writer. | Not run | |
| C4 | Check replication | A node written through one member can be read directly from the other two. | Not run | |
| C5 | Run the client test | A routed driver writes through the writer, reads from a follower, and all rows match. | Not run | |
| C6 | Check version and edition | `dbms.components()` reports the expected version and Enterprise edition. | Not run | |
| C7 | Connect from outside the cluster | A client connects over Bolt and the browser loads. Record the method, such as a port forward or a route. | Not run | |

### Resilience

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| R1 | Delete a follower pod | Writes keep working, and the pod returns and catches up. | Not run | |
| R2 | Delete the writer pod | A new writer is elected, and the pod returns and catches up. Record the time with no writer. | Not run | |
| R3 | Drain a worker node | The pods on that node move or wait as designed, and the cluster keeps its quorum. | Not run | |
| R4 | Watch for Java VM crashes | The cluster runs for at least 3 hours under periodic load with no pod restarts and no `hs_err` crash reports. See the note below. | Not run | |

The VM tests saw intermittent `SIGSEGV` crashes in the Java C2 compiler on `s390x`. Details are in the [VM crash section](../vm/IBMZ-VM-TEST-RESULTS.md#java-vm-crash). Save any crash report from the pod before it restarts, because the pod file system may be lost. Record the restart count of every pod.

### Operations

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| A1 | Scale the cluster | A fourth member joins as a Secondary and hosts databases as expected. | Not run | |
| A2 | Back up and restore | A backup completes, and a restore returns every test row. | Not run | |
| A3 | Rolling upgrade | Members restart one at a time and the cluster stays writable. Skip this test if only one version is available on `s390x`. | Not run | |

### Graph Data Science

These tests need three primaries plus one Secondary member, and an Enterprise license. GDS runs on the Secondary.

| ID | Test | Pass condition | Result | Notes |
| --- | --- | --- | --- | --- |
| G1 | Load the plugin | `gds.version()` returns the expected version. | Not run | |
| G2 | Run the known-answer checks | WCC, PageRank, Dijkstra, and write back match answers computed in Python, as in `tests/gds-test.py`. | Not run | |
| G3 | Run the load check | The same checks pass on a generated graph with 100,000 relationships. | Not run | |

## Results

Add the details for each area here as the tests finish.

### Platform results

`<what-passed-and-what-did-not>`

### Operator results

`<what-passed-and-what-did-not>`

### Cluster results

`<what-passed-and-what-did-not>`

### Resilience results

`<what-passed-and-what-did-not>`

### Operations results

`<what-passed-and-what-did-not>`

### Graph Data Science results

`<what-passed-and-what-did-not>`

## Issues

| ID | Test | Summary | Status | Evidence |
| --- | --- | --- | --- | --- |
| | | | | |

## Warnings seen

- `<warning-and-its-effect>`
