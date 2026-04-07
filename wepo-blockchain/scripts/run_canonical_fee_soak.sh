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
SUMMARY_JSON="${SOAK_LOG_DIR}/summary.json"
ITERATION_DATA="${SOAK_LOG_DIR}/iterations.tsv"
EVENT_DATA="${SOAK_LOG_DIR}/events.tsv"
SOAK_START_TS="$(date +%s)"

print_step() {
    printf '[wepo-soak] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

write_summary_json() {
    python3 - "${ITERATION_DATA}" "${EVENT_DATA}" "${SUMMARY_JSON}" <<'PY'
import csv
import json
import os
import sys
from pathlib import Path

iterations_path = Path(sys.argv[1])
events_path = Path(sys.argv[2])
summary_json_path = Path(sys.argv[3])

def load_tsv(path):
    if not path.exists():
        return []
    with path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader)

payload = {
    "total_runs": int(os.environ["TOTAL_RUNS"]),
    "passed_runs": int(os.environ["PASSED_RUNS"]),
    "failed_runs": int(os.environ["FAILED_RUNS"]),
    "backend_restarts": int(os.environ["BACKEND_RESTARTS"]),
    "node_restarts": int(os.environ["NODE_RESTARTS"]),
    "started_at": int(os.environ["SOAK_START_TS"]),
    "finished_at": int(os.environ["SOAK_END_TS"]),
    "duration_seconds": int(os.environ["SOAK_END_TS"]) - int(os.environ["SOAK_START_TS"]),
    "backend_base_url": os.environ["BACKEND_BASE_URL"],
    "node_base_url": os.environ["NODE_BASE_URL"],
    "node_log": os.environ["NODE_LOG"],
    "backend_log": os.environ["BACKEND_LOG"],
    "config": {
        "soak_iterations": int(os.environ["SOAK_ITERATIONS"]),
        "soak_pause_seconds": int(os.environ["SOAK_PAUSE_SECONDS"]),
        "max_failures": int(os.environ["MAX_FAILURES"]),
        "verify_idempotent_replay": os.environ["VERIFY_IDEMPOTENT_REPLAY"] == "true",
        "verify_concurrent_idempotency": os.environ["VERIFY_CONCURRENT_IDEMPOTENCY"] == "true",
        "expect_settlement_depletion": os.environ["EXPECT_SETTLEMENT_DEPLETION"] == "true",
        "backend_restart_iteration": int(os.environ["BACKEND_RESTART_ITERATION"]),
        "node_restart_iteration": int(os.environ["NODE_RESTART_ITERATION"]),
        "restart_settle_seconds": int(os.environ["RESTART_SETTLE_SECONDS"]),
    },
    "iterations": load_tsv(iterations_path),
    "events": load_tsv(events_path),
}

summary_json_path.write_text(json.dumps(payload, indent=2) + "\n")
PY
}

cleanup() {
    local exit_code=$?

    stop_backend
    stop_node
    export SOAK_END_TS
    SOAK_END_TS="$(date +%s)"

    {
        printf 'total_runs=%s\n' "${TOTAL_RUNS}"
        printf 'passed_runs=%s\n' "${PASSED_RUNS}"
        printf 'failed_runs=%s\n' "${FAILED_RUNS}"
        printf 'backend_restarts=%s\n' "${BACKEND_RESTARTS}"
        printf 'node_restarts=%s\n' "${NODE_RESTARTS}"
        printf 'node_log=%s\n' "${NODE_LOG}"
        printf 'backend_log=%s\n' "${BACKEND_LOG}"
    } >>"${SUMMARY_LOG}"

    export TOTAL_RUNS PASSED_RUNS FAILED_RUNS BACKEND_RESTARTS NODE_RESTARTS
    export SOAK_START_TS SOAK_END_TS BACKEND_BASE_URL NODE_BASE_URL NODE_LOG BACKEND_LOG
    export SOAK_ITERATIONS SOAK_PAUSE_SECONDS MAX_FAILURES
    export VERIFY_IDEMPOTENT_REPLAY VERIFY_CONCURRENT_IDEMPOTENCY EXPECT_SETTLEMENT_DEPLETION
    export BACKEND_RESTART_ITERATION NODE_RESTART_ITERATION RESTART_SETTLE_SECONDS
    write_summary_json

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
    printf 'event\tbackend_restart\t%s\t%s\n' "${iteration}" "$(date +%s)" >>"${EVENT_DATA}"
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
    printf 'event\tnode_restart\t%s\t%s\n' "${iteration}" "$(date +%s)" >>"${EVENT_DATA}"
    stop_node
    if (( RESTART_SETTLE_SECONDS > 0 )); then
        sleep "${RESTART_SETTLE_SECONDS}"
    fi
    start_node "restart"
}

