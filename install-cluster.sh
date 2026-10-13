#!/usr/bin/env bash
#
# Interactive installer for a three-member Neo4j Enterprise cluster on one Ubuntu machine.
# It automates the steps in cluster.md and explains each one before running it.
#
# Usage:
#   ./install-cluster.sh [install|verify|reset|uninstall|cleanup] [-y|--yes]
#
#   cleanup removes every earlier Neo4j install on this machine: the single node from
#   install-single.sh, any cluster members, and apt packages. Install offers to run it first.
#
# Environment overrides:
#   NEO4J_VERSION      Neo4j version to install            (default 2026.09.0)
#   TARBALL_PATH       Path to the Neo4j tarball           (default: next to this script)
#   NEO4J_PW           Initial password, skips the prompt
#   BASE_DIR           Parent directory for the instances  (default /opt)
#   HEAP               Heap size for each member           (default 1g, smaller under 7000 MB RAM)
#   PAGECACHE          Page cache size for each member     (default 512m, smaller under 7000 MB RAM)
#   LISTEN_ADDRESS     127.0.0.1 or 0.0.0.0                (default asks, 127.0.0.1 recommended)
#   ADVERTISED_ADDRESS Hostname or IP members advertise    (default localhost)
#   NEO4J_LICENSE      eval or commercial                  (default asks, eval)

set -Eeuo pipefail
# With set -E the trap also fires inside $(...) subshells, so report only from the main shell.
on_err() {
  [[ $BASHPID == "$$" ]] || return 0
  echo "ERROR: command failed at line $1. Fix the problem and re-run; completed steps are skipped or safely repeated." >&2
}
trap 'on_err $LINENO' ERR

VERSION="${NEO4J_VERSION:-2026.09.0}"
BASE_DIR="${BASE_DIR:-/opt}"
# Remember whether the user chose these, so preflight only auto-sizes the ones left at default.
HEAP_SET="${HEAP:+1}"
PAGECACHE_SET="${PAGECACHE:+1}"
HEAP="${HEAP:-1g}"
PAGECACHE="${PAGECACHE:-512m}"
LISTEN="${LISTEN_ADDRESS:-}"
ADVERTISED="${ADVERTISED_ADDRESS:-}"
LICENSE="${NEO4J_LICENSE:-}"
MEMBERS=(1 2 3)
WORK_DIR="/tmp/neo4j-cluster-install"
TARBALL_PATH="${TARBALL_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/neo4j-enterprise-${VERSION}-unix.tar.gz}"
UNIT_FILE="/etc/systemd/system/neo4j@.service"
SINGLE_DIR="${BASE_DIR}/neo4j-single"
SINGLE_SERVICE="neo4j-single"
SINGLE_UNIT="/etc/systemd/system/${SINGLE_SERVICE}.service"
MARK_BEGIN="# BEGIN install-cluster.sh"
MARK_END="# END install-cluster.sh"

ACTION="install"
YES=0
for arg in "$@"; do
  case "$arg" in
    install | verify | reset | uninstall | cleanup) ACTION="$arg" ;;
    -y | --yes) YES=1 ;;
    -h | --help)
      awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "This script needs root. Re-running with sudo..."
  exec sudo -E bash "$0" "$@"
fi

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi

# ---------------------------------------------------------------- helpers

STEP_NO=0
step() {
  STEP_NO=$((STEP_NO + 1))
  echo
  echo "${BOLD}==> Step ${STEP_NO}: $1${RESET}"
}
explain() { echo "${DIM}    $*${RESET}"; }
ok() { echo "    ${GREEN}OK${RESET} $*"; }
warn() { echo "    ${YELLOW}WARN${RESET} $*"; }
die() { echo "    ${RED}FAIL${RESET} $*" >&2; exit 1; }

pause() {
  (( YES )) && return 0
  read -rp "    Press Enter to continue (Ctrl+C to quit) " _
}

# confirm "question" default(y|n)
confirm() {
  local q="$1" def="${2:-y}" reply hint
  if (( YES )); then [[ $def == y ]]; return; fi
  [[ $def == y ]] && hint="[Y/n]" || hint="[y/N]"
  read -rp "    $q $hint " reply
  reply="${reply:-$def}"
  [[ $reply =~ ^[Yy] ]]
}

