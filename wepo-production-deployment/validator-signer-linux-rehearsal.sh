#!/usr/bin/env bash
set -euo pipefail

umask 077

SOURCE_ROOT="${SOURCE_ROOT:-/workspace}"
RELEASE_ROOT=/opt/wepo-rehearsal
RAW_EVIDENCE="${RAW_EVIDENCE:-/evidence/raw-evidence.json}"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3.11}"
NETWORK_PROFILE=test
NODE_USER=wepo-node
NODE_GROUP=wepo-node
SIGNER_USER=wepo-signer
SIGNER_GROUP=wepo-signer
SIGNER_HOME=/var/lib/wepo-signer
KEY_FILE=${SIGNER_HOME}/private/validator-key.json
STATE_DB=${SIGNER_HOME}/state/anti-equivocation.sqlite3
PUBLIC_PATH=/etc/wepo/validator-signer-public.json
ENV_PATH=/etc/wepo/validator-signer.env
WORK_DIR=/var/lib/wepo-signer-rehearsal
BACKUP_DIR=${SIGNER_HOME}/rehearsal-backup

log() {
    printf '[wepo-signer-rehearsal] %s\n' "$1" >&2
}

fail() {
    log "FAIL $1"
    exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "container rehearsal must run as root"
[[ ! -e "${RAW_EVIDENCE}" ]] || fail "raw evidence path already exists"
install -d -m 0700 -o root -g root "$(dirname "${RAW_EVIDENCE}")" "${WORK_DIR}"
install -d -m 0555 -o root -g root \
    "${RELEASE_ROOT}" \
    "${RELEASE_ROOT}/wepo-blockchain" \
    "${RELEASE_ROOT}/wepo-blockchain/core" \
    "${RELEASE_ROOT}/wepo-blockchain/signer"
install -m 0555 -o root -g root \
    "${SOURCE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py" \
    "${RELEASE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py"
for module in address_utils.py dilithium.py; do
install -m 0444 -o root -g root \
    "${SOURCE_ROOT}/wepo-blockchain/signer/stake_transaction_policy.py" \
    "${RELEASE_ROOT}/wepo-blockchain/signer/stake_transaction_policy.py"
    install -m 0444 -o root -g root "${SOURCE_ROOT}/wepo-blockchain/core/${module}" \
        "${RELEASE_ROOT}/wepo-blockchain/core/${module}"
done

log "proving unsupported and mainnet profiles are refused before installation"
set +e
NETWORK_PROFILE=mainnet RELEASE_ROOT="${RELEASE_ROOT}" PYTHON_BIN="${PYTHON_BIN}" \
    /usr/local/libexec/wepo/install-validator-signer.sh \
    >"${WORK_DIR}/mainnet-install.stdout" 2>"${WORK_DIR}/mainnet-install.stderr"
MAINNET_INSTALL_RC=$?
NETWORK_PROFILE=staging RELEASE_ROOT="${RELEASE_ROOT}" PYTHON_BIN="${PYTHON_BIN}" \
    /usr/local/libexec/wepo/install-validator-signer.sh \
    >"${WORK_DIR}/staging-install.stdout" 2>"${WORK_DIR}/staging-install.stderr"
STAGING_INSTALL_RC=$?
set -e
[[ "${MAINNET_INSTALL_RC}" -ne 0 ]] || fail "mainnet signer installation was accepted"
[[ "${STAGING_INSTALL_RC}" -ne 0 ]] || fail "unsupported staging profile was accepted"
grep -F 'mainnet signer installation is locked' "${WORK_DIR}/mainnet-install.stdout" >/dev/null \
    || fail "mainnet install refusal reason is missing"
grep -F 'only the supported test profile' "${WORK_DIR}/staging-install.stdout" >/dev/null \
    || fail "unsupported profile refusal reason is missing"
if id "${NODE_USER}" >/dev/null 2>&1 || id "${SIGNER_USER}" >/dev/null 2>&1; then
    fail "refused profile installation mutated service accounts"
fi

log "installing separate-user signer boundary"
NODE_USER="${NODE_USER}" NODE_GROUP="${NODE_GROUP}" \
SIGNER_USER="${SIGNER_USER}" SIGNER_GROUP="${SIGNER_GROUP}" \
NETWORK_PROFILE="${NETWORK_PROFILE}" RELEASE_ROOT="${RELEASE_ROOT}" \
PYTHON_BIN="${PYTHON_BIN}" INITIALIZE_KEY=1 \
    /usr/local/libexec/wepo/install-validator-signer.sh

log "verifying filesystem and sudo boundary"
NODE_USER="${NODE_USER}" NODE_GROUP="${NODE_GROUP}" \
SIGNER_USER="${SIGNER_USER}" SIGNER_GROUP="${SIGNER_GROUP}" \
NETWORK_PROFILE="${NETWORK_PROFILE}" RELEASE_ROOT="${RELEASE_ROOT}" \
PYTHON_BIN="${PYTHON_BIN}" \
    /usr/local/libexec/wepo/verify-validator-signer-host.sh

COMMAND_JSON="$("${PYTHON_BIN}" - "${ENV_PATH}" <<'PY'
import shlex
import sys

value = None
with open(sys.argv[1], encoding="utf-8") as source:
    for raw in source:
        if raw.startswith("WEPO_VALIDATOR_SIGNER_COMMAND_JSON="):
            value = shlex.split(raw.strip(), posix=True)[0].split("=", 1)[1]
            break
if value is None:
    raise SystemExit("missing signer command")
print(value)
PY
)"

