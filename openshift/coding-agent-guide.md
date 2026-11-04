# Coding agent guide: OpenShift tests on IBM Z

**Goal:** This testing validates the Neo4j EE IntelliGraph bundle that Neo4j is preparing for IBM. The bundle includes Neo4j Enterprise Edition and Graph Data Science. The testing sets a baseline of what works in this package.

This guide tells a coding agent how to build the missing test code and run the OpenShift tests. The test list and pass conditions are in [IBMZ-OPENSHIFT-TEST-RESULTS.md](IBMZ-OPENSHIFT-TEST-RESULTS.md). Test IDs such as P1 and C4 refer to that file.

## Rules

- **Findings:** A failure is a result. Record it, even when a workaround exists. Record every workaround as well, because the baseline must show what needed one.
- **Test bugs:** Tell a fault in the test code apart from a fault in the product. Do not mark a test `Failed` until the test code is ruled out.
- **Bug fixes:** Discuss a fix with the user before making it. This covers the test code, the manifests, and the Neo4j configuration.
- **Scope:** Change only what a test needs. Ask before changing a Java version, a JVM flag, or a test's pass condition.
- **Commits:** Commit only when the user asks.
- **External actions:** Ask before filing an issue against any project.
- **Shared cluster:** Assume other people use the OpenShift cluster. Ask before draining a node, deleting a project, or removing a custom resource definition. Those definitions are cluster-wide.
- **VM:** Do not change the VM server. It is a separate test.
- **Secrets:** Never print or commit a password, license, or token. Keep server addresses and cluster URLs out of committed files. `tests/.env` is ignored by git, so keep those values there.
- **Support:** These results are not a statement of support from Neo4j. Neo4j documents no support for `s390x`. Neo4j also states that it does not support the Kubernetes operator.

## Ask the user first

Collect these answers before Phase 1. Stop and ask if one is missing.