dir_of() { echo "${BASE_DIR}/neo4j-$1"; }
offset_of() { echo $(((${1} - 1) * 10)); }
bolt_port() { echo $((7687 + $(offset_of "$1"))); }
http_port() { echo $((7474 + $(offset_of "$1"))); }
https_port() { echo $((7473 + $(offset_of "$1"))); }
cluster_port() { echo $((6000 + $(offset_of "$1"))); }
raft_port() { echo $((7000 + $(offset_of "$1"))); }
routing_port() { echo $((7688 + $(offset_of "$1"))); }
backup_port() { echo $((6362 + $(offset_of "$1"))); }

services() { local s=(); for n in "${MEMBERS[@]}"; do s+=("neo4j@${n}"); done; echo "${s[@]}"; }

# os_release_field <name>, read in a subshell so it cannot overwrite VERSION
os_release_field() {
  # shellcheck disable=SC1091
  ( . /etc/os-release; printf '%s' "${!1:-}" )
}

get_password() {
  [[ -n "${NEO4J_PW:-}" ]] && return 0
  local p1 p2
  while true; do
    read -rsp "    Choose the neo4j password (8+ characters): " p1; echo
    if [[ ${#p1} -lt 8 ]]; then warn "Password must be at least 8 characters."; continue; fi
    read -rsp "    Confirm password: " p2; echo
    if [[ $p1 != "$p2" ]]; then warn "Passwords do not match."; continue; fi
    NEO4J_PW="$p1"
    break
  done
}

# cypher <address> <database> <query>
cypher() {
  NEO4J_PASSWORD="$NEO4J_PW" "$(dir_of 1)/bin/cypher-shell" \
    -a "$1" -u neo4j -d "$2" --format plain "$3"
}

available_count() {
  local n
  n=$(cypher neo4j://localhost:7687 system \
    "SHOW SERVERS YIELD state, health WHERE state = 'Enabled' AND health = 'Available' RETURN count(*) AS n;" \
    2>/dev/null | tail -n1 || true)
  [[ $n =~ ^[0-9]+$ ]] || n=0
  echo "$n"
}

# wait_for_available <count> <timeout seconds>
wait_for_available() {
  local want="$1" timeout="$2" waited=0 got
  printf "    Waiting for %s available servers" "$want"
  while (( waited < timeout )); do
    got=$(available_count)
    if (( got >= want )); then echo; ok "$got servers are Enabled and Available."; return 0; fi
    printf "."
    sleep 5
    waited=$((waited + 5))
  done
  echo
  return 1
}

# read_from_member <member number> <expected message>, retries while the follower catches up
read_from_member() {
  local n="$1" msg="$2" tries=0 out
  while (( tries < 12 )); do
    out=$(cypher "bolt://localhost:$(bolt_port "$n")" neo4j \
      "MATCH (t:ClusterTest {msg: '${msg}'}) RETURN t.msg;" 2>/dev/null | tail -n1 || true)
    if [[ $out == "\"${msg}\"" ]]; then return 0; fi
    sleep 5
    tries=$((tries + 1))
  done
  return 1
}

need_cluster_files() {
  [[ -x "$(dir_of 1)/bin/cypher-shell" ]] || die "$(dir_of 1) not found. Run './install-cluster.sh install' first."
}

# ---------------------------------------------------------------- steps

preflight() {
  step "Preflight checks"
  explain "Checks the OS, memory, disk space, and that the ports we need are free."
  pause

  if [[ -r /etc/os-release ]]; then
    local os_id os_version_id os_pretty
    os_id=$(os_release_field ID)
    os_version_id=$(os_release_field VERSION_ID)
    os_pretty=$(os_release_field PRETTY_NAME)
    if [[ $os_id == ubuntu && ( $os_version_id == "22.04" || $os_version_id == "24.04" ) ]]; then
      ok "Ubuntu ${os_version_id} is supported."
    else
      warn "Detected ${os_pretty:-unknown OS}. This guide targets Ubuntu Server 22.04 or 24.04."
      confirm "Continue anyway?" n || exit 1
    fi
  fi

  command -v apt-get > /dev/null || die "apt-get not found. This script supports Ubuntu and Debian only."

  local arch
  arch=$(uname -m)
  case $arch in
    x86_64 | aarch64) ok "Architecture ${arch}." ;;
    *) warn "Architecture ${arch}. Neo4j documents support only for x86_64 and ARM, so this platform is unsupported." ;;
  esac

  local mem_mb cpus
  mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
  cpus=$(nproc)
  if (( mem_mb < 7000 )); then
    warn "Only ${mem_mb} MB RAM detected. Three members need about 8 GB with the default memory settings."
    # Per member: leave 1 GB for the OS, split the rest three ways, and keep 384 MB for JVM
    # overhead outside the heap. Heap gets two thirds of what is left, page cache the rest.
    local usable_mb=$(((mem_mb - 1024) / 3 - 384))
    local heap_mb=$((usable_mb * 2 / 3 / 128 * 128))
    ((heap_mb < 512)) && heap_mb=512
    ((heap_mb > 1024)) && heap_mb=1024
    local pagecache_mb=$(((usable_mb - heap_mb) / 64 * 64))
    ((pagecache_mb < 128)) && pagecache_mb=128
    ((pagecache_mb > 512)) && pagecache_mb=512
    [[ -n $HEAP_SET ]] || HEAP="${heap_mb}m"
    [[ -n $PAGECACHE_SET ]] || PAGECACHE="${pagecache_mb}m"
    warn "Using HEAP=${HEAP} PAGECACHE=${PAGECACHE} per member. Set HEAP and PAGECACHE to override."
    confirm "Continue anyway?" n || exit 1
  else
    ok "${mem_mb} MB RAM, ${cpus} vCPUs."
  fi

  mkdir -p "$BASE_DIR"
  local avail_gb fstype
  avail_gb=$(df -BG --output=avail "$BASE_DIR" | tail -n1 | tr -dc '0-9')
  fstype=$(df --output=fstype "$BASE_DIR" | tail -n1 | tr -d ' ')
  (( avail_gb >= 10 )) && ok "${avail_gb} GB free in ${BASE_DIR}." || warn "Only ${avail_gb} GB free in ${BASE_DIR}."
  if [[ $fstype == ext4 || $fstype == xfs ]]; then
    ok "Filesystem is ${fstype}."
  else
    warn "Filesystem is ${fstype}. Neo4j supports only ext4 and xfs on Linux."
  fi

  if systemctl is-active --quiet neo4j@1 2> /dev/null; then
    ok "Members are already running; skipping the port check."
  else
    local busy=() p
    for n in "${MEMBERS[@]}"; do
      for p in "$(bolt_port "$n")" "$(http_port "$n")" "$(https_port "$n")" "$(cluster_port "$n")" \
        "$(raft_port "$n")" "$(routing_port "$n")" "$(backup_port "$n")"; do
        if ss -ltn "sport = :${p}" | grep -q LISTEN; then busy+=("$p"); fi
      done
    done
    if (( ${#busy[@]} )); then
      die "These ports are already in use: ${busy[*]}. Stop whatever uses them and re-run."
    fi
    ok "All required ports are free."
  fi
}

choose_settings() {
  step "Choose network and license settings"
  explain "Listening on 127.0.0.1 keeps every port closed to the network. Use an SSH tunnel to reach it."
  explain "Listening on 0.0.0.0 opens the ports to anything that can reach this machine. Add a firewall and TLS first."
  if [[ -z $LISTEN ]]; then
    if confirm "Listen on localhost only (recommended)?" y; then LISTEN="127.0.0.1"; else LISTEN="0.0.0.0"; fi
  fi
  if [[ -z $ADVERTISED ]]; then
    ADVERTISED="localhost"
    if [[ $LISTEN == "0.0.0.0" ]]; then
      read -rp "    Hostname or IP that clients and members use to reach this machine: " ADVERTISED
      [[ -n $ADVERTISED ]] || die "An advertised address is required when listening on all interfaces."
    fi
  fi
  ok "Listen address: ${LISTEN}, advertised address: ${ADVERTISED}."

  explain "Enterprise Edition needs a license agreement. 'eval' accepts the Neo4j Evaluation Agreement."
  explain "'commercial' accepts the commercial agreement."
  if [[ -z $LICENSE ]]; then
    if confirm "Accept the evaluation license?" y; then LICENSE="eval"; else LICENSE="commercial"; fi
  fi
  [[ $LICENSE == eval || $LICENSE == commercial ]] || die "NEO4J_LICENSE must be 'eval' or 'commercial'."
  ok "License: ${LICENSE}."
}

install_java() {
  step "Install Java"
  explain "Neo4j ${VERSION} needs Java 21 or Java 25. The 'universe' apt repository must be enabled."
  pause

  apt-get update -qq
  apt-get install -y -qq software-properties-common curl ca-certificates > /dev/null
  add-apt-repository -y universe > /dev/null
  apt-get update -qq

  local major=""
  if command -v java > /dev/null; then
    major=$(java -version 2>&1 | awk -F'"' '/version/ {print $2}' | cut -d. -f1)
  fi
  if [[ $major == 21 || $major == 25 ]]; then
    ok "Java ${major} is already the default."
  else
    apt-get install -y -qq openjdk-21-jre-headless > /dev/null
    major=$(java -version 2>&1 | awk -F'"' '/version/ {print $2}' | cut -d. -f1)
    if [[ $major != 21 && $major != 25 ]]; then
      update-java-alternatives --list || true
      die "The default Java is version ${major:-unknown}. Run: sudo update-java-alternatives --jre --set <java21name>"
    fi
    ok "Installed Java ${major}."
  fi
}

create_user() {
  step "Create the neo4j user and group"
  explain "Neo4j runs as an unprivileged 'neo4j' user."
  pause
  getent group neo4j > /dev/null || groupadd neo4j
  id neo4j > /dev/null 2>&1 || useradd -g neo4j -s /bin/bash neo4j
  ok "User and group 'neo4j' exist."
}

unpack_neo4j() {
  step "Unpack Neo4j Enterprise ${VERSION}"
  explain "Unpacks ${TARBALL_PATH} to ${WORK_DIR}."
  pause
  [[ -f $TARBALL_PATH ]] || die "${TARBALL_PATH} not found. Copy neo4j-enterprise-${VERSION}-unix.tar.gz next to this script or set TARBALL_PATH."
  tar tzf "$TARBALL_PATH" > /dev/null 2>&1 || die "${TARBALL_PATH} is not a valid gzip tarball. Copy it to this machine again."
  mkdir -p "$WORK_DIR"
  if [[ ! -d "${WORK_DIR}/neo4j-enterprise-${VERSION}" ]]; then
    tar zxf "$TARBALL_PATH" -C "$WORK_DIR"
  fi
  ok "Unpacked to ${WORK_DIR}/neo4j-enterprise-${VERSION}."
}

create_instances() {
  step "Create the three instance directories"
  explain "Copies the unpacked install to $(dir_of 1), $(dir_of 2), and $(dir_of 3)."
  explain "Each member gets its own binaries, config, data, and logs."
  pause
  local group="adm"
  getent group adm > /dev/null || group="neo4j"
  for n in "${MEMBERS[@]}"; do
    local d
    d=$(dir_of "$n")
    if [[ -d $d ]]; then
      ok "$d already exists; keeping it."
    else
      cp -a "${WORK_DIR}/neo4j-enterprise-${VERSION}" "$d"
      ok "Created $d."
    fi
    chown -R "neo4j:${group}" "$d"
  done
}

write_config() {
  step "Write the cluster configuration"
  explain "Appends a managed block to each member's conf/neo4j.conf. Re-running replaces that block."
  explain "All members share the same discovery list and ask for 3 primaries."
  explain "Ports are offset by 10 per member so the three instances do not collide."
  pause

  local endpoints=""
  for n in "${MEMBERS[@]}"; do
    endpoints+="${ADVERTISED}:$(cluster_port "$n"),"
  done
  endpoints="${endpoints%,}"

  for n in "${MEMBERS[@]}"; do
    local conf
    conf="$(dir_of "$n")/conf/neo4j.conf"
    sed -i "/${MARK_BEGIN}/,/${MARK_END}/d" "$conf"
    cat >> "$conf" << EOF
${MARK_BEGIN}
server.default_listen_address=${LISTEN}
server.default_advertised_address=${ADVERTISED}
dbms.cluster.endpoints=${endpoints}
initial.dbms.default_primaries_count=3

server.bolt.listen_address=:$(bolt_port "$n")
server.bolt.advertised_address=:$(bolt_port "$n")
server.http.listen_address=:$(http_port "$n")
server.http.advertised_address=:$(http_port "$n")
server.https.listen_address=:$(https_port "$n")
server.https.advertised_address=:$(https_port "$n")
server.cluster.listen_address=:$(cluster_port "$n")
server.cluster.advertised_address=:$(cluster_port "$n")
server.cluster.raft.listen_address=:$(raft_port "$n")
server.cluster.raft.advertised_address=:$(raft_port "$n")
server.routing.listen_address=:$(routing_port "$n")
server.routing.advertised_address=:$(routing_port "$n")
server.backup.listen_address=127.0.0.1:$(backup_port "$n")

server.memory.heap.initial_size=${HEAP}
server.memory.heap.max_size=${HEAP}
server.memory.pagecache.size=${PAGECACHE}
${MARK_END}
EOF
    ok "Configured member ${n} (bolt $(bolt_port "$n"), http $(http_port "$n"), cluster $(cluster_port "$n"))."
  done
}

accept_license() {
  step "Accept the Enterprise license"
  explain "Runs 'neo4j-admin server license' on each member."
  pause
  local flag="--accept-evaluation"
  [[ $LICENSE == commercial ]] && flag="--accept-commercial"
  for n in "${MEMBERS[@]}"; do
    runuser -u neo4j -- "$(dir_of "$n")/bin/neo4j-admin" server license "$flag"
  done
  ok "License accepted on all members."
}

set_password() {
  step "Set the initial password"
  explain "All members need the same initial password, set before the first start."
  explain "Once a member has started, the password lives in the system database and this step is skipped."
  pause
  get_password
  for n in "${MEMBERS[@]}"; do
    local d
    d=$(dir_of "$n")
    if [[ -d "${d}/data/databases/system" ]]; then
      warn "Member ${n} has already started once; keeping its existing password."
    else
      runuser -u neo4j -- "${d}/bin/neo4j-admin" dbms set-initial-password "$NEO4J_PW" > /dev/null
      ok "Password set on member ${n}."
    fi
  done
}

create_services() {
  step "Create the systemd service"
  explain "One template unit ${UNIT_FILE} runs every member. neo4j@1 uses ${BASE_DIR}/neo4j-1, and so on."
  pause
  cat > "$UNIT_FILE" << EOF
[Unit]
Description=Neo4j Graph Database member %i
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${BASE_DIR}/neo4j-%i/bin/neo4j console
Restart=on-abnormal
User=neo4j
Group=neo4j
Environment="NEO4J_CONF=${BASE_DIR}/neo4j-%i/conf" "NEO4J_HOME=${BASE_DIR}/neo4j-%i"
LimitNOFILE=60000
TimeoutSec=120

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  ok "Service template installed."
  if confirm "Start the cluster automatically at boot?" y; then
    # shellcheck disable=SC2046
    systemctl enable $(services) > /dev/null 2>&1
    ok "Enabled at boot."
  fi
}

start_cluster() {
  step "Start the cluster"
  explain "Start order does not matter. The cluster forms once all three members find each other."
  pause
  # shellcheck disable=SC2046
  systemctl start $(services)
  get_password
  if wait_for_available 3 240; then
    return 0
  fi
  warn "The cluster did not report 3 available servers in time."
  warn "Check: journalctl -u neo4j@1 --no-pager -n 100"
  warn "Re-run './install-cluster.sh verify' once the members finish joining."
  return 1
}

verify_cluster() {
  step "Verify the cluster"
  explain "Lists the servers and the databases they host."
  pause
  need_cluster_files
  get_password
  echo
  cypher neo4j://localhost:7687 system "SHOW SERVERS;"
  echo
  cypher neo4j://localhost:7687 system "SHOW DATABASES;"
  echo
}

replication_test() {
  step "Replication test"
  explain "Writes a node through the routing driver, then reads it directly from members 2 and 3."
  confirm "Run the replication test?" y || return 0
  need_cluster_files
  get_password
  local msg
  msg="hello-$(date +%s)"
  cypher neo4j://localhost:7687 neo4j "CREATE (:ClusterTest {msg: '${msg}'});"
  for n in 2 3; do
    if read_from_member "$n" "$msg"; then
      ok "Member ${n} returned the node written through member 1."
    else
      warn "Member ${n} did not return the node within 60 seconds."
    fi
  done
  cypher neo4j://localhost:7687 neo4j "MATCH (t:ClusterTest {msg: '${msg}'}) DELETE t;" || true
}

failover_test() {
  step "Failover test"
  explain "Stops member 2, confirms writes still work with 2 of 3 members, then restarts it."
  confirm "Run the failover test?" n || return 0
  need_cluster_files
  get_password
  systemctl stop neo4j@2
  ok "Stopped neo4j@2."
  sleep 10
  local msg
  msg="failover-$(date +%s)"
  if cypher neo4j://localhost:7687 neo4j "CREATE (:ClusterTest {msg: '${msg}'});"; then
    ok "Write succeeded with one member down."
  else
    warn "Write failed with one member down."
  fi
  systemctl start neo4j@2
  ok "Restarted neo4j@2."
  wait_for_available 3 180 || warn "Member 2 has not rejoined yet."
  if read_from_member 2 "$msg"; then
    ok "Member 2 caught up and has the node written while it was down."
  else
    warn "Member 2 has not caught up yet."
  fi
  cypher neo4j://localhost:7687 neo4j "MATCH (t:ClusterTest {msg: '${msg}'}) DELETE t;" || true
}

summary() {
  echo
  echo "${BOLD}Done.${RESET} Your three-member cluster is running."
  echo
  echo "  Bolt:     neo4j://localhost:$(bolt_port 1)  (members on $(bolt_port 2) and $(bolt_port 3))"
  echo "  Browser:  http://localhost:$(http_port 1)"
  echo "  User:     neo4j"
  echo
  echo "From your laptop, tunnel the ports and open Neo4j Browser:"
  echo "  ssh -L $(http_port 1):localhost:$(http_port 1) -L $(bolt_port 1):localhost:$(bolt_port 1) \\"
  echo "      -L $(bolt_port 2):localhost:$(bolt_port 2) -L $(bolt_port 3):localhost:$(bolt_port 3) <user>@<server-ip>"
  echo
  echo "Useful commands:"
  echo "  systemctl status neo4j@1 neo4j@2 neo4j@3"
  echo "  journalctl -u neo4j@1 -f"
  echo "  $0 verify | reset | uninstall"
}

# ---------------------------------------------------------------- cleanup

LEFTOVERS=()
APT_PKGS=()
CONFLICTS=0

# Fills LEFTOVERS with a description of each earlier install found.
# Sets CONFLICTS=1 when the single node or an apt package would collide with the cluster ports.
find_leftovers() {
  LEFTOVERS=()
  APT_PKGS=()
  CONFLICTS=0

  if [[ -d $SINGLE_DIR || -f $SINGLE_UNIT ]]; then
    LEFTOVERS+=("Single node: ${SINGLE_DIR} and the ${SINGLE_SERVICE} service")
    CONFLICTS=1
  fi

  local members=() n
  for n in "${MEMBERS[@]}"; do
    if [[ -d "$(dir_of "$n")" ]]; then members+=("$(dir_of "$n")"); fi
  done
  if (( ${#members[@]} )) || [[ -f $UNIT_FILE ]]; then
    LEFTOVERS+=("Cluster members: ${members[*]:-none} and the neo4j@ service template")
  fi

  mapfile -t APT_PKGS < <(dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' 'neo4j*' 2> /dev/null | awk '$1 ~ /^ii/ {print $2}')
  if (( ${#APT_PKGS[@]} )); then
    LEFTOVERS+=("apt packages: ${APT_PKGS[*]}")
    CONFLICTS=1
  fi

  if id neo4j > /dev/null 2>&1 && pgrep -u neo4j java > /dev/null; then
    LEFTOVERS+=("Running Java processes owned by the neo4j user")
  fi
}

show_leftovers() {
  local item
  for item in "${LEFTOVERS[@]}"; do echo "      - ${item}"; done
}

cleanup_all() {
  local units=("$SINGLE_SERVICE")
  for n in "${MEMBERS[@]}"; do units+=("neo4j@${n}"); done
  units+=(neo4j)

  systemctl stop "${units[@]}" 2> /dev/null || true
  systemctl disable "${units[@]}" 2> /dev/null || true
  rm -f "$SINGLE_UNIT" "$UNIT_FILE"
  systemctl daemon-reload
  ok "Stopped and removed the Neo4j services."

  if id neo4j > /dev/null 2>&1 && pgrep -u neo4j java > /dev/null; then
    pkill -TERM -u neo4j java || true
    sleep 5
    pkill -KILL -u neo4j java 2> /dev/null || true
    ok "Stopped leftover Neo4j processes."
  fi

  rm -rf "$SINGLE_DIR"
  for n in "${MEMBERS[@]}"; do rm -rf "$(dir_of "$n")"; done
  ok "Removed the single node and cluster member directories."

  if (( ${#APT_PKGS[@]} )); then
    apt-get purge -y -qq "${APT_PKGS[@]}" > /dev/null
    ok "Purged apt packages: ${APT_PKGS[*]}."
    local d
    for d in /var/lib/neo4j /var/log/neo4j /etc/neo4j; do
      if [[ -d $d ]]; then
        if confirm "Delete leftover ${d}?" n; then rm -rf "$d"; ok "Deleted ${d}."; else warn "Left ${d} in place."; fi
      fi
    done
  fi

  if [[ -d $WORK_DIR ]]; then
    if confirm "Also delete the unpacked copy in ${WORK_DIR}?" n; then
      rm -rf "$WORK_DIR"
      ok "Deleted ${WORK_DIR}."
    fi
  fi

  if id neo4j > /dev/null 2>&1; then
    if confirm "Also remove the neo4j user and group?" n; then
      userdel neo4j || true
      if getent group neo4j > /dev/null; then groupdel neo4j || true; fi
      ok "Removed the neo4j user and group."
    fi
  fi
}

offer_cleanup() {
  step "Check for earlier installs"
  explain "Looks for a single node, old cluster members, or apt packages left from earlier tests."
  find_leftovers
  if (( ${#LEFTOVERS[@]} == 0 )); then
    ok "No earlier install found."
    return 0
  fi
  echo "    Found:"
  show_leftovers
  local def="n"
  if (( CONFLICTS )); then
    def="y"
    warn "The single node or apt packages use the default ports and will block cluster member 1."
  else
    explain "Re-running install reuses the existing members. Choose y for a clean slate."
  fi
  if confirm "Remove all of this, including data?" "$def"; then
    cleanup_all
  elif (( CONFLICTS )); then
    warn "Leaving it in place. The port check will stop the install if the ports are busy."
  fi
}

# ---------------------------------------------------------------- actions

do_cleanup() {
  step "Clean up earlier installs"
  find_leftovers
  if (( ${#LEFTOVERS[@]} == 0 )); then
    ok "Nothing to clean up."
    return 0
  fi
  echo "    Found:"
  show_leftovers
  warn "This deletes all data in the installs listed above."
  (( YES )) || confirm "Delete all of this?" n || exit 0
  cleanup_all
  ok "Clean. Run './install-cluster.sh install' to build the cluster."
}

do_install() {
  echo "${BOLD}Neo4j ${VERSION} Enterprise: three-member cluster on one machine${RESET}"
  echo "This script walks through each step and explains what it does before running it."
  (( YES )) || echo "Press Enter to move to the next step."
  offer_cleanup
  preflight
  choose_settings
  install_java
  create_user
  unpack_neo4j
  create_instances
  write_config
  accept_license
  set_password
  create_services
  if start_cluster; then
    verify_cluster
    replication_test
    failover_test
    summary
  else
    exit 1
  fi
}

do_verify() {
  verify_cluster
  replication_test
  failover_test
}

do_reset() {
  step "Reset the cluster"
  warn "This deletes the databases, transaction logs, and cluster state of all members."
  confirm "Delete all data and start over?" n || exit 0
  # shellcheck disable=SC2046
  systemctl stop $(services) || true
  for n in "${MEMBERS[@]}"; do
    rm -rf "$(dir_of "$n")/data/databases" "$(dir_of "$n")/data/transactions" "$(dir_of "$n")/data/cluster-state"
  done
  ok "Data removed."
  set_password
  # shellcheck disable=SC2046
  systemctl start $(services)
  wait_for_available 3 240 || warn "The cluster has not fully formed yet."
}

do_uninstall() {
  step "Uninstall"
  warn "This stops the cluster and deletes ${BASE_DIR}/neo4j-1, -2, and -3 including all data."
  confirm "Remove everything?" n || exit 0
  # shellcheck disable=SC2046
  systemctl stop $(services) 2> /dev/null || true
  # shellcheck disable=SC2046
  systemctl disable $(services) 2> /dev/null || true
  rm -f "$UNIT_FILE"
  systemctl daemon-reload
  for n in "${MEMBERS[@]}"; do rm -rf "$(dir_of "$n")"; done
  ok "Cluster removed. The 'neo4j' user, Java, and ${WORK_DIR} were left in place."
}

case "$ACTION" in
  install) do_install ;;
  verify) do_verify ;;
  reset) do_reset ;;
  uninstall) do_uninstall ;;
  cleanup) do_cleanup ;;
esac
