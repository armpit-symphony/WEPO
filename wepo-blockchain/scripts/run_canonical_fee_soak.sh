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
DEPLETED_SETTLEMENT_ADDRESS="${DEPLETED_SETTLEMENT_ADDRESS:-wepo1deadbeefdeadbeefdeadbeefdeadbeefdeadbe}"
DIFFICULTY_OVERRIDE="${DIFFICULTY_OVERRIDE:-1}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-30}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-20}"
SOAK_ITERATIONS="${SOAK_ITERATIONS:-10}"
SOAK_PAUSE_SECONDS="${SOAK_PAUSE_SECONDS:-1}"
MAX_FAILURES="${MAX_FAILURES:-1}"
SOAK_LOG_DIR="${SOAK_LOG_DIR:-/tmp/wepo-canonical-fee-soak-logs}"
VERIFY_IDEMPOTENT_REPLAY="${VERIFY_IDEMPOTENT_REPLAY:-false}"
VERIFY_CONCURRENT_IDEMPOTENCY="${VERIFY_CONCURRENT_IDEMPOTENCY:-false}"
EXPECT_SETTLEMENT_DEPLETION="${EXPECT_SETTLEMENT_DEPLETION:-false}"
BACKEND_RESTART_ITERATION="${BACKEND_RESTART_ITERATION:-0}"
NODE_RESTART_ITERATION="${NODE_RESTART_ITERATION:-0}"
RESTART_SETTLE_SECONDS="${RESTART_SETTLE_SECONDS:-1}"

if [[ "${EXPECT_SETTLEMENT_DEPLETION}" == "true" ]]; then
    SETTLEMENT_ADDRESS="${DEPLETED_SETTLEMENT_ADDRESS}"
fi

NODE_BASE_URL="http://${NODE_HOST}:${NODE_API_PORT}"
BACKEND_BASE_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
BACKEND_ENV_PATH="${BACKEND_DIR}/.env"

NODE_PID=""
BACKEND_PID=""
TOTAL_RUNS=0
PASSED_RUNS=0
FAILED_RUNS=0
BACKEND_RESTARTS=0
NODE_RESTARTS=0

mkdir -p "${SOAK_LOG_DIR}"
NODE_LOG="${SOAK_LOG_DIR}/node.log"
BACKEND_LOG="${SOAK_LOG_DIR}/backend.log"
SUMMARY_LOG="${SOAK_LOG_DIR}/summary.log"