| Item | Why it matters |
| --- | --- |
| Bundle version and artifacts | The test must run the bundle. See [Bundle or stand-in](#bundle-or-stand-in). |
| `oc` login method and API address | The operator install needs `cluster-admin`. |
| Target project names | The kit uses `neo4j` and `neo4j-operator-system`. |
| Storage class | P4 and every Neo4j pod depend on it. |
| Worker count and free memory | See the sizing note in [Phase 1](#phase-1-platform). |
| Neo4j license | `spec.license.accept` takes `"yes"` for a commercial license or `"eval"` for an evaluation. |
| GDS Enterprise license | G1 to G3 need it. The VM run reported the edition as `Unlicensed`. |
| Java version | See [Java version](#java-version). |
| Permission to drain a node | R3 needs it. |

## Read these sources

The operator changes often, so read these pages instead of relying on the summary here. Do not invent custom resource fields. Check each field against the API reference.

- [Operator repository](https://github.com/neo4j-partners/neo4j-kubernetes-operator)
- [IBM Z kit](https://github.com/neo4j-partners/neo4j-kubernetes-operator/tree/main/hack/openshift-s390x)
- [OpenShift quickstart](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/01-getting-started/openshift.md)
- [What works today](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/01-getting-started/feature-status.md)
- [Clustering](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/03-neo4j/02-clustering.md)
- [Plugins](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/03-neo4j/07-plugins.md)
- [Backup and restore](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/03-neo4j/10-backup-restore.md)
- [Operator-owned settings](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/05-reference/operator-owned-config.md)
- [API reference](https://github.com/neo4j-partners/neo4j-kubernetes-operator/blob/main/docs/user-guide/05-reference/api.md)
- [GDS on a Neo4j cluster](https://neo4j.com/docs/graph-data-science/current/production-deployment/neo4j-cluster/)
- [VM crash details](../vm/IBMZ-VM-TEST-RESULTS.md#java-vm-crash)

## Known facts

These were checked in November 2026. Check them again if the versions change.

- **Neo4j image:** The public `neo4j:2026.09.0-enterprise` image has no `s390x` build. It lists `amd64` and `arm64` only.
- **Operator image:** The published operator image `1.0.0` has no `s390x` build. It lists `amd64` and `arm64` only.
- **Kit:** The operator repository has a kit in `hack/openshift-s390x`. It builds both images on the `s390x` nodes and pushes them to the OpenShift internal registry.
- **Kit image contents:** The kit copies the Neo4j files from the `amd64` image and adds an `s390x` Java runtime. It uses `eclipse-temurin:21-jre`.
- **Kit test cluster:** The kit notes describe two workers with about 1 GiB free each. That is too small for these tests.
- **Laptop tools:** `oc` and `helm` 3.8 or later are missing from the laptop. `kubectl` and `docker` are installed. The kit builds in the cluster, so it does not need Docker.

## Bundle or stand-in

The VM tests used the public tarball and the GDS plugin from its `products/` directory. They did not use a bundle build. Choose the image in this order:

1. Use a bundle image for `s390x` if the bundle provides one.
2. Build from the bundle tarball with the kit's tarball variant.
3. Build with the kit's default `Dockerfile.neo4j` if the user approves a stand-in.

Option 3 does not validate the bundle. If the test uses it, say so in the P2 notes and in the Results section. Add a `Bundle version` row to the Test environment table, and record the exact bundle version or `Not the bundle`.

## Java version

The VM crashes happened on OpenJDK 21. Read the [VM crash section](../vm/IBMZ-VM-TEST-RESULTS.md#java-vm-crash) first, because it may hold a newer soak result than this guide. The root cause is not confirmed.

Use the Java version that the bundle ships. If the test uses the kit, the runtime is Java 21. Ask the user before changing it. Read the version from the image without starting a JVM:

```bash
oc exec -n neo4j <pod> -- sh -c 'cat "$JAVA_HOME/release"'
```

## What exists and what to build

Shared Python goes in `tests/`. Manifests and OpenShift scripts go in `openshift/`. Clone the operator repository outside this repository, and record its commit hash.

| Tests | Exists today | Build |
| --- | --- | --- |
| P4 | Nothing | `openshift/storage-test.yaml`, with a claim and a test pod |
| C1 | Kit sample | `openshift/neo4j-cluster.yaml`, from the starting point below |
| C2, C3, C5, C6 | `tests/laptop-test.py --via oc` | Nothing, but see the warning below |
| C4 | Only in `vm/install-cluster.sh` | A Python replication test that reads each member directly |
| C7 | The Bolt half is covered by the laptop test | A port forward for 7474 |
| R1, R2 | Only in `vm/install-cluster.sh` | A Python failover test that measures the time with no writer |
| R3 | Nothing | Manual steps recorded in the notes |
| R4 | Nothing in this repository | A soak script, as described in [R4](#r4-soak) |
| A1 to A3 | Nothing | Manifests, from the operator docs |
| G1 to G3 | `tests/gds-test.py`, VM single node only | A `--via oc` path, as described in [Phase 6](#phase-6-graph-data-science) |

`--via oc` has only run against a fake `oc`. No Neo4j traffic has gone through it, so expect to fix it in Phase 3.

Follow these conventions in the test code:

- `tests/access.py` is the only shared module that knows about the platform. A test receives an `Access` and does not open its own connection.
- Scripts run with `uv run`, and settings come from `tests/.env`. Add new settings to `tests/.env.example`.
- Use PEP 8, type hints on public functions, and the standard library first.
- Do not run `ruff check --fix`. It changes `timezone.utc` to `UTC`, which breaks the Python 3.10 floor.

## Phase 1: Platform

Log in and read the cluster:

```bash
oc whoami
oc version
oc get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.nodeInfo.architecture}{"\n"}{end}'
oc adm top nodes
oc get storageclass
oc get projects | grep -i neo4j
```

- **Existing work:** The kit may already have run on this cluster. Report any existing `neo4j` projects or custom resources to the user before changing them.
- **Version floor:** The operator chart needs Kubernetes 1.34 or later, which is OpenShift 4.21. An older cluster blocks the Operator area.
- **Sizing:** The default pod request is 2 GiB of memory and 500m of CPU. Three primaries and a GDS member need much more free memory than the kit's two small workers. The VM GDS run used a 2 GB heap. Tell the user if the workers are too small for Phase 6.
- **P2:** Use the source chosen in [Bundle or stand-in](#bundle-or-stand-in). The test passes when a test pod from the image logs `Started.`. Record the image digest.
- **P3:** Build the operator image with the kit. The operator image has no shell, so debug it from its log.
- **P4:** Write a known file to a claim on the chosen class, read it back from a new pod, and compare it. Use an image that has an `s390x` build, such as a Red Hat UBI image.
- **Storage backend:** The kit sample uses `managed-nfs-storage`. Record the backend, and check the Neo4j system requirements before treating an NFS result as a baseline.

## Phase 2: Operator

Follow steps 0 to 6 of the kit README from the root of the operator clone. It covers the projects, the builds, the custom resource definitions, and the Helm install.

- **Image references:** Do not pass `image.digest`. Set a fully qualified `spec.image.repository`, and add it to `allowedImageRepositories`.
- **Platform:** Leave `platform` at `auto`. Confirm that the operator detected OpenShift:

  ```bash
  oc logs -n neo4j-operator-system deploy/neo4j-operator-controller-manager \
    | grep "resolved operand platform"
  ```

- **O1:** The test passes when the Deployment is `Available` and `oc get crd | grep neo4j.com` lists the definitions.
- **O2:** Check the operator pod now, and the Neo4j pods after C1. The expected constraint is `restricted-v2`, with no extra grant.

  ```bash
  oc get pod <pod> -n neo4j -o jsonpath='{.metadata.annotations.openshift\.io/scc}{"\n"}'
  ```

- **O3:** Run this test last, after Phase 6. The later phases need the operator. Delete the `Neo4j` resources before uninstalling it, then follow the operator's uninstall page.

## Phase 3: Cluster

Create `openshift/neo4j-cluster.yaml` from this starting point. It uses fields from the operator docs. Check them against the API reference and fill in the placeholders.

```yaml
apiVersion: neo4j.com/v1
kind: Neo4j
metadata:
  name: z-test
  namespace: neo4j
spec:
  edition: enterprise
  version: "2026.09.0"
  image:
    repository: image-registry.openshift-image-registry.svc:5000/neo4j/neo4j
    pullPolicy: Always
  license:
    accept: "<yes-or-eval>"
  topology:
    mode: Cluster
    primaries:
      members: 3
    defaultPrimariesCount: 3
  trust:
    insecureAdminConnection: true
  resources:
    requests:
      cpu: <cpu>
      memory: <memory>
    limits:
      cpu: <cpu>
      memory: <memory>
  config:
    neo4j:
      server.memory.heap.initial_size: 512m
      server.memory.heap.max_size: 512m
      server.memory.pagecache.size: 128m
  storage:
    volumes:
      data:
        mode: Dynamic
        dynamic:
          size: 10Gi
          storageClassName: <storage-class>
  auth:
    generatePassword: true
  podDisruptionBudget:
    enabled: true
    minAvailable: 2
```

The kit's cluster sample differs from this file in two ways that matter:

- **`defaultPrimariesCount: 3`:** Without this, `neo4j` lives on one primary. C3 and C4 then cannot pass, and R1 means nothing.
- **`trust.insecureAdminConnection: true`:** The clustering docs say a cluster with neither this nor Bolt TLS is rejected. The kit sample sets neither, so its behavior may differ. This setting leaves Bolt in plain text, which matches the `neo4j://` address in `oc_access`. Using TLS needs a change to `oc_access`.

The memory values match the VM cluster. Change them only if the pods need it, and record the final values.

Deploy the cluster and wait:

```bash
oc apply -f openshift/neo4j-cluster.yaml
oc get neo4j z-test -n neo4j -w
oc get neo4j z-test -n neo4j \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} ({.reason}){"\n"}{end}'
```

Formation can take several minutes. Set up the client when `ClusterFormed` is `True`:

1. Find the pod labels with `oc get pods -n neo4j --show-labels`. The operator docs use `app.kubernetes.io/instance=z-test` for Services.
2. Set `OC_NAMESPACE` and `OC_POD_SELECTOR` in `tests/.env`.
3. Copy the generated password into `NEO4J_PW`, and do not print it. The Secret name is in `status.credentials.secretName`, and `z-test-auth` is the expected name. Its `NEO4J_AUTH` key holds the value in `user/password` form.

Before the first run, check two assumptions in `tests/access.py`:

- **Advertised names:** `host_resolver` expects the first DNS label of each advertised address to be the pod name. The operator docs describe both per-pod Services and headless Service names. Compare the `address` column of `SHOW SERVERS` with the pod names.
- **Routing mode:** Read `dbms.routing.default_router` in the rendered config. A `SERVER` value gives the driver a routing table with one address, so C5 cannot show a read on a follower. Discuss that result with the user.

```bash
oc get configmap z-test-primary-config -n neo4j -o jsonpath='{.data.neo4j\.conf}' \
  | grep -E 'routing|advertised'
```

Run the client test. It covers C2, C3, C5, and C6:

```bash
uv run tests/laptop-test.py --via oc
```

- **C2:** Read the `Servers` line.
- **C3:** Read the `Databases` line.
- **C5:** Read the `Rows` line. Also confirm that the read went to a server other than the writer.
- **C6:** The script checks only the edition. Compare the printed version with the expected version by hand.
- **C4:** Write a node through the routed driver, then read it from each member with a direct `bolt://` driver. `Access` needs a list of member URIs for this. Poll for a short time or use bookmarks, because a follower may lag.
- **C7:** Record port forwarding as the Bolt method. Forward 7474 and load the browser. If the user wants a route, note that Bolt is not HTTP, and most ingress controllers cannot route it.

Do not run `cypher-shell` or `java -version` inside a pod with a tight memory limit. The kit reports that the extra JVM can kill the container with exit code 137. Connect from the laptop instead.

## Phase 4: Resilience

These tests use the Phase 3 client, with three limits:

- **Dead forwards:** A port forward dies with its pod. Open new forwards after each delete.
- **Member count:** `oc_access` counts `Running` pods, so the `Servers` check fails while a pod is down. Read the `Rows` line during the outage. The `Servers` line is meaningful after the pod returns.
- **Terminating pods:** A deleted pod can still report `Running` for a short time. Wait until it is gone before opening forwards.

The tests work like this:

- **R1:** Find a follower with `SHOW DATABASE neo4j`. Delete its pod, then confirm writes still work. After the pod returns, confirm it holds a node written during the outage.
- **R2:** Find the writer. Delete its pod while a loop attempts a write about once per second through the surviving pods. Record the time with no writer. Confirm the catch-up as in R1.
- **R3:** Ask the user first. Run `oc adm drain <node> --ignore-daemonsets --delete-emptydir-data`, watch the pods, then run `oc adm uncordon <node>`. Record the pod placement. With two workers, two primaries can share a node, and the disruption budget may block the drain. That is a result to record.

### R4 soak

Write a soak script in `openshift/`. Use the design of the VM soak:

- Run 12 rounds, 15 minutes apart, for about 3 hours.
- Each round runs `tests/laptop-test.py --via oc`.
- Each round records the restart count and last exit code of every pod.
- Each round looks for new `hs_err` files.
- The script stops early if crashes occur in 3 rounds in a row.
- The script keeps a timestamped log.

The pod file system may be lost at restart, so plan the crash evidence before the run. Set `-XX:ErrorFile` to a path on the data volume with `spec.config.jvm.additionalArguments`. Confirm the mount path first. This rolls the pods, so run C2 and C3 again, and record the flag in the R4 notes.

```bash
oc get pods -n neo4j -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].restartCount}{" "}{.status.containerStatuses[0].lastState.terminated.exitCode}{"\n"}{end}'
oc logs -n neo4j <pod> --previous > <local-file>
```

Treat exit code 137 as a memory kill or a forced stop until the evidence shows otherwise. A Java VM crash usually exits with 134. Check the `oc logs --previous` output for the `SIGSEGV` banner.

Save crash reports in `openshift/crash-reports/`. A crash report can hold the command line and environment settings, so search it for secrets before saving it. Compare each crash with the VM signature: `SIGSEGV` in `C2 CompilerThread0`, in the `PhaseOutput` stage.

## Phase 5: Operations

Use the operator docs for these tests.

- **A1:** The operator rejects an even number of primaries, so the fourth member must be a Secondary. Add one to the read pool with `oc scale neo4j z-test -n neo4j --replicas=1`. New members host no databases until told to, so run `ALTER DATABASE neo4j SET TOPOLOGY 3 PRIMARIES 1 SECONDARY`. Confirm the new member with the laptop test, then remove it. The operator lists scale in as not tested end to end, so record the result.
- **A2:** Enable `spec.features.backup.enabled` and `spec.connectivity.listeners.backup`. This rolls the pods. Write rows with `tests/laptop-test.py --via oc --keep`, take a `Neo4jBackup`, delete the rows, and run a `Neo4jRestore`. Then confirm every row is back. The docs do not state the architecture of the backup job, so watch for an image failure on `s390x`.
- **A3:** This test needs a second `s390x` image, so skip it if only one version exists. Take a backup first, because Neo4j cannot downgrade. Change `spec.version`, then keep writing during the roll. The operator refuses this change for a digest pin.

## Phase 6: Graph Data Science

GDS runs on a Secondary. The operator's analytics pool provides one. It sets the Secondary mode for all databases, including `system`, and it sets server-side routing. GDS on a primary or a read pool member is rejected.

Add the pool to the manifest:

```yaml
spec:
  topology:
    secondaries:
      analytics:
        members: 1
        plugins: [gds]
```

Set up the license and settings:

- **License Secret:** Create the Secret and label it `neo4j.com/mountable-by-operator=true`. Reference it in `spec.pluginDefinitions.gds`. The docs show this for Standalone, so check the API reference for Cluster mode.
- **Strict validation:** Neo4j versions before 2026.11 refuse to start with a plugin setting in the operator's config. On 2026.09.0, set `server.config.strict_validation.enabled: "false"`. A misspelled key then only logs a warning, so read the startup log. Remove the setting on 2026.11 or later.
- **Procedures:** Set `dbms.security.procedures.unrestricted: "gds.*"` in `spec.config.neo4j`. The operator does not set it.
- **Memory:** The VM GDS run used a 2 GB heap and a 512 MB page cache. Check the API reference for per-pool resources and settings, so the primaries stay small.
- **Database copy:** The default Secondary count is read only at first start. On the running cluster, run `ALTER DATABASE neo4j SET TOPOLOGY 3 PRIMARIES 1 SECONDARY`.
- **Selector:** `OC_POD_SELECTOR` must also match the analytics pod. The routing table can list it, and the laptop test counts it as a member.

Read `PluginsReady` after the roll. Neo4j can start while the plugin is missing, so the pod state alone proves nothing.

```bash
oc get neo4j z-test -n neo4j -o jsonpath='{.status.conditions[?(@.type=="PluginsReady")]}'
```

Extend `tests/gds-test.py` with `--via oc`. Keep the current `--via ssh` behavior for the VM.

- **Two drivers:** Use the routed driver to create and remove test data. Use a direct `bolt://` driver to the analytics pod for all GDS calls.
- **Replication:** Test data reaches the Secondary after a delay. Pass bookmarks from the write, or poll the node count, before projecting the graph.
- **Write back:** The Secondary sends `write` procedures to the writer through server-side routing. Read the scores back through the routed driver, and allow for the same delay.
- **Load balancing:** Neo4j does not balance GDS work across Secondaries, so use one analytics member.

The tests work like this:

- **G1:** Run `RETURN gds.version()`, `RETURN gds.isLicensed()`, and `CALL gds.license.state()` on the analytics pod. A licensing failure shows up here, not at startup. GDS runs in its Community form without a license, so a passing G2 does not prove the license works. Record the edition.
- **G2:** Run `tests/gds-test.py --via oc`.
- **G3:** Run `tests/gds-test.py --via oc --rels 100000`.

G2 and G3 catch byte order faults because the laptop computes the expected answers in pure Python. Keep that comparison in place.

## Record the results

Update [IBMZ-OPENSHIFT-TEST-RESULTS.md](IBMZ-OPENSHIFT-TEST-RESULTS.md) as each test finishes:

1. Set each test's `Result` and `Notes`. Use `Blocked` when an earlier failure stops a test, and name that failure.
2. Update the counts in the Summary table. Set an area to `Passed` only when every test in it passed.
3. Fill in the Test environment table, including the image digest and the operator commit hash.
4. Add what passed and what did not under Results. Say which results came from a stand-in image.
5. Add each fault to Issues, with evidence.
6. Add each warning to Warnings seen, with its effect.

Keep the evidence, such as command output and crash reports, under `openshift/`. Remove secrets and addresses first. End with a short report to the user that lists what works in the package, what failed, what was skipped, and every workaround.
