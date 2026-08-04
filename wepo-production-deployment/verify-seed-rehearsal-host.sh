#!/usr/bin/env bash
# Read-only local verifier for the isolated three-host seed rehearsal.
set -euo pipefail

ENV_PATH="${ENV_PATH:-/etc/wepo/seed-rehearsal.env}"
SERVICE_NAME="${SERVICE_NAME:-wepo-seed-rehearsal}"
API_URL="${API_URL:-http://127.0.0.1:8122/api/network/status}"
P2P_PORT="${P2P_PORT:-22567}"
MINIMUM_CONNECTED_PEERS="${MINIMUM_CONNECTED_PEERS:-2}"

fail() {
    printf '[wepo-seed-verify] FAIL %s\n' "$1" >&2
    exit 1
}

pass() {
    printf '[wepo-seed-verify] PASS %s\n' "$1"
}

[[ "${EUID}" -eq 0 ]] || fail "run as root to inspect service configuration"
[[ -f "${ENV_PATH}" ]] || fail "missing environment file: ${ENV_PATH}"

set -a
# shellcheck disable=SC1090
source "${ENV_PATH}"
set +a

[[ "${WEPO_NETWORK_PROFILE:-}" == "test" ]] || fail "rehearsal must use test profile"
[[ "${WEPO_REQUIRE_MAINNET_SEEDS:-}" == "0" ]] || fail "mainnet seed requirement must be 0"
[[ "${WEPO_DNS_SEEDS:-}" == "off" ]] || fail "DNS seeds must remain off for this rehearsal"
[[ "${WEPO_NODE_API_HOST:-}" == "127.0.0.1" ]] || fail "API host must remain loopback"
[[ "${WEPO_STATIC_PEERS:-}" != *"198.51.100."* ]] || fail "replace documentation peer addresses"

IFS=',' read -r -a peers <<<"${WEPO_STATIC_PEERS:-}"
[[ "${#peers[@]}" -ge 2 ]] || fail "at least two static peer endpoints are required"
for peer in "${peers[@]}"; do
    [[ "${peer}" == *:* ]] || fail "invalid static peer: ${peer}"
    [[ "${peer}" != 127.* ]] || fail "loopback cannot be a seed peer: ${peer}"
done
pass "isolated test-profile static-peer configuration"

systemctl is-enabled --quiet "${SERVICE_NAME}" || fail "service is not enabled"
systemctl is-active --quiet "${SERVICE_NAME}" || fail "service is not active"
pass "systemd service enabled and active"

ss -ltn | grep -Eq ":${P2P_PORT}[[:space:]]" || fail "P2P port ${P2P_PORT} is not listening"
pass "P2P listener present on ${P2P_PORT}"

status_json="$(curl --fail --silent --show-error --max-time 5 "${API_URL}")" || fail "local node API unavailable"
printf '%s' "${status_json}" | python3 -c '
import json
import sys

minimum = int(sys.argv[1])
payload = json.load(sys.stdin)
connections = payload.get("connections")
if not isinstance(connections, list) or len(connections) < minimum:
    raise SystemExit(1)
' "${MINIMUM_CONNECTED_PEERS}" || fail "node reports fewer than ${MINIMUM_CONNECTED_PEERS} peers"
pass "node reports at least ${MINIMUM_CONNECTED_PEERS} connected peers"

for peer in "${peers[@]}"; do
    host="${peer%:*}"
    port="${peer##*:}"
    timeout 5 bash -c "</dev/tcp/${host}/${port}" || fail "cannot establish TCP to ${peer}"
done
pass "outbound TCP reachability to configured peers"

printf '[wepo-seed-verify] VERIFIED local host only; retain independent external port evidence separately.\n'
