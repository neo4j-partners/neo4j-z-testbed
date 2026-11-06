# Java soak tests on the IBM Z VM

This note records the soak test that is running on the VM, how to collect it, and what to do next. It holds no passwords or server addresses. Those are in `tests/.env` on the laptop.

## Current state

| Item | Value |
| --- | --- |
| Test | Java 21 comparison soak of the three-member cluster |
| Started | 2026-11-04 at 22:00:51 UTC |
| Expected end | 2026-11-05 at about 09:46 UTC |
| Design | 48 rounds, 15 minutes apart |
| Systemd unit on the VM | `neo4j-soak-java21` |
| Java on the VM | OpenJDK `21.0.12.1+1-1-24.04.4-Ubuntu`, the build in the three crash reports |
| Neo4j | Enterprise 2026.09.0, 512 MB heap, 128 MB page cache, no GDS |
| Password file on the VM | `~/soak/tests/.env`, still present until the soak is collected |

The soak needs no laptop, VPN, or SSH session. A VM reboot would stop it.

## Why this soak is running

The Java VM crashed three times on Java 21 on 2026-11-04. The cause is not confirmed. Details are in the [VM crash section](vm/IBMZ-VM-TEST-RESULTS.md#java-vm-crash).

The Java 25 soak then passed 48 of 48 rounds with no crashes. That run had no control, so this soak repeats it on Java 21.

- **If Java 21 crashes:** The two versions behave differently, which favors Java 25.
- **If Java 21 stays clean:** This soak does not trigger the crash, so neither run shows whether Java 25 fixes it. The next step is a test that triggers it, such as frequent member restarts.

## How the soak works

Each round runs an unchanged copy of `tests/laptop-test.py` on the VM through `~/soak/vm-round.py`. It connects straight to the cluster with no SSH tunnel. The test writes 100 rows, reads them back, compares them, and deletes them.

Each round also checks for new crash reports and stopped members. The script saves new crash files and restarts a stopped member. It stops early after crashes in 3 rounds in a row.

## Files on the VM

| Path | Purpose |
| --- | --- |
| `~/soak/soak.log` | One line per round, plus `CRASH` lines and the end totals |
| `~/soak/rounds/round-N.log` | Test output for each round |
| `~/soak/crashes/` | New `hs_err` and replay files from this soak |
| `~/soak/java25-run/` | All logs from the finished Java 25 soak |
| `~/soak/soak-vm.sh` | The soak script |
| `~/soak/vm-round.py` | Runs one round on the VM |
| `~/soak/tests/` | Copies of the test scripts, plus `.env` |
| `~/soak/lib/` | Python driver packages, used only by this test |
| `/tmp/hs_err_pid*.log` | Crash reports written by the Java VM. Three exist from before the soaks. |

## Password file

The soak needs the Neo4j password, so it is stored in a file on the VM.

- **Source:** The source of truth is `NEO4J_PW` in `tests/.env` on the laptop. Git ignores that file.
- **VM copy:** `~/soak/tests/.env` on the VM holds only `NEO4J_PW`. Its mode is `600`, so only the `ubuntu` user can read it.
- **Backup:** The password has no other backup. If the laptop file is lost, the VM copy is the only remaining copy until it is deleted.
- **Clean up:** Delete the VM copy after collecting the soak. Run `rm -f ~/soak/tests/.env` on the VM.

## Check the soak

These commands run on the VM:

```bash
systemctl is-active neo4j-soak-java21
tail ~/soak/soak.log
grep -c ' test=0 ' ~/soak/soak.log
grep CRASH ~/soak/soak.log
```

A finished soak shows `inactive`, and the last log line starts with `soak end`.

## Collect the results

1. Connect to the VPN.
2. Confirm that `soak.log` ends with a `soak end` line.
3. Copy `~/soak/soak.log` to `vm/soak-java21-cluster.log`.
4. Copy any files in `~/soak/crashes/` to `vm/crash-reports/`. Scan them for secrets first.
5. Add the comparison to [IBMZ-VM-TEST-RESULTS.md](vm/IBMZ-VM-TEST-RESULTS.md), next to the [Java 25 soak](vm/IBMZ-VM-TEST-RESULTS.md#java-25-cluster-soak).
6. Delete `~/soak/tests/.env` on the VM.
7. Decide which Java version the VM keeps.

Asking Claude Code to "collect the soak" runs these steps. Project memory holds them too.

## Next steps

- **Java version:** Choose the version for the VM. It stays on Java 21 until changed.
- **Crash status:** The crash stays `Open` in the results unless the evidence settles it.
- **Restart test:** Run a restart-heavy test if Java 21 stays clean.
- **OpenShift:** Set up cluster access when ready, then follow [coding-agent-guide.md](openshift/coding-agent-guide.md).
- **Commits:** The README, results, guide, and soak files are not committed yet.

## If something goes wrong

**Stop the soak:** Run this on the VM. The cluster keeps running.

```bash
sudo systemctl stop neo4j-soak-java21
```

**Restart after a VM reboot:** Run these on the VM. Move the old logs first, so the new run has its own log. `~/soak/tests/.env` must still exist on the VM.

```bash
sudo systemctl start neo4j@1 neo4j@2 neo4j@3
cd ~/soak && mkdir java21-run-1 && mv soak.log rounds crashes java21-run-1/
sudo systemd-run --unit=neo4j-soak-java21 --uid=ubuntu --setenv=HOME="$HOME" \
  --working-directory="$HOME/soak" /usr/bin/bash "$HOME/soak/soak-vm.sh"
```

**Return the VM to Java 25:** Run these on the VM after the soak ends.

```bash
sudo update-java-alternatives --jre-headless --set java-1.25.0-openjdk-s390x
sudo systemctl restart neo4j@1 neo4j@2 neo4j@3
```
