#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_SMOKE_LAUNCHER="${PROJECT_ROOT}/wepo-blockchain/scripts/run_canonical_fee_smoke.sh"
LOCAL_SOAK_LAUNCHER="${PROJECT_ROOT}/wepo-blockchain/scripts/run_canonical_fee_soak.sh"
SMOKE_SCRIPT="${PROJECT_ROOT}/canonical_fee_settlement_smoke.py"

GATE_MODE="${GATE_MODE:-assume-running}"
RELEASE_GATE_LOG_DIR="${RELEASE_GATE_LOG_DIR:-/tmp/wepo-canonical-release-gate}"
BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:8011}"
NODE_BASE_URL="${NODE_BASE_URL:-http://127.0.0.1:8122}"
BACKEND_ENV_PATH="${BACKEND_ENV_PATH:-${PROJECT_ROOT}/backend/.env}"
MONGO_URL="${MONGO_URL:-}"
DB_NAME="${DB_NAME:-}"
SETTLEMENT_ADDRESS="${SETTLEMENT_ADDRESS:-}"

VERIFY_IDEMPOTENT_REPLAY="${VERIFY_IDEMPOTENT_REPLAY:-true}"
VERIFY_CONCURRENT_IDEMPOTENCY="${VERIFY_CONCURRENT_IDEMPOTENCY:-true}"
EXPECT_SETTLEMENT_DEPLETION="${EXPECT_SETTLEMENT_DEPLETION:-false}"
RUN_SOAK="${RUN_SOAK:-true}"

SOAK_ITERATIONS="${SOAK_ITERATIONS:-5}"
SOAK_PAUSE_SECONDS="${SOAK_PAUSE_SECONDS:-1}"
MAX_FAILURES="${MAX_FAILURES:-1}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-30}"
BACKEND_RESTART_ITERATION="${BACKEND_RESTART_ITERATION:-0}"
NODE_RESTART_ITERATION="${NODE_RESTART_ITERATION:-0}"
RESTART_SETTLE_SECONDS="${RESTART_SETTLE_SECONDS:-1}"

TOTAL_CASES=0
PASSED_CASES=0
FAILED_CASES=0
GATE_STARTED_AT="$(date +%s)"
CASES_TSV=""
SUMMARY_LOG=""
SUMMARY_JSON=""

print_step() {
    printf '[wepo-gate] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

assert_gate_mode() {
    case "${GATE_MODE}" in
        local-managed|assume-running)
            ;;
        *)
            fail "Unsupported GATE_MODE=${GATE_MODE}; expected local-managed or assume-running"
            ;;
    esac
}

append_smoke_connection_args() {
    local -n target_args="$1"
    target_args+=(--backend-base-url "${BACKEND_BASE_URL}")
    target_args+=(--node-base-url "${NODE_BASE_URL}")
    target_args+=(--backend-env "${BACKEND_ENV_PATH}")
    if [[ -n "${MONGO_URL}" ]]; then
        target_args+=(--mongo-url "${MONGO_URL}")
    fi
    if [[ -n "${DB_NAME}" ]]; then
        target_args+=(--db-name "${DB_NAME}")
    fi
    if [[ -n "${SETTLEMENT_ADDRESS}" ]]; then
        target_args+=(--settlement-address "${SETTLEMENT_ADDRESS}")
    fi
}

