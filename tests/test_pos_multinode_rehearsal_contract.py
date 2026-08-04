"""Safety and evidence contract for the local hybrid PoW/PoS rehearsal."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wepo-blockchain" / "scripts" / "wepo_pos_multinode_rehearsal.py"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_pos_rehearsal_is_parseable_and_explicitly_test_only():
    content = source()
    ast.parse(content, filename=str(SCRIPT))

    assert '"--network-profile",\n            "test"' in content
    assert '"WEPO_NETWORK_PROFILE": "test"' in content
    assert '"WEPO_DNS_SEEDS": "off"' in content
    assert '"WEPO_REQUIRE_MAINNET_SEEDS": "0"' in content
    assert '"WEPO_TEST_PRE_POS_BLOCKS": "2"' in content
    assert '"network_profile": "test"' in content
    assert '"test_only": True' in content
    assert '"mainnet_mutated": False' in content
    assert "MAINNET_GENESIS_FINALIZED" not in content


def test_pos_rehearsal_uses_real_signer_and_retains_no_private_key():
    content = source()

    assert "wepo_validator_signer.py" in content
    assert "WEPO_VALIDATOR_SIGNER_COMMAND_JSON" in content
    assert '"--state-db"' in content
    assert '"--stdio"' in content
    assert '"--allow-insecure-permissions-for-test"' in content
    assert "submit_signed_stake" in content
    assert "Transaction.from_dict" in content
    assert "sign_all_inputs" not in content
    assert '"--authorize-stake-request"' in content
    assert "sign_stake_transaction" in content
    assert '"controller_loaded_private_key": False' in content
    assert '"private_key_loaded_by_controller": False' in content
    assert '"private_key_retained": workspace_retained' in content
    assert "create_workspace_marker(workspace)" in content
    assert "remove_workspace_verified(workspace)" in content
    assert '"workspace_cleanup_verified": workspace_cleanup_verified' in content
    assert '"workspace_retained": workspace_retained' in content
    assert "Retained evidence cannot be combined with private test artifacts" in content
    assert '"private_key_in_evidence": False' in content
    assert '"private_key": key.private_key' not in content
    assert "read_signer_rows" in content
    assert "distinct_height_constraint_verified" in content
    assert "rolled_back_authorization_retained" in content
    assert "continued_above_retained_height" in content


def test_pos_rehearsal_covers_partition_reorg_restart_and_evidence_integrity():
    content = source()

    assert "node_count\": 3" in content
    assert "partitioned signer-produced PoS block" in content
    assert "stronger PoW branch adoption after rejoin" in content
    assert content.count("with closing(sqlite3.connect(path)) as connection:") == 4
    assert "def semantic_database_sha256" in content
    assert '"semantic_sha256": semantic_database_sha256(database)' in content
    assert '"semantic_state_equal": True' in content
    assert "Final node databases differ semantically" in content
    assert "from contextlib import closing" in content
    assert "evidence_path.parent.mkdir(parents=True, exist_ok=True)" in content
    assert "Signer-produced partition block remained canonical" in content
    assert "post-reorg signer continuation" in content
    assert "node_a.restart" in content
    assert "PRAGMA quick_check" in content
    assert "database_sha256" in content
    assert "script_sha256" in content
    assert "vector_sha256" in content
    assert "os.O_EXCL" in content
    assert "Refusing to overwrite evidence file" in content
    assert "retain_logs" in content
