#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
NODE_SCRIPT="${PROJECT_ROOT}/wepo-blockchain/core/wepo_node.py"
SMOKE_SCRIPT="${PROJECT_ROOT}/canonical_fee_settlement_smoke.py"

NODE_HOST="${NODE_HOST:-127.0.0.1}"
NODE_API_PORT="${NODE_API_PORT:-8122}"
NODE_P2P_PORT="${NODE_P2P_PORT:-22568}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8011}"
NODE_DATA_DIR="${NODE_DATA_DIR:-/tmp/wepo-fee-smoke-fast}"
SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS:-wepo1208a6064a35231e174df1750f0d983d1}"
DIFFICULTY_OVERRIDE="${DIFFICULTY_OVERRIDE:-1}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-30}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-20}"
LOG_DIR="${LOG_DIR:-/tmp/wepo-canonical-fee-smoke-logs}"

NODE_BASE_URL="http://${NODE_HOST}:${NODE_API_PORT}"
BACKEND_BASE_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
BACKEND_ENV_PATH="${BACKEND_DIR}/.env"

NODE_PID=""
BACKEND_PID=""

mkdir -p "${LOG_DIR}"
NODE_LOG="${LOG_DIR}/node.log"
BACKEND_LOG="${LOG_DIR}/backend.log"

print_step() {
    printf '[wepo-launcher] %s\n' "$1"
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
        if curl -s "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    return 1
}

print_step "Checking ports"
check_port_free "${NODE_API_PORT}"
check_port_free "${BACKEND_PORT}"

print_step "Starting node at ${NODE_BASE_URL}"
python3 "${NODE_SCRIPT}" \
    --data-dir "${NODE_DATA_DIR}" \
    --p2p-port "${NODE_P2P_PORT}" \
    --api-port "${NODE_API_PORT}" \
    --miner-address "${SETTLEMENT_ADDRESS}" \
    --difficulty-override "${DIFFICULTY_OVERRIDE}" \
    --no-background-mining \
    >"${NODE_LOG}" 2>&1 &
NODE_PID=$!

if ! wait_for_http "${NODE_BASE_URL}/api/network/status" "${READY_TIMEOUT_SECONDS}"; then
    fail "Node did not become ready; see ${NODE_LOG}"
fi

print_step "Starting backend at ${BACKEND_BASE_URL}"
(
    cd "${BACKEND_DIR}"
    WEPO_NODE_API_URL="${NODE_BASE_URL}" \
    WEPO_CANONICAL_APPLICATION_FEES_ENABLED=true \
    WEPO_APP_FEE_SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS}" \
    python3 -m uvicorn server:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
) >"${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!

if ! wait_for_http "${BACKEND_BASE_URL}/api/" "${READY_TIMEOUT_SECONDS}"; then
    fail "Backend did not become ready; see ${BACKEND_LOG}"
fi

print_step "Running canonical fee smoke"
python3 "${SMOKE_SCRIPT}" \
    --backend-base-url "${BACKEND_BASE_URL}" \
    --node-base-url "${NODE_BASE_URL}" \
    --backend-env "${BACKEND_ENV_PATH}" \
    --settlement-address "${SETTLEMENT_ADDRESS}" \
    --mine-timeout "${SMOKE_TIMEOUT_SECONDS}"

print_step "PASS canonical fee smoke launcher completed successfully"
