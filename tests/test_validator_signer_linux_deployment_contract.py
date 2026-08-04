from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "wepo-production-deployment"


def text(name: str) -> str:
    return (DEPLOYMENT / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def bash_syntax(source: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-n"],
        input=source.replace("\r", "").encode("utf-8"),
        capture_output=True,
        timeout=30,
    )


def test_validator_signer_deployment_scripts_have_valid_bash_syntax():
    for name in ("install-validator-signer.sh", "verify-validator-signer-host.sh"):
        result = bash_syntax(text(name))
        assert result.returncode == 0, result.stderr.decode("utf-8")


def test_installer_enforces_separate_users_immutable_runtime_and_mainnet_gate():
    script = text("install-validator-signer.sh")
    assert 'MAINNET_SIGNER_QUALIFICATION_ONLY="${MAINNET_SIGNER_QUALIFICATION_ONLY:-0}"' in script
    assert 'systemctl is-active --quiet "${NODE_SERVICE_NAME}"' in script
    assert "qualification requires the node service to remain inactive" in script
    assert script.index("mainnet_release_blockers") < script.index('ensure_group "${NODE_GROUP}"')

    assert 'NODE_USER="${NODE_USER:-wepo-node}"' in script
    assert 'SIGNER_USER="${SIGNER_USER:-wepo-signer}"' in script
    assert '[[ "${NODE_USER}" != "${SIGNER_USER}" ]]' in script
    assert '"${NETWORK_PROFILE}" == "test" || "${NETWORK_PROFILE}" == "mainnet"' in script
    assert "mainnet_release_blockers" in script
    assert "frozen mainnet parameter gate clears" in script
    assert 'NETWORK_PROFILE="${NETWORK_PROFILE:-test}"' in script
    assert '[[ "$(stat -c \'%u\' "${path}")"' not in script  # guard brittle duplicate checks
    assert 'owner="$(stat -c \'%u\' "${path}")"' in script
    assert "8#022" in script
    assert 'require_immutable_file "${SIGNER_SCRIPT}"' in script
    assert 'require_immutable_file "${RELEASE_ROOT}/wepo-blockchain/core/dilithium.py"' in script
    assert "--allow-insecure-permissions-for-test" not in script
    assert 'NODE_DATA_DIR="${NODE_DATA_DIR:-/var/lib/wepo/node}"' in script
    assert 'install -d -m 0750 -o "${NODE_USER}" -g "${NODE_GROUP}" "${NODE_DATA_DIR}"' in script


def test_installer_generates_exact_sudo_and_systemd_namespace_contract():
    script = text("install-validator-signer.sh")

    assert '"/usr/bin/sudo", "-n", "-u", sys.argv[1], "--"' in script
    assert 'NOPASSWD:NOEXEC:' in script
    assert 'visudo -cf "${SUDOERS_PATH}.tmp"' in script
    assert "NoNewPrivileges=false" in script
    assert "ReadWritePaths=${SIGNER_HOME}/state" in script
    assert 'EnvironmentFile=${ENV_PATH}' in script
    assert "WEPO_VALIDATOR_SIGNER_COMMAND_JSON" in script
    assert "WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS=15" in script

    assert '"${NETWORK_PROFILE}" == "test" || "${NETWORK_PROFILE}" == "mainnet"' in script
    assert "mainnet_release_blockers" in script
    assert "frozen mainnet parameter gate clears" in script


def test_mainnet_signer_gate_runs_before_installer_mutation():
    script = text("install-validator-signer.sh")
    assert script.index("mainnet_release_blockers") < script.index('ensure_group "${NODE_GROUP}"')

def test_host_verifier_proves_permissions_denials_and_database_integrity():
    script = text("verify-validator-signer-host.sh")

    assert 'MAINNET_SIGNER_QUALIFICATION_ONLY="${MAINNET_SIGNER_QUALIFICATION_ONLY:-0}"' in script
    assert 'systemctl is-active --quiet "${NODE_SERVICE_NAME}"' in script
    assert "qualification requires the node service to remain inactive" in script
    required = [
        'test ! -r "${KEY_FILE}"',
        'test ! -w "${KEY_FILE}"',
        'test ! -x "$(dirname "${KEY_FILE}")"',
        'test ! -w "${SIGNER_SCRIPT}"',
        'sudo -n -u "${SIGNER_USER}" -- /bin/true',
        "--allow-insecure-permissions-for-test",
        'PRAGMA quick_check',
        'anti-equivocation database quick_check failed',
    ]
    for marker in required:
        assert marker in script
    assert script.index('sudo -n -u "${SIGNER_USER}" -- /bin/true') < script.index(
        'unapproved command as signer'
    )


def test_rehearsal_is_pinned_ephemeral_offline_and_fail_if_present():
    dockerfile = text("validator-signer-linux-rehearsal.Dockerfile")
    container = text("validator-signer-linux-rehearsal.sh")
    runner = text("run_validator_signer_linux_rehearsal.py")
    client = text("validator_signer_rehearsal_client.py")

    assert "python:3.11-slim@sha256:" in dockerfile
    assert "dilithium-py==1.1.0" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "0bd29e80bad7ed6700984708ca2798a318e3a8bd404f2a5c8d08cc9eceafd5a5" in dockerfile
    assert "sudo=1.9.16p2-3+deb13u2" in dockerfile
    assert '"--network", "none"' in runner
    assert '"--rm"' in runner
    assert "dst=/workspace,readonly" in runner
    assert "os.O_EXCL" in runner
    assert "refusing to retain private key material" in runner
    assert "ephemeral rehearsal container was not removed" in runner
    assert "corrupt_state_failed_closed" in container
    assert "mainnet_install_refused_before_mutation" in container
    assert "unsupported_profile_refused_before_mutation" in container
    assert "complete_safety_unit_restored" in container
    assert "host_fencing_not_exercised" in container
    assert "off_host_encrypted_backup_not_exercised" in container
    assert "anti-equivocation refusal" in client
    assert "idempotent retry returned a different signature" in client
    assert '"private_key":' not in client


def test_canonical_staging_verifier_defines_redis_check_before_calling_it():
    script = text("verify-canonical-staging-host.sh")

    assert script.index("check_redis() {") < script.index("run_release_gate() {")
    call_site = script.rindex("load_backend_env")
    assert call_site < script.rindex("validate_backend_env") < script.rindex("check_redis")

    bootstrap = text("bootstrap-canonical-staging.sh")
    assert 'install -d -m 0755 -o root -g root "${INSTALL_ROOT}"' in bootstrap
    assert 'install -d -m 0755 -o "${WEPO_USER}" -g "${WEPO_GROUP}" "${INSTALL_ROOT}"' not in bootstrap
    staging_unit = text("wepo-node-staging.service.example")
    assert "wepo-node-staging.service.example" in bootstrap
    assert '"${SCRIPT_DIR}/wepo-node.service.example"' not in bootstrap
    assert "WEPO_NETWORK_PROFILE=test" in staging_unit
    assert "WEPO_REQUIRE_MAINNET_SEEDS=0" in staging_unit
    assert "--network-profile test" in staging_unit
    assert "--difficulty-override 1" in staging_unit
    assert "--no-background-mining" in staging_unit
    assert "--network-profile mainnet" not in staging_unit
    assert 'document.get("network_profile") != "test"' in script
    assert "check_node_profile" in script