write_summary_json() {
    GATE_FINISHED_AT="$(date +%s)"
    export TOTAL_CASES PASSED_CASES FAILED_CASES GATE_STARTED_AT GATE_FINISHED_AT
    export GATE_MODE RELEASE_GATE_LOG_DIR BACKEND_BASE_URL NODE_BASE_URL BACKEND_ENV_PATH
    export VERIFY_IDEMPOTENT_REPLAY VERIFY_CONCURRENT_IDEMPOTENCY EXPECT_SETTLEMENT_DEPLETION
    export RUN_SOAK SOAK_ITERATIONS SOAK_PAUSE_SECONDS MAX_FAILURES BACKEND_RESTART_ITERATION
    export NODE_RESTART_ITERATION RESTART_SETTLE_SECONDS MONGO_URL DB_NAME SETTLEMENT_ADDRESS

    python3 - "${CASES_TSV}" "${SUMMARY_JSON}" <<'PY'
import csv
import json
import os
import sys
from pathlib import Path

cases_path = Path(sys.argv[1])
summary_json_path = Path(sys.argv[2])

cases = []
if cases_path.exists():
    with cases_path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        cases = list(reader)

payload = {
    "mode": os.environ["GATE_MODE"],
    "total_cases": int(os.environ["TOTAL_CASES"]),
    "passed_cases": int(os.environ["PASSED_CASES"]),
    "failed_cases": int(os.environ["FAILED_CASES"]),
    "started_at": int(os.environ["GATE_STARTED_AT"]),
    "finished_at": int(os.environ["GATE_FINISHED_AT"]),
    "duration_seconds": int(os.environ["GATE_FINISHED_AT"]) - int(os.environ["GATE_STARTED_AT"]),
    "log_dir": os.environ["RELEASE_GATE_LOG_DIR"],
    "backend_base_url": os.environ["BACKEND_BASE_URL"],
    "node_base_url": os.environ["NODE_BASE_URL"],
    "backend_env_path": os.environ["BACKEND_ENV_PATH"],
    "mongo_url": os.environ["MONGO_URL"],
    "db_name": os.environ["DB_NAME"],
    "settlement_address": os.environ["SETTLEMENT_ADDRESS"],
    "config": {
        "verify_idempotent_replay": os.environ["VERIFY_IDEMPOTENT_REPLAY"] == "true",
        "verify_concurrent_idempotency": os.environ["VERIFY_CONCURRENT_IDEMPOTENCY"] == "true",
        "expect_settlement_depletion": os.environ["EXPECT_SETTLEMENT_DEPLETION"] == "true",
        "run_soak": os.environ["RUN_SOAK"] == "true",
        "soak_iterations": int(os.environ["SOAK_ITERATIONS"]),
        "soak_pause_seconds": int(os.environ["SOAK_PAUSE_SECONDS"]),
        "max_failures": int(os.environ["MAX_FAILURES"]),
        "backend_restart_iteration": int(os.environ["BACKEND_RESTART_ITERATION"]),
        "node_restart_iteration": int(os.environ["NODE_RESTART_ITERATION"]),
        "restart_settle_seconds": int(os.environ["RESTART_SETTLE_SECONDS"]),
    },
    "cases": cases,
}

summary_json_path.write_text(json.dumps(payload, indent=2) + "\n")
PY
}

cleanup() {
    local exit_code=$?
    {
        printf 'mode=%s\n' "${GATE_MODE}"
        printf 'total_cases=%s\n' "${TOTAL_CASES}"
        printf 'passed_cases=%s\n' "${PASSED_CASES}"
        printf 'failed_cases=%s\n' "${FAILED_CASES}"
    } >>"${SUMMARY_LOG}"
    write_summary_json
    if [[ ${exit_code} -eq 0 ]]; then
        print_step "Release gate complete summary=${SUMMARY_JSON}"
    else
        print_step "Release gate failed summary=${SUMMARY_JSON}"
    fi
}

trap cleanup EXIT INT TERM

record_case_result() {
    local case_name="$1"
    local status="$2"
    local duration_seconds="$3"
    local log_path="$4"
    local artifact_path="${5:-}"

    TOTAL_CASES=$((TOTAL_CASES + 1))
    if [[ "${status}" == "pass" ]]; then
        PASSED_CASES=$((PASSED_CASES + 1))
    else
        FAILED_CASES=$((FAILED_CASES + 1))
    fi

    printf '%s\t%s\t%s\t%s\t%s\n' \
        "${case_name}" "${status}" "${duration_seconds}" "${log_path}" "${artifact_path}" \
        >>"${CASES_TSV}"
    printf 'case=%s status=%s duration_seconds=%s log=%s artifact=%s\n' \
        "${case_name}" "${status}" "${duration_seconds}" "${log_path}" "${artifact_path}" \
        >>"${SUMMARY_LOG}"
}

run_case() {
    local case_name="$1"
    shift
    local log_path="${RELEASE_GATE_LOG_DIR}/${case_name}.log"
    local started_at finished_at duration_seconds

    started_at="$(date +%s)"
    print_step "Starting case ${case_name}"
    if "$@" >"${log_path}" 2>&1; then
        finished_at="$(date +%s)"
        duration_seconds=$((finished_at - started_at))
        record_case_result "${case_name}" "pass" "${duration_seconds}" "${log_path}"
        print_step "PASS case ${case_name}"
        return 0
    fi

    finished_at="$(date +%s)"
    duration_seconds=$((finished_at - started_at))
    record_case_result "${case_name}" "fail" "${duration_seconds}" "${log_path}"
    print_step "FAIL case ${case_name}"
    return 1
}