extract_trade_field() {
    local log_path="$1"
    local field="$2"
    local line
    line="$(grep -m1 'Trade executed trade_id=' "${log_path}" || true)"
    if [[ -z "${line}" ]]; then
        return 0
    fi
    sed -n "s/.*${field}=\([^ ]*\).*/\1/p" <<<"${line}"
}

classify_failure() {
    local log_path="$1"
    local fail_line
    fail_line="$(grep '^\[wepo-smoke\] FAIL ' "${log_path}" | tail -n1 || true)"
    if [[ -z "${fail_line}" ]]; then
        printf 'unknown'
        return
    fi
    if grep -q 'HTTP 429' <<<"${fail_line}"; then
        printf 'rate_limited'
        return
    fi
    if grep -q 'HTTP 500' <<<"${fail_line}"; then
        printf 'backend_500'
        return
    fi
    if grep -q 'Insufficient balance' <<<"${fail_line}"; then
        printf 'settlement_wallet_depleted'
        return
    fi
    if grep -q 'Node is unreachable' <<<"${fail_line}"; then
        printf 'node_unreachable'
        return
    fi
    if grep -q 'Backend is unreachable' <<<"${fail_line}"; then
        printf 'backend_unreachable'
        return
    fi
    printf 'smoke_failure'
}

extract_failure_reason() {
    local log_path="$1"
    local fail_line
    fail_line="$(grep '^\[wepo-smoke\] FAIL ' "${log_path}" | tail -n1 || true)"
    if [[ -z "${fail_line}" ]]; then
        return 0
    fi
    printf '%s' "${fail_line#\[wepo-smoke\] FAIL }" | tr '\t' ' ' | tr '\n' ' '
}

run_iteration() {
    local iteration="$1"
    local iteration_log="${SOAK_LOG_DIR}/smoke-${iteration}.log"
    local iteration_started_at iteration_finished_at duration_seconds
    local status trade_id settlement_txid settlement_policy failure_classification failure_reason
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
    iteration_started_at="$(date +%s)"
    if python3 "${SMOKE_SCRIPT}" \
        "${smoke_args[@]}" \
        >"${iteration_log}" 2>&1; then
        iteration_finished_at="$(date +%s)"
        duration_seconds=$((iteration_finished_at - iteration_started_at))
        PASSED_RUNS=$((PASSED_RUNS + 1))
        status="pass"
        trade_id="$(extract_trade_field "${iteration_log}" 'trade_id')"
        settlement_txid="$(extract_trade_field "${iteration_log}" 'settlement_txid')"
        settlement_policy="$(extract_trade_field "${iteration_log}" 'settlement_policy')"
        failure_classification=""
        failure_reason=""
        print_step "PASS iteration ${iteration}; log=${iteration_log}"
        printf 'iteration=%s status=pass log=%s\n' "${iteration}" "${iteration_log}" >>"${SUMMARY_LOG}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "${iteration}" "${status}" "${duration_seconds}" "${trade_id}" "${settlement_txid}" \
            "${settlement_policy}" "${failure_classification}" "${failure_reason}" \
            "${iteration_started_at}" "${iteration_log}" >>"${ITERATION_DATA}"
        return 0
    fi

    iteration_finished_at="$(date +%s)"
    duration_seconds=$((iteration_finished_at - iteration_started_at))
    FAILED_RUNS=$((FAILED_RUNS + 1))
    status="fail"
    trade_id="$(extract_trade_field "${iteration_log}" 'trade_id')"
    settlement_txid="$(extract_trade_field "${iteration_log}" 'settlement_txid')"
    settlement_policy="$(extract_trade_field "${iteration_log}" 'settlement_policy')"
    failure_classification="$(classify_failure "${iteration_log}")"
    failure_reason="$(extract_failure_reason "${iteration_log}")"
    print_step "FAIL iteration ${iteration}; log=${iteration_log}"
    printf 'iteration=%s status=fail log=%s\n' "${iteration}" "${iteration_log}" >>"${SUMMARY_LOG}"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "${iteration}" "${status}" "${duration_seconds}" "${trade_id}" "${settlement_txid}" \
        "${settlement_policy}" "${failure_classification}" "${failure_reason}" \
        "${iteration_started_at}" "${iteration_log}" >>"${ITERATION_DATA}"
    return 1
}

print_step "Checking ports"
check_port_free "${NODE_API_PORT}"
check_port_free "${BACKEND_PORT}"

: >"${NODE_LOG}"
: >"${BACKEND_LOG}"
: >"${SUMMARY_LOG}"
printf 'iteration\tstatus\tduration_seconds\ttrade_id\tsettlement_txid\tsettlement_policy\tfailure_classification\tfailure_reason\tstarted_at\tlog_path\n' >"${ITERATION_DATA}"
printf 'kind\tevent\titeration\ttimestamp\n' >"${EVENT_DATA}"
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