run_client() {
    local height="$1"
    local output_path="$2"
    runuser -u "${NODE_USER}" -- "${PYTHON_BIN}" \
        /usr/local/libexec/wepo/validator_signer_rehearsal_client.py \
        --command-json "${COMMAND_JSON}" \
        --public-metadata "${PUBLIC_PATH}" \
        --network "${NETWORK_PROFILE}" \
        --height "${height}" \
        --core-dir "${RELEASE_ROOT}/wepo-blockchain/core" >"${output_path}"
}

log "signing height 17 with restart/idempotence/conflict checks"
run_client 17 "${WORK_DIR}/height-17.json"

log "creating a consistent local backup of the signer safety unit"
install -d -m 0700 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" "${BACKUP_DIR}"
runuser -u "${SIGNER_USER}" -- "${PYTHON_BIN}" - "${STATE_DB}" \
    "${BACKUP_DIR}/anti-equivocation.sqlite3" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
install -m 0600 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" \
    "${KEY_FILE}" "${BACKUP_DIR}/validator-key.json"

log "proving corrupt anti-equivocation state fails closed"
install -m 0600 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" \
    "${BACKUP_DIR}/anti-equivocation.sqlite3" "${STATE_DB}.good"
rm -f "${STATE_DB}-wal" "${STATE_DB}-shm"
runuser -u "${SIGNER_USER}" -- "${PYTHON_BIN}" - "${STATE_DB}" <<'PY'
import sys

with open(sys.argv[1], "wb") as output:
    output.write(b"deliberately-corrupt-rehearsal-state")
PY

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
set +e
printf '%s\n' "${PUBLIC_REQUEST}" | runuser -u "${NODE_USER}" -- \
    sudo -n -u "${SIGNER_USER}" -- "${PYTHON_BIN}" \
    "${RELEASE_ROOT}/wepo-blockchain/signer/wepo_validator_signer.py" \
    --network "${NETWORK_PROFILE}" --key-file "${KEY_FILE}" \
    --state-db "${STATE_DB}" --stdio >"${WORK_DIR}/corrupt.stdout" 2>"${WORK_DIR}/corrupt.stderr"
CORRUPT_RC=$?
set -e
[[ "${CORRUPT_RC}" -ne 0 ]] || fail "corrupt signer state was accepted"
grep -F 'failed closed' "${WORK_DIR}/corrupt.stderr" >/dev/null \
    || fail "corrupt signer state failed for an unexpected reason"

log "restoring the complete safety unit and continuing above retained height"
install -m 0600 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" \
    "${BACKUP_DIR}/validator-key.json" "${KEY_FILE}"
