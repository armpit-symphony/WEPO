#!/usr/bin/env bash
set -euo pipefail

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

RELEASE_ROOT="$(readlink -f "${RELEASE_ROOT}")"
PYTHON_BIN="$(readlink -f "${PYTHON_BIN}")"
SIGNER_SCRIPT="${RELEASE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py"
ENV_PATH="${WEPO_ETC_DIR}/validator-signer.env"
SIGNER_POLICY="${RELEASE_ROOT}/wepo-blockchain/signer/stake_transaction_policy.py"
PUBLIC_PATH="${WEPO_ETC_DIR}/validator-signer-public.json"
DROPIN_PATH="/etc/systemd/system/${NODE_SERVICE_NAME}.service.d/validator-signer.conf"

log() {
    printf '[wepo-signer-verify] %s\n' "$1"
}

fail() {
    log "FAIL $1"
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || fail "run as root"
}

assert_owner_mode() {
    local path="$1"
    local owner="$2"
    local group="$3"
    local mode="$4"
    [[ -e "${path}" && ! -L "${path}" ]] || fail "missing or symlinked path: ${path}"
    [[ "$(stat -c '%U:%G' "${path}")" == "${owner}:${group}" ]] \
        || fail "wrong owner for ${path}"
    [[ "$(stat -c '%a' "${path}")" == "${mode}" ]] || fail "wrong mode for ${path}"
}

require_root
[[ "${NETWORK_PROFILE}" == "test" || "${NETWORK_PROFILE}" == "mainnet" ]] \
    || fail "only the supported test or release-gated mainnet signer profile may be verified"
[[ "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "0" || "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "1" ]] \
    || fail "MAINNET_SIGNER_QUALIFICATION_ONLY must be 0 or 1"
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
        fail "mainnet signer verification is locked until the frozen mainnet parameter gate clears"
    fi
fi
if [[ "${NETWORK_PROFILE}" == "mainnet" && "${MAINNET_SIGNER_QUALIFICATION_ONLY}" == "1" ]]; then
    command -v systemctl >/dev/null 2>&1 \
        || fail "systemctl is required for mainnet signer qualification"
    if systemctl is-active --quiet "${NODE_SERVICE_NAME}"; then
        fail "mainnet signer qualification requires the node service to remain inactive"
    fi
    log "QUALIFICATION ONLY: verifying mainnet-domain signer while node service is inactive"
fi

[[ "${NODE_USER}" != "${SIGNER_USER}" ]] || fail "node and signer users are not distinct"
id "${NODE_USER}" >/dev/null 2>&1 || fail "node user is missing"
id "${SIGNER_USER}" >/dev/null 2>&1 || fail "signer user is missing"

assert_owner_mode "$(dirname "${KEY_FILE}")" "${SIGNER_USER}" "${SIGNER_GROUP}" 700
assert_owner_mode "${NODE_DATA_DIR}" "${NODE_USER}" "${NODE_GROUP}" 750
assert_owner_mode "$(dirname "${STATE_DB}")" "${SIGNER_USER}" "${SIGNER_GROUP}" 700
assert_owner_mode "${KEY_FILE}" "${SIGNER_USER}" "${SIGNER_GROUP}" 600
assert_owner_mode "${ENV_PATH}" root "${NODE_GROUP}" 640
assert_owner_mode "${PUBLIC_PATH}" root "${NODE_GROUP}" 640
assert_owner_mode "${SUDOERS_PATH}" root root 440
assert_owner_mode "${DROPIN_PATH}" root root 644