run_local_smoke_case() {
    local case_name="$1"
    shift
    run_case "${case_name}" env \
        LOG_DIR="${RELEASE_GATE_LOG_DIR}/${case_name}-launcher" \
        SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS}" \
        "$@" \
        "${LOCAL_SMOKE_LAUNCHER}"
}

run_assumed_stack_smoke_case() {
    local case_name="$1"
    shift
    local -a smoke_args=("${SMOKE_SCRIPT}")
    append_smoke_connection_args smoke_args
    smoke_args+=(--mine-timeout "${SMOKE_TIMEOUT_SECONDS}")
    smoke_args+=("$@")
    run_case "${case_name}" python3 "${smoke_args[@]}"
}

run_local_soak_case() {
    local case_name="soak"
    local soak_dir="${RELEASE_GATE_LOG_DIR}/soak"
    local log_path="${RELEASE_GATE_LOG_DIR}/${case_name}.log"
    local started_at finished_at duration_seconds

    mkdir -p "${soak_dir}"
    started_at="$(date +%s)"
    print_step "Starting case ${case_name}"
    if env \
        SOAK_LOG_DIR="${soak_dir}" \
        SOAK_ITERATIONS="${SOAK_ITERATIONS}" \
        SOAK_PAUSE_SECONDS="${SOAK_PAUSE_SECONDS}" \
        MAX_FAILURES="${MAX_FAILURES}" \
        BACKEND_RESTART_ITERATION="${BACKEND_RESTART_ITERATION}" \
        NODE_RESTART_ITERATION="${NODE_RESTART_ITERATION}" \
        RESTART_SETTLE_SECONDS="${RESTART_SETTLE_SECONDS}" \
        "${LOCAL_SOAK_LAUNCHER}" \
        >"${log_path}" 2>&1; then
        finished_at="$(date +%s)"
        duration_seconds=$((finished_at - started_at))
        record_case_result "${case_name}" "pass" "${duration_seconds}" "${log_path}" "${soak_dir}/summary.json"
        print_step "PASS case ${case_name}"
        return 0
    fi

    finished_at="$(date +%s)"
    duration_seconds=$((finished_at - started_at))
    record_case_result "${case_name}" "fail" "${duration_seconds}" "${log_path}" "${soak_dir}/summary.json"
    print_step "FAIL case ${case_name}"
    return 1
}

run_assumed_stack_soak_case() {
    local case_name="soak"
    local soak_dir="${RELEASE_GATE_LOG_DIR}/soak"
    local case_log="${RELEASE_GATE_LOG_DIR}/${case_name}.log"
    local case_summary="${soak_dir}/summary.log"
    local case_json="${soak_dir}/summary.json"
    local started_at finished_at duration_seconds
    local total_runs=0
    local passed_runs=0
    local failed_runs=0

    mkdir -p "${soak_dir}"
    : >"${case_log}"
    : >"${case_summary}"
    printf 'iteration\tstatus\tlog_path\n' >"${soak_dir}/iterations.tsv"

    started_at="$(date +%s)"
    print_step "Starting case ${case_name}"

    for (( iteration=1; iteration<=SOAK_ITERATIONS; iteration++ )); do
        local iteration_log="${soak_dir}/smoke-${iteration}.log"
        local -a smoke_args=("${SMOKE_SCRIPT}")
        append_smoke_connection_args smoke_args
        smoke_args+=(--mine-timeout "${SMOKE_TIMEOUT_SECONDS}")
        total_runs=$((total_runs + 1))

        if python3 "${smoke_args[@]}" >"${iteration_log}" 2>&1; then
            passed_runs=$((passed_runs + 1))
            printf '%s\tpass\t%s\n' "${iteration}" "${iteration_log}" >>"${soak_dir}/iterations.tsv"
            printf 'iteration=%s status=pass log=%s\n' "${iteration}" "${iteration_log}" >>"${case_summary}"
        else
            failed_runs=$((failed_runs + 1))
            printf '%s\tfail\t%s\n' "${iteration}" "${iteration_log}" >>"${soak_dir}/iterations.tsv"
            printf 'iteration=%s status=fail log=%s\n' "${iteration}" "${iteration_log}" >>"${case_summary}"
            if (( failed_runs >= MAX_FAILURES )); then
                break
            fi
        fi

        if (( iteration < SOAK_ITERATIONS )) && (( SOAK_PAUSE_SECONDS > 0 )); then
            sleep "${SOAK_PAUSE_SECONDS}"
        fi
    done

    {
        printf 'total_runs=%s\n' "${total_runs}"
        printf 'passed_runs=%s\n' "${passed_runs}"
        printf 'failed_runs=%s\n' "${failed_runs}"
    } >>"${case_summary}"

    python3 - "${soak_dir}/iterations.tsv" "${case_json}" "${SOAK_ITERATIONS}" "${SOAK_PAUSE_SECONDS}" "${MAX_FAILURES}" <<'PY'
import csv
import json
import sys
from pathlib import Path

iterations_path = Path(sys.argv[1])
summary_json_path = Path(sys.argv[2])
payload = {
    "config": {
        "soak_iterations": int(sys.argv[3]),
        "soak_pause_seconds": int(sys.argv[4]),
        "max_failures": int(sys.argv[5]),
    },
    "iterations": [],
}

with iterations_path.open() as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    payload["iterations"] = list(reader)

payload["total_runs"] = len(payload["iterations"])
payload["passed_runs"] = sum(1 for item in payload["iterations"] if item["status"] == "pass")
payload["failed_runs"] = sum(1 for item in payload["iterations"] if item["status"] == "fail")
summary_json_path.write_text(json.dumps(payload, indent=2) + "\n")
PY

    cat "${case_summary}" >"${case_log}"

    finished_at="$(date +%s)"
    duration_seconds=$((finished_at - started_at))
    if (( failed_runs == 0 )); then
        record_case_result "${case_name}" "pass" "${duration_seconds}" "${case_log}" "${case_json}"
        print_step "PASS case ${case_name}"
        return 0
    fi

    record_case_result "${case_name}" "fail" "${duration_seconds}" "${case_log}" "${case_json}"
    print_step "FAIL case ${case_name}"
    return 1
}