install -m 0600 -o "${SIGNER_USER}" -g "${SIGNER_GROUP}" \
    "${BACKUP_DIR}/anti-equivocation.sqlite3" "${STATE_DB}"
rm -f "${STATE_DB}-wal" "${STATE_DB}-shm" "${STATE_DB}.good"
run_client 18 "${WORK_DIR}/height-18.json"

NODE_USER="${NODE_USER}" NODE_GROUP="${NODE_GROUP}" \
SIGNER_USER="${SIGNER_USER}" SIGNER_GROUP="${SIGNER_GROUP}" \
NETWORK_PROFILE="${NETWORK_PROFILE}" RELEASE_ROOT="${RELEASE_ROOT}" \
PYTHON_BIN="${PYTHON_BIN}" \
    /usr/local/libexec/wepo/verify-validator-signer-host.sh

log "publishing sanitized raw evidence"
"${PYTHON_BIN}" - "${RAW_EVIDENCE}" "${WORK_DIR}" "${STATE_DB}" \
    "${RELEASE_ROOT}" "${CORRUPT_RC}" <<'PY'
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

output = Path(sys.argv[1])
work = Path(sys.argv[2])
state_db = Path(sys.argv[3])
release = Path(sys.argv[4])
corrupt_rc = int(sys.argv[5])

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

with (work / "height-17.json").open(encoding="utf-8") as source:
    height_17 = json.load(source)
with (work / "height-18.json").open(encoding="utf-8") as source:
    height_18 = json.load(source)
connection = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
try:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    signed_heights = [row[0] for row in connection.execute(
        "SELECT height FROM signed_blocks ORDER BY height"
    )]
finally:
    connection.close()

document = {
    "format": "wepo-validator-signer-linux-rehearsal-v1",
    "status": "pass",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "network_profile": "test",
    "mainnet_mutated": False,
    "accounts": {
        "node": "wepo-node",
        "signer": "wepo-signer",
        "distinct": True,
        "locked_shells": True,
    },
    "boundary": {
        "node_cannot_read_key": True,
        "node_cannot_write_key_or_state": True,
        "runtime_root_owned_immutable": True,
        "exact_sudo_command_only": True,
        "unapproved_command_refused": True,
        "unapproved_arguments_refused": True,
        "test_permission_bypass_absent": True,
        "systemd_sudo_transition_explicit": True,
        "mainnet_install_refused_before_mutation": True,
        "unsupported_profile_refused_before_mutation": True,
    },
    "signing": {
        "runs": [height_17, height_18],
        "signed_heights": signed_heights,
        "anti_equivocation_quick_check": quick_check,
        "process_restart_between_requests": True,
    },
    "recovery": {
        "consistent_key_and_state_backup_created": True,
        "corrupt_state_failed_closed": True,
        "corrupt_state_returncode": corrupt_rc,
        "complete_safety_unit_restored": True,
        "continued_above_restored_height": signed_heights == [17, 18],
        "host_fencing_not_exercised": True,
        "off_host_encrypted_backup_not_exercised": True,
    },
    "artifacts": {
        "signer_script_sha256": sha256(release / "wepo-blockchain/signer/wepo_validator_signer.py"),
        "stake_policy_sha256": sha256(release / "wepo-blockchain/signer/stake_transaction_policy.py"),
        "dilithium_module_sha256": sha256(release / "wepo-blockchain/core/dilithium.py"),
        "installer_sha256": sha256(Path("/usr/local/libexec/wepo/install-validator-signer.sh")),
        "verifier_sha256": sha256(Path("/usr/local/libexec/wepo/verify-validator-signer-host.sh")),
        "client_sha256": sha256(Path("/usr/local/libexec/wepo/validator_signer_rehearsal_client.py")),
        "private_key_in_evidence": False,
        "private_key_retained_outside_ephemeral_container": False,
    },
}
serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
if len(serialized) > 128 * 1024 or any(key in serialized for key in ('"private_key":', '"private_key_hex":')):
    raise SystemExit("evidence secret-safety check failed")
descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as destination:
    destination.write(serialized)
PY

log "PASS Linux separate-user validator-signer rehearsal"