for immutable in \
    "${PYTHON_BIN}" \
    "${SIGNER_SCRIPT}" \
    "${RELEASE_ROOT}/wepo-blockchain/core/address_utils.py" \
    "${SIGNER_POLICY}" \
    "${RELEASE_ROOT}/wepo-blockchain/core/dilithium.py"; do
    [[ -f "${immutable}" && ! -L "${immutable}" ]] || fail "immutable runtime path is invalid: ${immutable}"
    [[ "$(stat -c '%u' "${immutable}")" == "0" ]] || fail "runtime is not root-owned: ${immutable}"
    mode="$(stat -c '%a' "${immutable}")"
    (( (8#${mode} & 8#022) == 0 )) || fail "runtime is group/other writable: ${immutable}"
done

runuser -u "${NODE_USER}" -- test ! -r "${KEY_FILE}" \
    || fail "node user can read validator private key"
runuser -u "${NODE_USER}" -- test ! -w "${KEY_FILE}" \
    || fail "node user can write validator private key"
runuser -u "${NODE_USER}" -- test ! -x "$(dirname "${KEY_FILE}")" \
    || fail "node user can traverse validator key directory"
runuser -u "${NODE_USER}" -- test ! -w "${SIGNER_SCRIPT}" \
    || fail "node user can modify signer code"
runuser -u "${NODE_USER}" -- test ! -w "$(dirname "${STATE_DB}")" \
    || fail "node user can modify signer state directory"

visudo -cf "${SUDOERS_PATH}" >/dev/null || fail "sudoers fragment is invalid"
grep -F -- '--allow-insecure-permissions-for-test' "${SUDOERS_PATH}" "${ENV_PATH}" >/dev/null 2>&1 \
    && fail "test-only permission bypass is present in deployment configuration"

PUBLIC_REQUEST="$("${PYTHON_BIN}" - "${PUBLIC_PATH}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    public = json.load(source)
print(json.dumps({
    "version": 3,
    "operation": "public_key",
    "validator_address": public["validator_address"],
}, separators=(",", ":")))
PY
)"

printf '%s\n' "${PUBLIC_REQUEST}" | runuser -u "${NODE_USER}" -- \
    sudo -n -u "${SIGNER_USER}" -- "${PYTHON_BIN}" "${SIGNER_SCRIPT}" \
    --network "${NETWORK_PROFILE}" --key-file "${KEY_FILE}" \
    --state-db "${STATE_DB}" --stdio >"${PUBLIC_PATH}.verify.tmp"
"${PYTHON_BIN}" - "${PUBLIC_PATH}" "${PUBLIC_PATH}.verify.tmp" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    expected = json.load(source)
with open(sys.argv[2], encoding="utf-8") as source:
    response = json.load(source)
assert response == {
    "version": 3,
    "ok": True,
    "public_key": expected["public_key"],
}
PY
rm -f "${PUBLIC_PATH}.verify.tmp"

if runuser -u "${NODE_USER}" -- sudo -n -u "${SIGNER_USER}" -- /bin/true >/dev/null 2>&1; then
    fail "node user can execute an unapproved command as signer"
fi
if printf '%s\n' "${PUBLIC_REQUEST}" | runuser -u "${NODE_USER}" -- \
    sudo -n -u "${SIGNER_USER}" -- "${PYTHON_BIN}" "${SIGNER_SCRIPT}" \
    --network "${NETWORK_PROFILE}" --key-file "${KEY_FILE}" \
    --state-db "${STATE_DB}" --stdio --allow-insecure-permissions-for-test >/dev/null 2>&1; then
    fail "node user can append unapproved signer arguments"
fi

grep -Fx "NoNewPrivileges=false" "${DROPIN_PATH}" >/dev/null \
    || fail "systemd drop-in does not permit the exact sudo transition"
grep -Fx "ReadWritePaths=${SIGNER_HOME}/state" "${DROPIN_PATH}" >/dev/null \
    || fail "systemd namespace does not expose signer state to the child signer"

assert_owner_mode "${STATE_DB}" "${SIGNER_USER}" "${SIGNER_GROUP}" 600
quick_check="$(runuser -u "${SIGNER_USER}" -- "${PYTHON_BIN}" - "${STATE_DB}" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    print(connection.execute("PRAGMA quick_check").fetchone()[0])
finally:
    connection.close()
PY
)"
[[ "${quick_check}" == "ok" ]] || fail "anti-equivocation database quick_check failed"

log "PASS separate-user signer boundary verified"