run_release_gate() {
    local status=0

    if [[ "${GATE_MODE}" == "local-managed" ]]; then
        run_local_smoke_case "happy_path" || status=1
        if [[ "${VERIFY_IDEMPOTENT_REPLAY}" == "true" ]]; then
            run_local_smoke_case "idempotent_replay" VERIFY_IDEMPOTENT_REPLAY=true || status=1
        fi
        if [[ "${VERIFY_CONCURRENT_IDEMPOTENCY}" == "true" ]]; then
            run_local_smoke_case "concurrent_idempotency" VERIFY_CONCURRENT_IDEMPOTENCY=true || status=1
        fi
        if [[ "${EXPECT_SETTLEMENT_DEPLETION}" == "true" ]]; then
            run_local_smoke_case "settlement_depletion" EXPECT_SETTLEMENT_DEPLETION=true || status=1
        fi
        if [[ "${RUN_SOAK}" == "true" ]]; then
            run_local_soak_case || status=1
        fi
    else
        run_assumed_stack_smoke_case "happy_path" || status=1
        if [[ "${VERIFY_IDEMPOTENT_REPLAY}" == "true" ]]; then
            run_assumed_stack_smoke_case "idempotent_replay" --verify-idempotent-replay || status=1
        fi
        if [[ "${VERIFY_CONCURRENT_IDEMPOTENCY}" == "true" ]]; then
            run_assumed_stack_smoke_case "concurrent_idempotency" --verify-concurrent-idempotency || status=1
        fi
        if [[ "${EXPECT_SETTLEMENT_DEPLETION}" == "true" ]]; then
            run_assumed_stack_smoke_case "settlement_depletion" --expect-settlement-depletion || status=1
        fi
        if [[ "${RUN_SOAK}" == "true" ]]; then
            run_assumed_stack_soak_case || status=1
        fi
    fi

    return "${status}"
}

assert_gate_mode
mkdir -p "${RELEASE_GATE_LOG_DIR}"
CASES_TSV="${RELEASE_GATE_LOG_DIR}/cases.tsv"
SUMMARY_LOG="${RELEASE_GATE_LOG_DIR}/summary.log"
SUMMARY_JSON="${RELEASE_GATE_LOG_DIR}/summary.json"
printf 'case\tstatus\tduration_seconds\tlog_path\tartifact_path\n' >"${CASES_TSV}"
: >"${SUMMARY_LOG}"

print_step "Mode=${GATE_MODE} backend=${BACKEND_BASE_URL} node=${NODE_BASE_URL}"
run_release_gate
