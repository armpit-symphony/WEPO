#!/usr/bin/env bash
set -euo pipefail

WEPO_ETC_DIR="${WEPO_ETC_DIR:-/etc/wepo}"
WEPO_LOG_DIR="${WEPO_LOG_DIR:-/var/log/wepo}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/wepo}"
BACKEND_ENV_PATH="${BACKEND_ENV_PATH:-${WEPO_ETC_DIR}/backend.env}"
BACKEND_SERVICE_NAME="${BACKEND_SERVICE_NAME:-wepo-backend}"
NODE_SERVICE_NAME="${NODE_SERVICE_NAME:-wepo-node}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-wepo-api}"
BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:8011}"
NODE_BASE_URL="${NODE_BASE_URL:-http://127.0.0.1:8122}"
RUN_RELEASE_GATE="${RUN_RELEASE_GATE:-true}"
SOAK_ITERATIONS="${SOAK_ITERATIONS:-5}"
SOAK_PAUSE_SECONDS="${SOAK_PAUSE_SECONDS:-1}"
MAX_FAILURES="${MAX_FAILURES:-1}"
RELEASE_GATE_LOG_DIR="${RELEASE_GATE_LOG_DIR:-${WEPO_LOG_DIR}/release-gate-$(date +%Y%m%d-%H%M%S)}"
PYTHON_BIN="${PYTHON_BIN:-${INSTALL_ROOT}/.venv/bin/python}"

MONGO_URL_VALUE=""
DB_NAME_VALUE=""
NODE_API_URL_VALUE=""
CANONICAL_FEES_VALUE=""
SETTLEMENT_ADDRESS_VALUE=""
ALLOWED_ORIGINS_VALUE=""

print_step() {
    printf '[wepo-host-check] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        fail "Run this script as root so it can inspect /etc, systemd, and nginx"
    fi
}

require_file() {
    local path="$1"
    [[ -f "${path}" ]] || fail "Missing required file ${path}"
}

require_command() {
    local cmd="$1"
    command -v "${cmd}" >/dev/null 2>&1 || fail "Required command not found: ${cmd}"
}

load_backend_env() {
    require_file "${BACKEND_ENV_PATH}"
    set -a
    # shellcheck disable=SC1090
    source "${BACKEND_ENV_PATH}"
    set +a

    MONGO_URL_VALUE="${MONGO_URL:-}"
    DB_NAME_VALUE="${DB_NAME:-}"
    NODE_API_URL_VALUE="${WEPO_NODE_API_URL:-}"
    CANONICAL_FEES_VALUE="${WEPO_CANONICAL_APPLICATION_FEES_ENABLED:-}"
    SETTLEMENT_ADDRESS_VALUE="${WEPO_APP_FEE_SETTLEMENT_ADDRESS:-}"
    ALLOWED_ORIGINS_VALUE="${WEPO_ALLOWED_ORIGINS:-}"
}

validate_backend_env() {
    [[ -n "${MONGO_URL_VALUE}" ]] || fail "MONGO_URL is empty in ${BACKEND_ENV_PATH}"
    [[ -n "${DB_NAME_VALUE}" ]] || fail "DB_NAME is empty in ${BACKEND_ENV_PATH}"
    [[ -n "${NODE_API_URL_VALUE}" ]] || fail "WEPO_NODE_API_URL is empty in ${BACKEND_ENV_PATH}"
    [[ "${CANONICAL_FEES_VALUE,,}" == "true" ]] || fail "WEPO_CANONICAL_APPLICATION_FEES_ENABLED must be true in ${BACKEND_ENV_PATH}"
    [[ -n "${SETTLEMENT_ADDRESS_VALUE}" ]] || fail "WEPO_APP_FEE_SETTLEMENT_ADDRESS is empty in ${BACKEND_ENV_PATH}"
    [[ "${SETTLEMENT_ADDRESS_VALUE}" != "wepo1replacewithfundedstagingaddress" ]] || fail "WEPO_APP_FEE_SETTLEMENT_ADDRESS still has the placeholder value"
    [[ -n "${ALLOWED_ORIGINS_VALUE}" ]] || fail "WEPO_ALLOWED_ORIGINS is empty in ${BACKEND_ENV_PATH}"
    print_step "Backend env loaded db=${DB_NAME_VALUE} node_api=${NODE_API_URL_VALUE}"
}

check_systemd_unit() {
    local service_name="$1"
    systemctl status "${service_name}" --no-pager >/dev/null 2>&1 || fail "systemd unit ${service_name} is not installed cleanly"
    systemctl is-enabled "${service_name}" >/dev/null 2>&1 || fail "systemd unit ${service_name} is not enabled"
    systemctl is-active "${service_name}" >/dev/null 2>&1 || fail "systemd unit ${service_name} is not active"
    print_step "Service healthy ${service_name}"
}

check_nginx() {
    require_file "/etc/nginx/sites-available/${NGINX_SITE_NAME}"
    [[ -L "/etc/nginx/sites-enabled/${NGINX_SITE_NAME}" ]] || fail "nginx site ${NGINX_SITE_NAME} is not enabled"
    nginx -t >/dev/null 2>&1 || fail "nginx configuration test failed"
    print_step "nginx configuration passes"
}

check_local_http() {
    local url="$1"
    local label="$2"
    curl -fsS "${url}" >/dev/null || fail "${label} endpoint failed at ${url}"
    print_step "${label} reachable ${url}"
}

run_release_gate() {
    local gate_script="${INSTALL_ROOT}/wepo-production-deployment/run-canonical-release-gate.sh"
    [[ -x "${gate_script}" ]] || fail "Canonical release gate script missing or not executable at ${gate_script}"
    mkdir -p "${RELEASE_GATE_LOG_DIR}"
    print_step "Running canonical release gate logs=${RELEASE_GATE_LOG_DIR}"
    GATE_MODE=assume-running \
    PYTHON_BIN="${PYTHON_BIN}" \
    BACKEND_BASE_URL="${BACKEND_BASE_URL}" \
    NODE_BASE_URL="${NODE_BASE_URL}" \
    BACKEND_ENV_PATH="${BACKEND_ENV_PATH}" \
    SOAK_ITERATIONS="${SOAK_ITERATIONS}" \
    SOAK_PAUSE_SECONDS="${SOAK_PAUSE_SECONDS}" \
    MAX_FAILURES="${MAX_FAILURES}" \
    RELEASE_GATE_LOG_DIR="${RELEASE_GATE_LOG_DIR}" \
    "${gate_script}"
}

require_root
require_command curl
require_command systemctl
require_command nginx
load_backend_env
validate_backend_env
check_systemd_unit "${NODE_SERVICE_NAME}"
check_systemd_unit "${BACKEND_SERVICE_NAME}"
check_nginx
check_local_http "${BACKEND_BASE_URL}/api/" "backend"
check_local_http "${NODE_BASE_URL}/api/network/status" "node"

if [[ "${RUN_RELEASE_GATE}" == "true" ]]; then
    run_release_gate
else
    print_step "Skipping canonical release gate because RUN_RELEASE_GATE=${RUN_RELEASE_GATE}"
fi

print_step "PASS canonical staging host verification completed"
