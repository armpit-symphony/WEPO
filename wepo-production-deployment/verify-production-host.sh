#!/usr/bin/env bash
# Read-only qualification gate for an already installed WEPO release host.
# It never installs, starts, stops, reloads, or edits a service.
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/wepo/current}"
PYTHON_BIN="${PYTHON_BIN:-/opt/wepo/venv/bin/python}"
BACKEND_ENV_PATH="${BACKEND_ENV_PATH:-/etc/wepo/backend.env}"
NODE_ENV_PATH="${NODE_ENV_PATH:-/etc/wepo/node.env}"
NGINX_SITE_PATH="${NGINX_SITE_PATH:-/etc/nginx/sites-available/wepo-api}"
TLS_CERT_PATH="${TLS_CERT_PATH:-/etc/wepo/tls/fullchain.pem}"
TLS_KEY_PATH="${TLS_KEY_PATH:-/etc/wepo/tls/privkey.pem}"
RELEASE_MANIFEST_PATH="${RELEASE_MANIFEST_PATH:-${INSTALL_ROOT}/SHA256SUMS}"
BACKEND_SERVICE_NAME="${BACKEND_SERVICE_NAME:-wepo-backend}"
RELEASE_MANIFEST_SIGNATURE_PATH="${RELEASE_MANIFEST_SIGNATURE_PATH:-${RELEASE_MANIFEST_PATH}.sig}"
RELEASE_SIGNING_PUBLIC_KEY_PATH="${RELEASE_SIGNING_PUBLIC_KEY_PATH:-/etc/wepo/release-signing-public.pem}"
NODE_SERVICE_NAME="${NODE_SERVICE_NAME:-wepo-node}"
PUBLIC_API_HOST="${PUBLIC_API_HOST:-}"
CERT_MIN_SECONDS="${CERT_MIN_SECONDS:-1209600}"
EXPECTED_NETWORK="${EXPECTED_NETWORK:-mainnet}"

fail() {
    printf '[wepo-production-check] FAIL %s\n' "$1" >&2
    exit 1
}