print_step() {
    printf '[wepo-soak] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

cleanup() {
    local exit_code=$?

    stop_backend
    stop_node

    {
        printf 'total_runs=%s\n' "${TOTAL_RUNS}"
        printf 'passed_runs=%s\n' "${PASSED_RUNS}"
        printf 'failed_runs=%s\n' "${FAILED_RUNS}"
        printf 'backend_restarts=%s\n' "${BACKEND_RESTARTS}"
        printf 'node_restarts=%s\n' "${NODE_RESTARTS}"
        printf 'node_log=%s\n' "${NODE_LOG}"
        printf 'backend_log=%s\n' "${BACKEND_LOG}"
    } >>"${SUMMARY_LOG}"

    if [[ ${exit_code} -eq 0 ]]; then
        print_step "Teardown complete"
    else
        print_step "Teardown complete after failure; inspect ${SOAK_LOG_DIR}"
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

stop_backend() {
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill "${BACKEND_PID}" 2>/dev/null || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    BACKEND_PID=""
}

stop_node() {
    if [[ -n "${NODE_PID}" ]] && kill -0 "${NODE_PID}" 2>/dev/null; then
        kill "${NODE_PID}" 2>/dev/null || true
        wait "${NODE_PID}" 2>/dev/null || true
    fi
    NODE_PID=""
}

start_node() {
    local mode="${1:-start}"
    print_step "${mode^}ing node at ${NODE_BASE_URL}"
    python3 "${NODE_SCRIPT}" \
        --data-dir "${NODE_DATA_DIR}" \
        --p2p-port "${NODE_P2P_PORT}" \
        --api-port "${NODE_API_PORT}" \
        --miner-address "${SETTLEMENT_ADDRESS}" \
        --difficulty-override "${DIFFICULTY_OVERRIDE}" \
        --no-background-mining \
        >>"${NODE_LOG}" 2>&1 &
    NODE_PID=$!

    if ! wait_for_http "${NODE_BASE_URL}/api/network/status" "${READY_TIMEOUT_SECONDS}"; then
        fail "Node did not become ready; see ${NODE_LOG}"
    fi
}

start_backend() {
    local mode="${1:-start}"
    print_step "${mode^}ing backend at ${BACKEND_BASE_URL}"
    (
        cd "${BACKEND_DIR}"
        WEPO_NODE_API_URL="${NODE_BASE_URL}" \
        WEPO_CANONICAL_APPLICATION_FEES_ENABLED=true \
        WEPO_APP_FEE_SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS}" \
        python3 -m uvicorn server:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
    ) >>"${BACKEND_LOG}" 2>&1 &
    BACKEND_PID=$!

    if ! wait_for_http "${BACKEND_BASE_URL}/api/" "${READY_TIMEOUT_SECONDS}"; then
        fail "Backend did not become ready; see ${BACKEND_LOG}"
    fi
}

restart_backend() {
    local iteration="$1"
    BACKEND_RESTARTS=$((BACKEND_RESTARTS + 1))
    print_step "Restarting backend after iteration ${iteration}"
    printf 'event=backend_restart iteration=%s\n' "${iteration}" >>"${SUMMARY_LOG}"
    stop_backend
    if (( RESTART_SETTLE_SECONDS > 0 )); then
        sleep "${RESTART_SETTLE_SECONDS}"
    fi
    start_backend "restart"
}

restart_node() {
    local iteration="$1"
    NODE_RESTARTS=$((NODE_RESTARTS + 1))
    print_step "Restarting node after iteration ${iteration}"
    printf 'event=node_restart iteration=%s\n' "${iteration}" >>"${SUMMARY_LOG}"
    stop_node
    if (( RESTART_SETTLE_SECONDS > 0 )); then
        sleep "${RESTART_SETTLE_SECONDS}"
    fi
    start_node "restart"
}

run_iteration() {
    local iteration="$1"
    local iteration_log="${SOAK_LOG_DIR}/smoke-${iteration}.log"
    local -a smoke_args=(
        --backend-base-url "${BACKEND_BASE_URL}"
        --node-base-url "${NODE_BASE_URL}"
        --backend-env "${BACKEND_ENV_PATH}"
        --settlement-address "${SETTLEMENT_ADDRESS}"
        --mine-timeout "${SMOKE_TIMEOUT_SECONDS}"
    )

    if [[ "${VERIFY_IDEMPOTENT_REPLAY}" == "true" ]]; then
        smoke_args+=(--verify-idempotent-replay)
    fi

    if [[ "${VERIFY_CONCURRENT_IDEMPOTENCY}" == "true" ]]; then
        smoke_args+=(--verify-concurrent-idempotency)
    fi

    if [[ "${EXPECT_SETTLEMENT_DEPLETION}" == "true" ]]; then
        smoke_args+=(--expect-settlement-depletion)
    fi

    print_step "Starting iteration ${iteration}/${SOAK_ITERATIONS}"
    if python3 "${SMOKE_SCRIPT}" \
        "${smoke_args[@]}" \
        >"${iteration_log}" 2>&1; then
        PASSED_RUNS=$((PASSED_RUNS + 1))
        print_step "PASS iteration ${iteration}; log=${iteration_log}"
        printf 'iteration=%s status=pass log=%s\n' "${iteration}" "${iteration_log}" >>"${SUMMARY_LOG}"
        return 0
    fi

    FAILED_RUNS=$((FAILED_RUNS + 1))
    print_step "FAIL iteration ${iteration}; log=${iteration_log}"
    printf 'iteration=%s status=fail log=%s\n' "${iteration}" "${iteration_log}" >>"${SUMMARY_LOG}"
    return 1
}

print_step "Checking ports"
check_port_free "${NODE_API_PORT}"
check_port_free "${BACKEND_PORT}"

: >"${NODE_LOG}"
: >"${BACKEND_LOG}"
: >"${SUMMARY_LOG}"
start_node "start"
start_backend "start"
print_step "Beginning soak: iterations=${SOAK_ITERATIONS} max_failures=${MAX_FAILURES} pause=${SOAK_PAUSE_SECONDS}s"

for (( iteration=1; iteration<=SOAK_ITERATIONS; iteration++ )); do
    TOTAL_RUNS=$((TOTAL_RUNS + 1))

    if ! run_iteration "${iteration}" && (( FAILED_RUNS >= MAX_FAILURES )); then
        fail "Reached max failures (${MAX_FAILURES}) during soak"
    fi

    if (( iteration == BACKEND_RESTART_ITERATION )) && (( iteration < SOAK_ITERATIONS )); then
        restart_backend "${iteration}"
    fi

    if (( iteration == NODE_RESTART_ITERATION )) && (( iteration < SOAK_ITERATIONS )); then
        restart_node "${iteration}"
    fi

    if (( iteration < SOAK_ITERATIONS )) && (( SOAK_PAUSE_SECONDS > 0 )); then
        sleep "${SOAK_PAUSE_SECONDS}"
    fi
done

print_step "PASS soak completed: total=${TOTAL_RUNS} passed=${PASSED_RUNS} failed=${FAILED_RUNS}"
