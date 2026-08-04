#!/usr/bin/env bash
set -euo pipefail

umask 077

NODE_USER="${NODE_USER:-wepo-node}"
NODE_GROUP="${NODE_GROUP:-wepo-node}"
SIGNER_USER="${SIGNER_USER:-wepo-signer}"
SIGNER_GROUP="${SIGNER_GROUP:-wepo-signer}"
NETWORK_PROFILE="${NETWORK_PROFILE:-test}"
RELEASE_ROOT="${RELEASE_ROOT:-/opt/wepo/current}"
MAINNET_SIGNER_QUALIFICATION_ONLY="${MAINNET_SIGNER_QUALIFICATION_ONLY:-0}"
PYTHON_BIN="${PYTHON_BIN:-/opt/wepo/venv/bin/python}"
SIGNER_HOME="${SIGNER_HOME:-/var/lib/wepo-signer}"
KEY_FILE="${KEY_FILE:-${SIGNER_HOME}/private/validator-key.json}"
STATE_DB="${STATE_DB:-${SIGNER_HOME}/state/anti-equivocation.sqlite3}"
WEPO_ETC_DIR="${WEPO_ETC_DIR:-/etc/wepo}"
NODE_DATA_DIR="${NODE_DATA_DIR:-/var/lib/wepo/node}"
SUDOERS_PATH="${SUDOERS_PATH:-/etc/sudoers.d/wepo-validator-signer}"
NODE_SERVICE_NAME="${NODE_SERVICE_NAME:-wepo-node}"
INITIALIZE_KEY="${INITIALIZE_KEY:-0}"

SIGNER_SCRIPT="${RELEASE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py"
ENV_PATH="${WEPO_ETC_DIR}/validator-signer.env"
SIGNER_POLICY="${RELEASE_ROOT}/wepo-blockchain/signer/stake_transaction_policy.py"
PUBLIC_PATH="${WEPO_ETC_DIR}/validator-signer-public.json"
DROPIN_DIR="/etc/systemd/system/${NODE_SERVICE_NAME}.service.d"
DROPIN_PATH="${DROPIN_DIR}/validator-signer.conf"

log() {
    printf '[wepo-signer-install] %s\n' "$1"
}

