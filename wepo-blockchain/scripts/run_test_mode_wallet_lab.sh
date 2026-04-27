#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
NODE_SCRIPT="${PROJECT_ROOT}/wepo-blockchain/core/wepo_node.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

NODE_HOST="${NODE_HOST:-127.0.0.1}"
NODE_API_PORT="${NODE_API_PORT:-18212}"
NODE_P2P_PORT="${NODE_P2P_PORT:-22669}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-18021}"
NODE_DATA_DIR="${NODE_DATA_DIR:-/tmp/wepo-test-wallet-lab}"
MONGO_URL="${MONGO_URL:-mongodb://127.0.0.1:27018}"
DB_NAME="${DB_NAME:-wepo_test_wallet_lab}"
SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS:-wepo1208a6064a35231e174df1750f0d983d1}"
DIFFICULTY_OVERRIDE="${DIFFICULTY_OVERRIDE:-1}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-45}"
FUNDING_WAIT_SECONDS="${FUNDING_WAIT_SECONDS:-20}"
TARGET_FUNDING_WEPO="${TARGET_FUNDING_WEPO:-1.0}"
LOG_DIR="${LOG_DIR:-/tmp/wepo-test-wallet-lab-logs}"
RESET_LAB_STATE="${RESET_LAB_STATE:-0}"

NODE_PID=""
BACKEND_PID=""

print_step() {
    printf '[wepo-test-lab] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

cleanup() {
    local exit_code=$?
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill "${BACKEND_PID}" 2>/dev/null || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    if [[ -n "${NODE_PID}" ]] && kill -0 "${NODE_PID}" 2>/dev/null; then
        kill "${NODE_PID}" 2>/dev/null || true
        wait "${NODE_PID}" 2>/dev/null || true
    fi
    if [[ ${exit_code} -eq 0 ]]; then
        print_step "Teardown complete"
    else
        print_step "Teardown complete after failure; inspect ${LOG_DIR}"
    fi
}

trap cleanup EXIT INT TERM

check_port_free() {
    local port="$1"
    if ss -ltn | awk '{print $4}' | grep -Eq "[:.]${port}$"; then
        fail "Port ${port} is already in use"
    fi
}

wait_for_http() {
    local url="$1"
    local timeout="$2"
    local deadline=$((SECONDS + timeout))
    while (( SECONDS < deadline )); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_funding() {
    local deadline=$((SECONDS + FUNDING_WAIT_SECONDS))
    while (( SECONDS < deadline )); do
        local balance
        balance="$(curl -fsS "${NODE_BASE_URL}/api/wallet/${SETTLEMENT_ADDRESS}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("balance", 0))' 2>/dev/null || printf '0')"
        if python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) >= float(sys.argv[2]) else 1)" "${balance}" "${TARGET_FUNDING_WEPO}"; then
            print_step "Settlement wallet funded balance=${balance} WEPO"
            return 0
        fi
        sleep 1
    done
    fail "Settlement wallet ${SETTLEMENT_ADDRESS} did not reach ${TARGET_FUNDING_WEPO} WEPO in time"
}

print_schedule() {
    PYTHONPATH="${PROJECT_ROOT}/wepo-blockchain/core" python3 - <<'PY'
from network_profile import get_network_profile
profile = get_network_profile("test")
print(f"[wepo-test-lab] test profile: pre_pos_end={profile.pre_pos_duration_blocks} pos_first_active={profile.pos_activation_height + 1} phase_2a_end={profile.phase_2a_end_height} phase_2b_end={profile.phase_2b_end_height} phase_2c_end={profile.phase_2c_end_height} phase_2d_end={profile.phase_2d_end_height}")
print(f"[wepo-test-lab] test collateral: masternode_initial={profile.masternode_collateral_initial // 100000000} pos_initial={profile.pos_collateral_initial // 100000000}")
PY
}

mkdir -p "${LOG_DIR}"
NODE_LOG="${LOG_DIR}/node.log"
BACKEND_LOG="${LOG_DIR}/backend.log"
NODE_BASE_URL="http://${NODE_HOST}:${NODE_API_PORT}"
BACKEND_BASE_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

if [[ "${RESET_LAB_STATE}" == "1" ]]; then
    print_step "Resetting disposable test-lab state"
    rm -rf "${NODE_DATA_DIR}" "${LOG_DIR}"
fi

mkdir -p "${LOG_DIR}"

check_port_free "${NODE_API_PORT}"
check_port_free "${BACKEND_PORT}"
print_schedule

print_step "Starting test-mode node at ${NODE_BASE_URL}"
WEPO_NETWORK_PROFILE=test \
"${PYTHON_BIN}" "${NODE_SCRIPT}" \
    --network-profile test \
    --data-dir "${NODE_DATA_DIR}" \
    --p2p-port "${NODE_P2P_PORT}" \
    --api-port "${NODE_API_PORT}" \
    --miner-address "${SETTLEMENT_ADDRESS}" \
    --difficulty-override "${DIFFICULTY_OVERRIDE}" \
    >"${NODE_LOG}" 2>&1 &
NODE_PID=$!

if ! wait_for_http "${NODE_BASE_URL}/api/network/status" "${READY_TIMEOUT_SECONDS}"; then
    fail "Test-mode node did not become ready; see ${NODE_LOG}"
fi

wait_for_funding

print_step "Starting test-mode backend at ${BACKEND_BASE_URL}"
(
    cd "${BACKEND_DIR}"
    MONGO_URL="${MONGO_URL}" \
    DB_NAME="${DB_NAME}" \
    WEPO_NETWORK_PROFILE=test \
    WEPO_NODE_API_URL="${NODE_BASE_URL}" \
    WEPO_CANONICAL_APPLICATION_FEES_ENABLED=true \
    WEPO_APP_FEE_SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS}" \
    "${PYTHON_BIN}" -m uvicorn server:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
) >"${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!

if ! wait_for_http "${BACKEND_BASE_URL}/api/" "${READY_TIMEOUT_SECONDS}"; then
    fail "Test-mode backend did not become ready; see ${BACKEND_LOG}"
fi

print_step "PASS test wallet lab is ready"
print_step "node=${NODE_BASE_URL}"
print_step "backend=${BACKEND_BASE_URL}"
print_step "mongo=${MONGO_URL} db=${DB_NAME}"
print_step "logs=${LOG_DIR}"
print_step "Press Ctrl+C when finished"
wait
