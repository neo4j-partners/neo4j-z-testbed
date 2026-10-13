#!/usr/bin/env bash
#
# Interactive installer for a single Neo4j Enterprise node on one Ubuntu machine.
# Use it to check Java, the tarball, licensing, and networking before building the cluster.
# It installs from the tarball into /opt/neo4j-single and runs it as the neo4j-single service.
#
# Usage:
#   ./install-single.sh [install|verify|uninstall] [-y|--yes]
#
# Environment overrides:
#   NEO4J_VERSION      Neo4j version to install            (default 2026.09.0)
#   TARBALL_PATH       Path to the Neo4j tarball           (default: next to this script)
#   NEO4J_PW           Initial password, skips the prompt
#   BASE_DIR           Parent directory for the install    (default /opt)
#   HEAP               Heap size, for example 2g           (default: Neo4j chooses)
#   PAGECACHE          Page cache size, for example 1g     (default: Neo4j chooses)
#   LISTEN_ADDRESS     127.0.0.1 or 0.0.0.0                (default asks, 127.0.0.1 recommended)
#   ADVERTISED_ADDRESS Hostname or IP the node advertises  (default localhost)
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
HEAP="${HEAP:-}"
PAGECACHE="${PAGECACHE:-}"
LISTEN="${LISTEN_ADDRESS:-}"
ADVERTISED="${ADVERTISED_ADDRESS:-}"
LICENSE="${NEO4J_LICENSE:-}"
INSTALL_DIR="${BASE_DIR}/neo4j-single"
SERVICE="neo4j-single"
UNIT_FILE="/etc/systemd/system/${SERVICE}.service"
WORK_DIR="/tmp/neo4j-cluster-install"
TARBALL_PATH="${TARBALL_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/neo4j-enterprise-${VERSION}-unix.tar.gz}"
MARK_BEGIN="# BEGIN install-single.sh"
MARK_END="# END install-single.sh"
BOLT_PORT=7687
HTTP_PORT=7474

ACTION="install"
YES=0
for arg in "$@"; do
  case "$arg" in
    install | verify | uninstall) ACTION="$arg" ;;
    -y | --yes) YES=1 ;;
    -h | --help)
      sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
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

# cypher <query>
cypher() {
  NEO4J_PASSWORD="$NEO4J_PW" "${INSTALL_DIR}/bin/cypher-shell" \
    -a "bolt://localhost:${BOLT_PORT}" -u neo4j --format plain "$1"
}

wait_for_ready() {
  local timeout="$1" waited=0
  printf "    Waiting for Neo4j to accept connections"
  while (( waited < timeout )); do
    if cypher "RETURN 1;" > /dev/null 2>&1; then echo; ok "Neo4j is up."; return 0; fi
    printf "."
    sleep 5
    waited=$((waited + 5))
  done
  echo
  return 1
}