fail() {
    log "FAIL $1"
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || fail "run as root"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_safe_name() {
    [[ "$2" =~ ^[a-z_][a-z0-9_-]{0,30}$ ]] || fail "$1 is not a safe service-account name"
}

require_absolute_path() {
    [[ "$2" == /* && "$2" != *$'\n'* && "$2" != *$'\r'* && "$2" != *' '* ]] \
        || fail "$1 must be an absolute path without whitespace"
}

require_immutable_file() {
    local path="$1"
    local resolved owner mode
    [[ -f "${path}" && ! -L "${path}" ]] || fail "immutable file is missing or is a symlink: ${path}"
    resolved="$(readlink -f "${path}")"
    [[ "${resolved}" == "${path}" ]] || fail "immutable file path is not canonical: ${path}"
    owner="$(stat -c '%u' "${path}")"
    mode="$(stat -c '%a' "${path}")"
    [[ "${owner}" == "0" ]] || fail "immutable file is not root-owned: ${path}"
    (( (8#${mode} & 8#022) == 0 )) || fail "immutable file is group/other writable: ${path}"
}

ensure_group() {
    local group_name="$1"
    getent group "${group_name}" >/dev/null 2>&1 || groupadd --system "${group_name}"
}

ensure_locked_user() {
    local user_name="$1"
    local group_name="$2"
    local home_dir="$3"
    if ! id "${user_name}" >/dev/null 2>&1; then
        useradd --system --gid "${group_name}" --home-dir "${home_dir}" \
            --shell /usr/sbin/nologin "${user_name}"
    fi
    [[ "$(id -gn "${user_name}")" == "${group_name}" ]] \
        || fail "${user_name} primary group is not ${group_name}"
    case "$(getent passwd "${user_name}" | cut -d: -f7)" in
        /usr/sbin/nologin|/sbin/nologin|/bin/false) ;;
        *) fail "${user_name} must have a non-login shell" ;;
    esac
}

render_command_json() {
    "${PYTHON_BIN}" - "${SIGNER_USER}" "${PYTHON_BIN}" "${SIGNER_SCRIPT}" \
        "${NETWORK_PROFILE}" "${KEY_FILE}" "${STATE_DB}" <<'PY'
import json
import sys

print(json.dumps([
    "/usr/bin/sudo", "-n", "-u", sys.argv[1], "--",
    sys.argv[2], sys.argv[3], "--network", sys.argv[4],
    "--key-file", sys.argv[5], "--state-db", sys.argv[6], "--stdio",
], separators=(",", ":")))
PY
}

require_root
for command_name in getent groupadd useradd install readlink stat runuser visudo; do
    require_command "${command_name}"
done

require_safe_name NODE_USER "${NODE_USER}"
require_safe_name NODE_GROUP "${NODE_GROUP}"
require_safe_name SIGNER_USER "${SIGNER_USER}"
require_safe_name SIGNER_GROUP "${SIGNER_GROUP}"
[[ "${NODE_USER}" != "${SIGNER_USER}" ]] || fail "node and signer accounts must be distinct"
[[ "${NETWORK_PROFILE}" =~ ^[a-z][a-z0-9_-]{0,31}$ ]] || fail "invalid network profile"
[[ "${NETWORK_PROFILE}" == "test" || "${NETWORK_PROFILE}" == "mainnet" ]] \
    || fail "only the supported test profile or release-gated mainnet profile may be installed"
[[ "${INITIALIZE_KEY}" == "0" || "${INITIALIZE_KEY}" == "1" ]] \
    || fail "INITIALIZE_KEY must be 0 or 1"
[[ "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "0" || "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "1" ]] \
    || fail "MAINNET_SIGNER_QUALIFICATION_ONLY must be 0 or 1"

for named_path in RELEASE_ROOT PYTHON_BIN SIGNER_HOME KEY_FILE STATE_DB WEPO_ETC_DIR NODE_DATA_DIR SUDOERS_PATH; do
    require_absolute_path "${named_path}" "${!named_path}"
done

RELEASE_ROOT="$(readlink -f "${RELEASE_ROOT}")"
PYTHON_BIN="$(readlink -f "${PYTHON_BIN}")"
SIGNER_SCRIPT="${RELEASE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py"
require_immutable_file "${PYTHON_BIN}"
SIGNER_POLICY="${RELEASE_ROOT}/wepo-blockchain/signer/stake_transaction_policy.py"
require_immutable_file "${SIGNER_SCRIPT}"
require_immutable_file "${RELEASE_ROOT}/wepo-blockchain/core/address_utils.py"
require_immutable_file "${SIGNER_POLICY}"
require_immutable_file "${RELEASE_ROOT}/wepo-blockchain/core/dilithium.py"
"${PYTHON_BIN}" -c 'from dilithium_py.ml_dsa import ML_DSA_44; assert ML_DSA_44' \
    || fail "pinned ML-DSA runtime is unavailable"

if [[ "${NETWORK_PROFILE}" == "mainnet" && "${MAINNET_SIGNER_QUALIFICATION_ONLY}" != "1" ]]; then
    if ! "${PYTHON_BIN}" - "${RELEASE_ROOT}" <<'PY'
import sys
from pathlib import Path

release_root = Path(sys.argv[1])
sys.path.insert(0, str(release_root / "wepo-blockchain" / "core"))
import network_profile

blockers = network_profile.mainnet_release_blockers(
    manifest_path=release_root / "MAINNET_PARAMETER_MANIFEST.json"
)
if blockers:
    print("mainnet release blockers: " + ",".join(blockers))
    raise SystemExit(1)
PY
    then
        fail "mainnet signer installation is locked until the frozen mainnet parameter gate clears"
    fi
fi

if [[ "${NETWORK_PROFILE}" == "mainnet" && "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "1" ]]; then
    command -v systemctl >/dev/null 2>&1 \
        || fail "systemctl is required for mainnet signer qualification"
    if systemctl is-active --quiet "${NODE_SERVICE_NAME}"; then
        fail "mainnet signer qualification requires the node service to remain inactive"
    fi
    log "QUALIFICATION ONLY: installing mainnet-domain signer while node service is inactive"
fi

ensure_group "${NODE_GROUP}"
ensure_group "${SIGNER_GROUP}"
ensure_locked_user "${NODE_USER}" "${NODE_GROUP}" /var/lib/wepo-node
ensure_locked_user "${SIGNER_USER}" "${SIGNER_GROUP}" "${SIGNER_HOME}"

install -d -m 0700 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" "${SIGNER_HOME}"
install -d -m 0700 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" "$(dirname "${KEY_FILE}")"
install -d -m 0700 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" "$(dirname "${STATE_DB}")"
install -d -m 0750 -o "${NODE_USER}" -g "${NODE_GROUP}" "${NODE_DATA_DIR}"
install -d -m 0755 -o root -g root "${WEPO_ETC_DIR}"

if [[ "${INITIALIZE_KEY}" == "1" ]]; then
    [[ ! -e "${KEY_FILE}" ]] || fail "refusing to overwrite existing validator key"
    init_output="$(runuser -u "${SIGNER_USER}" -- "${PYTHON_BIN}" "${SIGNER_SCRIPT}" \
        --network "${NETWORK_PROFILE}" --key-file "${KEY_FILE}" --init-key)"
    printf '%s\n' "${init_output}" >"${PUBLIC_PATH}.tmp"
    install -m 0640 -o root -g "${NODE_GROUP}" "${PUBLIC_PATH}.tmp" "${PUBLIC_PATH}"
    rm -f "${PUBLIC_PATH}.tmp"
else
    [[ -f "${KEY_FILE}" ]] || fail "validator key is missing; initialize it in a reviewed ceremony"
    [[ -f "${PUBLIC_PATH}" ]] || fail "public validator metadata is missing: ${PUBLIC_PATH}"
fi

chown "${SIGNER_USER}:${SIGNER_GROUP}" "${KEY_FILE}"
chmod 0600 "${KEY_FILE}"

COMMAND_JSON="$(render_command_json)"
{
    printf "WEPO_VALIDATOR_SIGNER_COMMAND_JSON='%s'\n" "${COMMAND_JSON}"
    printf 'WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS=15\n'
} >"${ENV_PATH}.tmp"
install -m 0640 -o root -g "${NODE_GROUP}" "${ENV_PATH}.tmp" "${ENV_PATH}"
rm -f "${ENV_PATH}.tmp"

cat >"${SUDOERS_PATH}.tmp" <<EOF
Defaults:${NODE_USER} env_reset,!set_home
${NODE_USER} ALL=(${SIGNER_USER}) NOPASSWD:NOEXEC: ${PYTHON_BIN} ${SIGNER_SCRIPT} --network ${NETWORK_PROFILE} --key-file ${KEY_FILE} --state-db ${STATE_DB} --stdio
EOF
chmod 0440 "${SUDOERS_PATH}.tmp"
visudo -cf "${SUDOERS_PATH}.tmp" >/dev/null || fail "generated sudoers rule is invalid"
install -m 0440 -o root -g root "${SUDOERS_PATH}.tmp" "${SUDOERS_PATH}"
rm -f "${SUDOERS_PATH}.tmp"

install -d -m 0755 -o root -g root "${DROPIN_DIR}"
cat >"${DROPIN_PATH}.tmp" <<EOF
[Service]
User=${NODE_USER}
Group=${NODE_GROUP}
NoNewPrivileges=false
EnvironmentFile=${ENV_PATH}
ReadWritePaths=${SIGNER_HOME}/state
EOF
install -m 0644 -o root -g root "${DROPIN_PATH}.tmp" "${DROPIN_PATH}"
rm -f "${DROPIN_PATH}.tmp"

log "PASS installed locked ${NETWORK_PROFILE} signer boundary"
log "node_user=${NODE_USER} signer_user=${SIGNER_USER}"
log "public_metadata=${PUBLIC_PATH}"
log "run verify-validator-signer-host.sh before enabling PoS"