pass() {
    printf '[wepo-production-check] PASS %s\n' "$1"
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || fail "run as root for read-only host inspection"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

require_regular_file() {
    local path="$1"
    [[ -f "${path}" ]] || fail "required file is missing: ${path}"
    [[ ! -L "${path}" ]] || fail "symlink is forbidden for security file: ${path}"
}

require_private_file() {
    local path="$1"
    local mode owner
    require_regular_file "${path}"
    mode="$(stat -c '%a' "${path}")"
    owner="$(stat -c '%U' "${path}")"
    [[ "${owner}" == "root" ]] || fail "${path} must be root-owned"
    [[ "${mode}" == "600" || "${mode}" == "640" ]] || fail "${path} must be mode 0600 or 0640"
}

env_value() {
    local path="$1"
    local key="$2"
    "${PYTHON_BIN}" - "${path}" "${key}" <<'PY'
import re
import sys

path, key = sys.argv[1:]
pattern = re.compile(r"^" + re.escape(key) + r"=(.*)$")
values = []
with open(path, encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.fullmatch(line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.append(value)
if len(values) != 1:
    raise SystemExit(f"expected exactly one {key} entry in {path}, found {len(values)}")
print(values[0])
PY
}

require_exact_env() {
    local path="$1"
    local key="$2"
    local expected="$3"
    local actual
    actual="$(env_value "${path}" "${key}")" || fail "could not read ${key} from ${path}"
    [[ "${actual}" == "${expected}" ]] || fail "${key} must equal ${expected} in ${path}"
}

validate_backend_env() {
    local origins node_url redis_url mongo_url
    require_private_file "${BACKEND_ENV_PATH}"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_NETWORK_PROFILE "${EXPECTED_NETWORK}"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_NODE_API_URL "http://127.0.0.1:8122"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_REQUIRE_REDIS_RATE_LIMIT "1"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_TRUST_PROXY_HEADERS "1"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_FEATURE_PRIVACY "0"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_FEATURE_RWA "0"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_FEATURE_BTC "0"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_FEATURE_MESSAGING "0"
    require_exact_env "${BACKEND_ENV_PATH}" WEPO_ENABLE_STAGING_TOGGLES "0"

    origins="$(env_value "${BACKEND_ENV_PATH}" WEPO_ALLOWED_ORIGINS)"
    node_url="$(env_value "${BACKEND_ENV_PATH}" WEPO_NODE_API_URL)"
    redis_url="$(env_value "${BACKEND_ENV_PATH}" REDIS_URL)"
    mongo_url="$(env_value "${BACKEND_ENV_PATH}" MONGO_URL)"
    [[ -n "${origins}" && -n "${redis_url}" && -n "${mongo_url}" ]] || fail "backend endpoints and origins must be nonempty"
    [[ "${node_url}" == "http://127.0.0.1:8122" ]] || fail "backend node API must remain loopback-only"
    if printf '%s\n' "${origins}" | grep -Eiq 'example\.invalid|REPLACE|localhost|127\.0\.0\.1|\*'; then
        fail "backend origin allowlist contains a placeholder, wildcard, or loopback origin"
    fi
    if printf '%s\n%s\n' "${redis_url}" "${mongo_url}" | grep -Eiq 'example\.invalid|REPLACE'; then
        fail "backend datastore configuration contains a placeholder"
    fi
    WEPO_ORIGINS="${origins}" "${PYTHON_BIN}" - <<'PY'
import os
from urllib.parse import urlsplit

origins = [item.strip() for item in os.environ["WEPO_ORIGINS"].split(",") if item.strip()]
if not origins:
    raise SystemExit("no allowed origins")
for origin in origins:
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise SystemExit(f"origin is not an HTTPS origin: {origin}")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(f"loopback origin is forbidden: {origin}")
PY
    pass "backend environment is production-bound and fail-closed"
}

validate_node_env() {
    local peers dns
    require_private_file "${NODE_ENV_PATH}"
    require_exact_env "${NODE_ENV_PATH}" WEPO_NETWORK_PROFILE "${EXPECTED_NETWORK}"
    require_exact_env "${NODE_ENV_PATH}" WEPO_REQUIRE_MAINNET_SEEDS "1"
    require_exact_env "${NODE_ENV_PATH}" WEPO_NODE_API_HOST "127.0.0.1"
    peers="$(env_value "${NODE_ENV_PATH}" WEPO_STATIC_PEERS)"
    dns="$(env_value "${NODE_ENV_PATH}" WEPO_DNS_SEEDS)"
    [[ -n "${peers}${dns}" ]] || fail "at least one static or DNS seed source is required"
    if printf '%s\n%s\n' "${peers}" "${dns}" | grep -Eiq 'example\.invalid|REPLACE|localhost|127\.0\.0\.1'; then
        fail "node seed configuration contains a placeholder or loopback peer"
    fi
    pass "node environment requires real mainnet bootstrap peers"
}

validate_shielded_verifier() {
    local command_json
    require_exact_env "${NODE_ENV_PATH}" WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS "5"
    require_exact_env "${NODE_ENV_PATH}" WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES "1048576"
    require_exact_env "${NODE_ENV_PATH}" WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT "2"
    command_json="$(env_value "${NODE_ENV_PATH}" WEPO_SHIELDED_VERIFIER_COMMAND_JSON)" \
        || fail "could not read WEPO_SHIELDED_VERIFIER_COMMAND_JSON from ${NODE_ENV_PATH}"
    WEPO_SHIELDED_VERIFIER_COMMAND_JSON="${command_json}" \
        "${PYTHON_BIN}" - "${INSTALL_ROOT}" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

install_root = Path(sys.argv[1])
release_root = install_root.resolve(strict=True)
configured = json.loads(os.environ["WEPO_SHIELDED_VERIFIER_COMMAND_JSON"])
expected_configured = str(install_root / "zk" / "target" / "release" / "ghost_verifier")
if configured != [expected_configured]:
    raise SystemExit("Ghost verifier must be the exact direct release-tree executable")
verifier_path = Path(configured[0])
if verifier_path.is_symlink():
    raise SystemExit("Ghost verifier executable must not be a symlink")
resolved = verifier_path.resolve(strict=True)
if release_root not in resolved.parents:
    raise SystemExit("Ghost verifier executable escapes the signed release tree")
metadata = resolved.stat()
if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
    raise SystemExit("Ghost verifier is not an executable regular file")
if metadata.st_uid != 0 or metadata.st_mode & 0o022:
    raise SystemExit("Ghost verifier must be root-owned and not group/other writable")

core_dir = release_root / "wepo-blockchain" / "core"
sys.path.insert(0, str(core_dir))
import shielded_verifier

if shielded_verifier.SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED is not True:
    raise SystemExit("Ghost verifier independent release audit is not approved in source")
expected_sha256 = shielded_verifier.SHIELDED_VERIFIER_RELEASE_SHA256
if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
    raise SystemExit("Ghost verifier audited SHA-256 is not frozen in source")
actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
if actual_sha256 != expected_sha256:
    raise SystemExit("installed Ghost verifier does not match the audited SHA-256")
PY
    pass "mandatory Ghost verifier is direct, immutable, audited, and hash-bound"
}

validate_release_tree() {
    local release_root
    require_regular_file "${RELEASE_MANIFEST_PATH}"
    require_regular_file "${RELEASE_MANIFEST_SIGNATURE_PATH}"
    require_regular_file "${RELEASE_SIGNING_PUBLIC_KEY_PATH}"
    release_root="$(readlink -f "${INSTALL_ROOT}")"
    [[ -d "${release_root}" ]] || fail "release root does not resolve to a directory"
    [[ "$(stat -c '%U' "${release_root}")" == "root" ]] || fail "resolved release root must be root-owned"
    if find "${release_root}" -xdev \( -type f -o -type d \) \( -perm -0020 -o -perm -0002 \) -print -quit | grep -q .; then
        fail "release tree contains group/world-writable content"
    fi
    openssl dgst -sha256 -verify "${RELEASE_SIGNING_PUBLIC_KEY_PATH}" -signature "${RELEASE_MANIFEST_SIGNATURE_PATH}" "${RELEASE_MANIFEST_PATH}" >/dev/null || fail "release-manifest signature verification failed"
    (
        cd "${release_root}"
        sha256sum --strict --check "${RELEASE_MANIFEST_PATH}"
    ) >/dev/null || fail "release manifest verification failed"
    pass "resolved immutable release tree matches the signed SHA256SUMS"
}

validate_mainnet_release_gate() {
    if [[ "${EXPECTED_NETWORK}" != "mainnet" ]]; then
        pass "mainnet release decision gate is not applicable to ${EXPECTED_NETWORK}"
        return
    fi
    WEPO_RELEASE_ROOT="${INSTALL_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys

release_root = os.path.realpath(os.environ["WEPO_RELEASE_ROOT"])
core_dir = os.path.join(release_root, "wepo-blockchain", "core")
if not os.path.isdir(core_dir):
    raise SystemExit(f"release tree lacks blockchain core: {core_dir}")
sys.path.insert(0, core_dir)

from network_profile import (  # noqa: E402
    get_network_profile,
    mainnet_release_blockers,
)

profile = get_network_profile("mainnet")
blockers = mainnet_release_blockers(profile)
if blockers:
    raise SystemExit(
        "mainnet release decision gate is closed: " + ", ".join(blockers)
    )
PY
    pass "signed release tree contains a complete mainnet decision set"
}

validate_systemd_service() {
    local service="$1"
    local expected_user="$2"
    local actual_user
    systemctl is-enabled "${service}" >/dev/null 2>&1 || fail "${service} is not enabled"
    systemctl is-active "${service}" >/dev/null 2>&1 || fail "${service} is not active"
    actual_user="$(systemctl show "${service}" --property=User --value)"
    [[ "${actual_user}" == "${expected_user}" ]] || fail "${service} must run as ${expected_user}"
    systemctl show "${service}" --property=NoNewPrivileges --value | grep -qx yes || fail "${service} lacks NoNewPrivileges"
}

validate_node_resource_controls() {
    local property value
    for property in MemoryHigh MemoryMax TasksMax CPUQuotaPerSecUSec; do
        value="$(systemctl show "${NODE_SERVICE_NAME}" --property="${property}" --value)"
        [[ -n "${value}" && "${value}" != "infinity" ]] || fail "${NODE_SERVICE_NAME} lacks finite ${property}"
    done
    [[ "$(systemctl show "${NODE_SERVICE_NAME}" --property=TasksMax --value)" =~ ^[0-9]+$ ]] || fail "${NODE_SERVICE_NAME} TasksMax is not numeric"
    (( $(systemctl show "${NODE_SERVICE_NAME}" --property=TasksMax --value) <= 128 )) || fail "${NODE_SERVICE_NAME} TasksMax exceeds 128"
    pass "node and verifier child process tree has finite CPU, memory, and task ceilings"
}

validate_systemd() {
    validate_systemd_service "${NODE_SERVICE_NAME}" wepo-node
    validate_systemd_service "${BACKEND_SERVICE_NAME}" wepo-api
    validate_node_resource_controls
    [[ "$(getent passwd wepo-node | cut -d: -f7)" == "/usr/sbin/nologin" ]] || fail "wepo-node must have a locked shell"
    [[ "$(getent passwd wepo-api | cut -d: -f7)" == "/usr/sbin/nologin" ]] || fail "wepo-api must have a locked shell"
    pass "node and API run as distinct locked identities"
}

validate_nginx_and_tls() {
    local rendered headers
    require_regular_file "${NGINX_SITE_PATH}"
    require_private_file "${TLS_KEY_PATH}"
    require_regular_file "${TLS_CERT_PATH}"
    [[ -n "${PUBLIC_API_HOST}" ]] || fail "PUBLIC_API_HOST is required"
    [[ "${PUBLIC_API_HOST}" != *example.invalid* ]] || fail "PUBLIC_API_HOST is a placeholder"
    nginx -t >/dev/null 2>&1 || fail "nginx configuration test failed"
    rendered="$(nginx -T 2>/dev/null)"
    for marker in 'ssl_protocols TLSv1.2 TLSv1.3' 'client_max_body_size 2m' 'Strict-Transport-Security' 'limit_req zone=wepo_api_per_ip' 'proxy_set_header X-Real-IP $remote_addr' 'proxy_set_header X-Forwarded-For $remote_addr'; do
        grep -Fq "${marker}" <<<"${rendered}" || fail "nginx is missing: ${marker}"
    done
    grep -Fq 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for' <<<"${rendered}" && fail "nginx appends attacker-supplied X-Forwarded-For"
    openssl x509 -checkend "${CERT_MIN_SECONDS}" -noout -in "${TLS_CERT_PATH}" >/dev/null || fail "TLS certificate expires too soon"
    headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null --proto '=https' --tlsv1.2 --max-time 10 "https://${PUBLIC_API_HOST}/healthz")" || fail "public HTTPS health request failed"
    grep -Eiq '^strict-transport-security:' <<<"${headers}" || fail "public response lacks HSTS"
    grep -Eiq '^x-content-type-options:[[:space:]]*nosniff' <<<"${headers}" || fail "public response lacks nosniff"
    pass "public TLS, proxy overwrite, limits, and headers verified"
}

validate_listeners() {
    local listeners
    listeners="$(ss -H -ltn)"
    WEPO_LISTENERS="${listeners}" "${PYTHON_BIN}" - <<'PY'
import os

lines = os.environ["WEPO_LISTENERS"].splitlines()

def addresses(port):
    suffix = f":{port}"
    return [line.split()[3] for line in lines if len(line.split()) >= 4 and line.split()[3].endswith(suffix)]

for port in (8011, 8122):
    found = addresses(port)
    if not found:
        raise SystemExit(f"port {port} is not listening")
    if any(not (item.startswith("127.0.0.1:") or item.startswith("[::1]:")) for item in found):
        raise SystemExit(f"port {port} is exposed beyond loopback: {found}")
p2p = addresses(22567)
if not p2p or all(item.startswith("127.0.0.1:") or item.startswith("[::1]:") for item in p2p):
    raise SystemExit("P2P port 22567 is not bound for external reachability")
for port in (6379, 27017):
    found = addresses(port)
    if any(item.startswith("0.0.0.0:") or item.startswith("[::]:") or item.startswith("*:") for item in found):
        raise SystemExit(f"datastore port {port} has a wildcard listener: {found}")
PY
    pass "API listeners are loopback-only and P2P is externally bound"
}

validate_dependencies_and_status() {
    REDIS_URL="$(env_value "${BACKEND_ENV_PATH}" REDIS_URL)" "${PYTHON_BIN}" - <<'PY'
import os
from redis import Redis

client = Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=5, socket_timeout=5)
if not client.ping():
    raise SystemExit("Redis ping returned false")
PY
    "${PYTHON_BIN}" "${INSTALL_ROOT}/tests/test_redis_rate_limit_fail_closed.py" >/dev/null || fail "runtime Redis fail-closed regression failed from release tree"
    NODE_STATUS_URL="http://127.0.0.1:8122/api/network/status" EXPECTED_NETWORK="${EXPECTED_NETWORK}" "${PYTHON_BIN}" - <<'PY'
import json
import os
from urllib.request import urlopen

with urlopen(os.environ["NODE_STATUS_URL"], timeout=5) as response:
    status = json.load(response)
if status.get("network_profile") != os.environ["EXPECTED_NETWORK"]:
    raise SystemExit("node reports the wrong network profile")
for key in ("chain_height", "latest_block_hash", "peers", "mempool_size", "mempool_bytes"):
    if key not in status:
        raise SystemExit(f"node status lacks {key}")
operational = status.get("operational")
if not isinstance(operational, dict) or operational.get("scope") != "process":
    raise SystemExit("node status lacks process-scoped operational metrics")
for key in ("p2p_block_rejections_total", "p2p_transaction_rejections_total"):
    if type(operational.get(key)) is not int or operational[key] < 0:
        raise SystemExit(f"node operational metrics lack {key}")
consensus = operational.get("consensus")
p2p = operational.get("p2p")
for key in ("block_validation_rejections_total", "reorgs_total", "reorg_failures_total"):
    if not isinstance(consensus, dict) or type(consensus.get(key)) is not int:
        raise SystemExit(f"consensus operational metrics lack {key}")
for key in ("misbehavior_events_total", "connection_failures_total", "banned_hosts_active"):
    if not isinstance(p2p, dict) or type(p2p.get(key)) is not int:
        raise SystemExit(f"P2P operational metrics lack {key}")
PY
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8011/api/ >/dev/null || fail "backend loopback health failed"
    pass "Redis, fail-closed regression, node status, and backend health verified"
}

require_root
for command in stat find grep sha256sum readlink systemctl getent nginx openssl curl ss; do
    require_command "${command}"
done
[[ -x "${PYTHON_BIN}" ]] || fail "Python runtime is missing: ${PYTHON_BIN}"

validate_backend_env
validate_node_env
validate_shielded_verifier
validate_release_tree
validate_mainnet_release_gate
validate_systemd
validate_nginx_and_tls
validate_listeners
validate_dependencies_and_status

pass "production host contract verified read-only; no service or file was mutated"
