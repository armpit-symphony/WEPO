#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAB_LAUNCHER="${PROJECT_ROOT}/wepo-blockchain/scripts/run_test_mode_wallet_lab.sh"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
FRONTEND_SERVER="${FRONTEND_DIR}/secure-server.js"

LAB_SESSION="${LAB_SESSION:-wepo-public-test-lab}"
FRONTEND_SESSION="${FRONTEND_SESSION:-wepo-public-test-frontend}"

FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:18021}"
NODE_BASE_URL="${NODE_BASE_URL:-http://127.0.0.1:18212}"

AUTO_BUILD_FRONTEND="${AUTO_BUILD_FRONTEND:-true}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-60}"

ACTION="${1:-start}"

print_step() {
    printf '[wepo-public-test] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

require_command() {
    local name="$1"
    command -v "${name}" >/dev/null 2>&1 || fail "Missing required command: ${name}"
}

session_exists() {
    local session_name="$1"
    tmux has-session -t "${session_name}" 2>/dev/null
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

ensure_port_free() {
    local port="$1"
    if ss -ltn | awk '{print $4}' | grep -Eq "[:.]${port}$"; then
        fail "Port ${port} is already in use"
    fi
}

start_stack() {
    local reset_lab_state="${1:-0}"

    require_command tmux
    require_command curl
    require_command node
    require_command npm

    [[ -x "${LAB_LAUNCHER}" ]] || fail "Missing launcher ${LAB_LAUNCHER}"
    [[ -f "${FRONTEND_SERVER}" ]] || fail "Missing frontend server ${FRONTEND_SERVER}"

    if session_exists "${LAB_SESSION}" || session_exists "${FRONTEND_SESSION}"; then
        fail "tmux session already exists; run '$0 status' or '$0 stop' first"
    fi

    ensure_port_free "${FRONTEND_PORT}"

    if [[ "${AUTO_BUILD_FRONTEND}" == "true" ]]; then
        print_step "Building frontend bundle"
        (
            cd "${FRONTEND_DIR}"
            npm run build
        )
    fi

    print_step "Starting wallet lab tmux session ${LAB_SESSION}"
    tmux new -d -s "${LAB_SESSION}" "RESET_LAB_STATE=${reset_lab_state} ${LAB_LAUNCHER}"

    if ! wait_for_http "${NODE_BASE_URL}/api/network/status" "${READY_TIMEOUT_SECONDS}"; then
        fail "Node did not become ready in tmux session ${LAB_SESSION}"
    fi

    if ! wait_for_http "${BACKEND_BASE_URL}/api/" "${READY_TIMEOUT_SECONDS}"; then
        fail "Backend did not become ready in tmux session ${LAB_SESSION}"
    fi

    print_step "Starting frontend tmux session ${FRONTEND_SESSION}"
    tmux new -d -s "${FRONTEND_SESSION}" "cd ${FRONTEND_DIR} && PORT=${FRONTEND_PORT} HOST=${FRONTEND_HOST} node ${FRONTEND_SERVER}"

    if ! wait_for_http "http://${FRONTEND_HOST}:${FRONTEND_PORT}/health" "${READY_TIMEOUT_SECONDS}"; then
        fail "Frontend did not become ready in tmux session ${FRONTEND_SESSION}"
    fi

    print_step "PASS local public-test stack is ready"
    print_step "frontend=http://${FRONTEND_HOST}:${FRONTEND_PORT}"
    print_step "backend=${BACKEND_BASE_URL}"
    print_step "node=${NODE_BASE_URL}"
    print_step "Use '$0 logs' to inspect tmux output"
    print_step "Use '$0 stop' to tear the stack down"
}

stop_stack() {
    require_command tmux

    if session_exists "${FRONTEND_SESSION}"; then
        print_step "Stopping tmux session ${FRONTEND_SESSION}"
        tmux kill-session -t "${FRONTEND_SESSION}"
    fi

    if session_exists "${LAB_SESSION}"; then
        print_step "Stopping tmux session ${LAB_SESSION}"
        tmux kill-session -t "${LAB_SESSION}"
    fi

    print_step "Local public-test stack stopped"
}

status_stack() {
    require_command tmux
    require_command curl

    print_step "tmux sessions"
    if session_exists "${LAB_SESSION}"; then
        print_step "lab session ${LAB_SESSION}: running"
    else
        print_step "lab session ${LAB_SESSION}: stopped"
    fi

    if session_exists "${FRONTEND_SESSION}"; then
        print_step "frontend session ${FRONTEND_SESSION}: running"
    else
        print_step "frontend session ${FRONTEND_SESSION}: stopped"
    fi

    print_step "HTTP probes"
    if curl -fsS "${NODE_BASE_URL}/api/network/status" >/dev/null 2>&1; then
        print_step "node ${NODE_BASE_URL}: up"
    else
        print_step "node ${NODE_BASE_URL}: down"
    fi

    if curl -fsS "${BACKEND_BASE_URL}/api/" >/dev/null 2>&1; then
        print_step "backend ${BACKEND_BASE_URL}: up"
    else
        print_step "backend ${BACKEND_BASE_URL}: down"
    fi

    if curl -fsS "http://${FRONTEND_HOST}:${FRONTEND_PORT}/health" >/dev/null 2>&1; then
        print_step "frontend http://${FRONTEND_HOST}:${FRONTEND_PORT}: up"
    else
        print_step "frontend http://${FRONTEND_HOST}:${FRONTEND_PORT}: down"
    fi
}

logs_stack() {
    require_command tmux

    if session_exists "${LAB_SESSION}"; then
        print_step "tmux ${LAB_SESSION}"
        tmux capture-pane -pt "${LAB_SESSION}"
    else
        print_step "tmux ${LAB_SESSION}: not running"
    fi

    if session_exists "${FRONTEND_SESSION}"; then
        print_step "tmux ${FRONTEND_SESSION}"
        tmux capture-pane -pt "${FRONTEND_SESSION}"
    else
        print_step "tmux ${FRONTEND_SESSION}: not running"
    fi
}

restart_clean_stack() {
    stop_stack
    start_stack 1
}

case "${ACTION}" in
    start)
        start_stack 0
        ;;
    start-clean)
        start_stack 1
        ;;
    restart-clean)
        restart_clean_stack
        ;;
    stop)
        stop_stack
        ;;
    status)
        status_stack
        ;;
    logs)
        logs_stack
        ;;
    *)
        fail "Unsupported action '${ACTION}'. Use: start | start-clean | restart-clean | stop | status | logs"
        ;;
esac
