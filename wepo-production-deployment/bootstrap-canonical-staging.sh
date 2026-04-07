#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WEPO_USER="${WEPO_USER:-wepo}"
WEPO_GROUP="${WEPO_GROUP:-wepo}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/wepo}"
WEPO_ETC_DIR="${WEPO_ETC_DIR:-/etc/wepo}"
WEPO_DATA_DIR="${WEPO_DATA_DIR:-/var/lib/wepo}"
WEPO_LOG_DIR="${WEPO_LOG_DIR:-/var/log/wepo}"
DOMAIN="${DOMAIN:-staging-api.sparkpitlabs.com}"
BACKEND_SERVICE_NAME="${BACKEND_SERVICE_NAME:-wepo-backend}"
NODE_SERVICE_NAME="${NODE_SERVICE_NAME:-wepo-node}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-wepo-api}"
STAGING_MINER_ADDRESS="${STAGING_MINER_ADDRESS:-wepo1replacewithfundedstagingaddress}"
FORCE_OVERWRITE="${FORCE_OVERWRITE:-false}"

print_step() {
    printf '[wepo-bootstrap] %s\n' "$1"
}

fail() {
    print_step "FAIL $1"
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        fail "Run this script as root"
    fi
}

ensure_group() {
    if getent group "${WEPO_GROUP}" >/dev/null 2>&1; then
        return
    fi
    print_step "Creating group ${WEPO_GROUP}"
    groupadd --system "${WEPO_GROUP}"
}

ensure_user() {
    if id "${WEPO_USER}" >/dev/null 2>&1; then
        return
    fi
    print_step "Creating user ${WEPO_USER}"
    useradd --system --gid "${WEPO_GROUP}" --home "${INSTALL_ROOT}" --shell /usr/sbin/nologin "${WEPO_USER}"
}

ensure_directories() {
    print_step "Creating canonical staging directories"
    install -d -m 0755 -o "${WEPO_USER}" -g "${WEPO_GROUP}" "${INSTALL_ROOT}"
    install -d -m 0755 -o "${WEPO_USER}" -g "${WEPO_GROUP}" "${WEPO_DATA_DIR}"
    install -d -m 0755 -o "${WEPO_USER}" -g "${WEPO_GROUP}" "${WEPO_DATA_DIR}/node"
    install -d -m 0755 -o "${WEPO_USER}" -g "${WEPO_GROUP}" "${WEPO_LOG_DIR}"
    install -d -m 0750 -o root -g "${WEPO_GROUP}" "${WEPO_ETC_DIR}"
}

render_template() {
    local source_path="$1"
    sed \
        -e "s#/opt/wepo#${INSTALL_ROOT}#g" \
        -e "s#staging-api.sparkpitlabs.com#${DOMAIN}#g" \
        -e "s#wepo1replacewithfundedstagingaddress#${STAGING_MINER_ADDRESS}#g" \
        "${source_path}"
}

install_rendered_template() {
    local source_path="$1"
    local destination_path="$2"
    local mode="$3"
    local owner="$4"
    local group="$5"
    local temp_path

    if [[ -e "${destination_path}" && "${FORCE_OVERWRITE}" != "true" ]]; then
        print_step "Keeping existing ${destination_path}"
        return
    fi

    temp_path="$(mktemp)"
    render_template "${source_path}" >"${temp_path}"
    install -m "${mode}" -o "${owner}" -g "${group}" "${temp_path}" "${destination_path}"
    rm -f "${temp_path}"
    print_step "Installed ${destination_path}"
}

require_paths() {
    [[ -d "${PROJECT_ROOT}" ]] || fail "Project root not found at ${PROJECT_ROOT}"
    [[ -f "${SCRIPT_DIR}/backend.env.example" ]] || fail "Missing backend.env.example"
    [[ -f "${SCRIPT_DIR}/wepo-backend.service.example" ]] || fail "Missing backend service template"
    [[ -f "${SCRIPT_DIR}/wepo-node.service.example" ]] || fail "Missing node service template"
    [[ -f "${SCRIPT_DIR}/nginx-wepo-api.conf.example" ]] || fail "Missing nginx template"
}

print_next_steps() {
    cat <<EOF

[wepo-bootstrap] Bootstrap complete.

Next steps:
1. Sync the current WEPO repo to ${INSTALL_ROOT}
2. Create the Python environment at ${INSTALL_ROOT}/.venv and install backend requirements
3. Edit ${WEPO_ETC_DIR}/backend.env with real Mongo, settlement wallet, and origin allowlist values
4. Review /etc/systemd/system/${NODE_SERVICE_NAME}.service for the staging miner address
5. Run: systemctl daemon-reload
6. Run: systemctl enable --now ${NODE_SERVICE_NAME} ${BACKEND_SERVICE_NAME}
7. Install TLS for ${DOMAIN} and reload nginx
8. Run the canonical release gate:
   GATE_MODE=assume-running BACKEND_BASE_URL=http://127.0.0.1:8011 NODE_BASE_URL=http://127.0.0.1:8122 BACKEND_ENV_PATH=${WEPO_ETC_DIR}/backend.env SOAK_ITERATIONS=5 ${INSTALL_ROOT}/wepo-production-deployment/run-canonical-release-gate.sh

This script does not start services automatically because the env file and funded addresses must be reviewed first.
EOF
}

require_root
require_paths
ensure_group
ensure_user
ensure_directories

install_rendered_template \
    "${SCRIPT_DIR}/backend.env.example" \
    "${WEPO_ETC_DIR}/backend.env" \
    0640 \
    root \
    "${WEPO_GROUP}"

install_rendered_template \
    "${SCRIPT_DIR}/wepo-backend.service.example" \
    "/etc/systemd/system/${BACKEND_SERVICE_NAME}.service" \
    0644 \
    root \
    root

install_rendered_template \
    "${SCRIPT_DIR}/wepo-node.service.example" \
    "/etc/systemd/system/${NODE_SERVICE_NAME}.service" \
    0644 \
    root \
    root

install_rendered_template \
    "${SCRIPT_DIR}/nginx-wepo-api.conf.example" \
    "/etc/nginx/sites-available/${NGINX_SITE_NAME}" \
    0644 \
    root \
    root

ln -sfn "/etc/nginx/sites-available/${NGINX_SITE_NAME}" "/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
print_step "Enabled nginx site /etc/nginx/sites-enabled/${NGINX_SITE_NAME}"

print_next_steps