need_install() {
  [[ -x "${INSTALL_DIR}/bin/cypher-shell" ]] || die "${INSTALL_DIR} not found. Run './install-single.sh install' first."
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
  if (( mem_mb < 2000 )); then
    warn "Only ${mem_mb} MB RAM detected. Neo4j needs at least 2 GB."
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

  if systemctl is-active --quiet "$SERVICE" 2> /dev/null; then
    ok "The ${SERVICE} service is already running; skipping the port check."
  else
    local busy=() p
    # Enterprise opens the cluster ports (6000, 7000, 7688) even on a standalone server.
    for p in 7687 7474 7473 6362 6000 7000 7688; do
      if ss -ltn "sport = :${p}" | grep -q LISTEN; then busy+=("$p"); fi
    done
    if (( ${#busy[@]} )); then
      die "These ports are already in use: ${busy[*]}. Stop whatever uses them (for example neo4j@1) and re-run."
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
      read -rp "    Hostname or IP that clients use to reach this machine: " ADVERTISED
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
  explain "Unpacks ${TARBALL_PATH} to ${WORK_DIR}. The cluster script reuses this unpacked copy."
  pause
  [[ -f $TARBALL_PATH ]] || die "${TARBALL_PATH} not found. Copy neo4j-enterprise-${VERSION}-unix.tar.gz next to this script or set TARBALL_PATH."
  tar tzf "$TARBALL_PATH" > /dev/null 2>&1 || die "${TARBALL_PATH} is not a valid gzip tarball. Copy it to this machine again."
  mkdir -p "$WORK_DIR"
  if [[ ! -d "${WORK_DIR}/neo4j-enterprise-${VERSION}" ]]; then
    tar zxf "$TARBALL_PATH" -C "$WORK_DIR"
  fi
  ok "Unpacked to ${WORK_DIR}/neo4j-enterprise-${VERSION}."
}

create_instance() {
  step "Create the install directory"
  explain "Copies the unpacked install to ${INSTALL_DIR} and gives the neo4j user ownership."
  pause
  local group="adm"
  getent group adm > /dev/null || group="neo4j"
  if [[ -d $INSTALL_DIR ]]; then
    ok "${INSTALL_DIR} already exists; keeping it."
  else
    cp -a "${WORK_DIR}/neo4j-enterprise-${VERSION}" "$INSTALL_DIR"
    ok "Created ${INSTALL_DIR}."
  fi
  chown -R "neo4j:${group}" "$INSTALL_DIR"
}

write_config() {
  step "Write the configuration"
  explain "Appends a managed block to conf/neo4j.conf. Re-running replaces that block."
  explain "This is a standalone server, so no cluster settings are needed."
  pause
  local conf="${INSTALL_DIR}/conf/neo4j.conf"
  sed -i "/${MARK_BEGIN}/,/${MARK_END}/d" "$conf"
  {
    echo "$MARK_BEGIN"
    echo "server.default_listen_address=${LISTEN}"
    echo "server.default_advertised_address=${ADVERTISED}"
    if [[ -n $HEAP ]]; then
      echo "server.memory.heap.initial_size=${HEAP}"
      echo "server.memory.heap.max_size=${HEAP}"
    fi
    if [[ -n $PAGECACHE ]]; then
      echo "server.memory.pagecache.size=${PAGECACHE}"
    fi
    echo "$MARK_END"
  } >> "$conf"
  ok "Configuration written to ${conf}."
}

accept_license() {
  step "Accept the Enterprise license"
  explain "Runs 'neo4j-admin server license'."
  pause
  local flag="--accept-evaluation"
  [[ $LICENSE == commercial ]] && flag="--accept-commercial"
  runuser -u neo4j -- "${INSTALL_DIR}/bin/neo4j-admin" server license "$flag"
  ok "License accepted."
}

set_password() {
  step "Set the initial password"
  explain "The password must be set before the first start."
  explain "Once the server has started, the password lives in the system database and this step is skipped."
  pause
  get_password
  if [[ -d "${INSTALL_DIR}/data/databases/system" ]]; then
    warn "The server has already started once; keeping its existing password."
  else
    runuser -u neo4j -- "${INSTALL_DIR}/bin/neo4j-admin" dbms set-initial-password "$NEO4J_PW" > /dev/null
    ok "Password set."
  fi
}

create_service() {
  step "Create the systemd service"
  explain "Creates ${UNIT_FILE} so Neo4j runs in the background and can start at boot."
  pause
  cat > "$UNIT_FILE" << EOF
[Unit]
Description=Neo4j Graph Database (single node)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${INSTALL_DIR}/bin/neo4j console
Restart=on-abnormal
User=neo4j
Group=neo4j
Environment="NEO4J_CONF=${INSTALL_DIR}/conf" "NEO4J_HOME=${INSTALL_DIR}"
LimitNOFILE=60000
TimeoutSec=120

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  ok "Service installed."
  if confirm "Start Neo4j automatically at boot?" y; then
    systemctl enable "$SERVICE" > /dev/null 2>&1
    ok "Enabled at boot."
  fi
}

start_server() {
  step "Start Neo4j"
  explain "Starts the service and waits until it accepts Bolt connections."
  pause
  systemctl start "$SERVICE"
  get_password
  if wait_for_ready 180; then
    return 0
  fi
  warn "Neo4j did not become ready in time."
  warn "Check: journalctl -u ${SERVICE} --no-pager -n 100"
  warn "Re-run './install-single.sh verify' once it finishes starting."
  return 1
}

verify_server() {
  step "Verify the server"
  explain "Shows the version and edition, then lists the databases."
  pause
  need_install
  get_password
  echo
  cypher "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition;"
  echo
  cypher "SHOW DATABASES;"
  echo
  if cypher "CALL dbms.components() YIELD edition RETURN edition;" | grep -qi enterprise; then
    ok "Edition is enterprise."
  else
    warn "Edition is not enterprise. Check that the Enterprise tarball was installed."
  fi
}

write_read_test() {
  step "Write and read test"
  explain "Creates a node, reads it back, then deletes it."
  confirm "Run the write and read test?" y || return 0
  need_install
  get_password
  local msg
  msg="hello-$(date +%s)"
  cypher "CREATE (:SingleTest {msg: '${msg}'});"
  local out
  out=$(cypher "MATCH (t:SingleTest {msg: '${msg}'}) RETURN t.msg;" | tail -n1)
  if [[ $out == "\"${msg}\"" ]]; then
    ok "Wrote and read back the test node."
  else
    warn "Could not read the test node back."
  fi
  cypher "MATCH (t:SingleTest {msg: '${msg}'}) DELETE t;" || true
}

summary() {
  echo
  echo "${BOLD}Done.${RESET} Neo4j Enterprise is running as a single node."
  echo
  echo "  Bolt:     bolt://localhost:${BOLT_PORT}"
  echo "  Browser:  http://localhost:${HTTP_PORT}"
  echo "  User:     neo4j"
  echo
  echo "From your laptop, tunnel the ports and open Neo4j Browser:"
  echo "  ssh -L ${HTTP_PORT}:localhost:${HTTP_PORT} -L ${BOLT_PORT}:localhost:${BOLT_PORT} <user>@<server-ip>"
  echo
  echo "Useful commands:"
  echo "  systemctl status ${SERVICE}"
  echo "  journalctl -u ${SERVICE} -f"
  echo "  $0 verify | uninstall"
  echo
  echo "Before building the cluster, run '$0 uninstall' so the default ports are free."
}

# ---------------------------------------------------------------- actions

do_install() {
  echo "${BOLD}Neo4j ${VERSION} Enterprise: single node${RESET}"
  echo "This script walks through each step and explains what it does before running it."
  (( YES )) || echo "Press Enter to move to the next step."
  preflight
  choose_settings
  install_java
  create_user
  unpack_neo4j
  create_instance
  write_config
  accept_license
  set_password
  create_service
  if start_server; then
    verify_server
    write_read_test
    summary
  else
    exit 1
  fi
}

do_verify() {
  verify_server
  write_read_test
}

do_uninstall() {
  step "Uninstall"
  warn "This stops the server and deletes ${INSTALL_DIR} including all data."
  confirm "Remove everything?" n || exit 0
  systemctl stop "$SERVICE" 2> /dev/null || true
  systemctl disable "$SERVICE" 2> /dev/null || true
  rm -f "$UNIT_FILE"
  systemctl daemon-reload
  rm -rf "$INSTALL_DIR"
  ok "Node removed. The 'neo4j' user, Java, and ${WORK_DIR} were left in place."
}

case "$ACTION" in
  install) do_install ;;
  verify) do_verify ;;
  uninstall) do_uninstall ;;
esac
