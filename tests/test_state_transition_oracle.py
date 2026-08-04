"""Cross-runtime contract tests for the independent Node state oracle."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))
import rescue_reference as R  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "vectors" / "state_transition_oracle_v1.json"
GENERATOR = ROOT / "tests" / "generate_state_transition_fixture.py"
ORACLE = ROOT / "tests" / "state_transition_oracle.mjs"


def _canonical_fixture_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _run_oracle(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(ORACLE), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _write_fixture(path: Path, fixture: dict) -> None:
    path.write_text(
        json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _reference_empty_roots(depth: int, empty_leaf_domain: int, node_domain: int):
    roots = [R.field_hash(empty_leaf_domain, [])]
    for _ in range(depth):
        child_elements = (
            R.bytes_to_field_elements(roots[-1])
            + R.bytes_to_field_elements(roots[-1])
        )
        roots.append(R.field_hash(node_domain, child_elements))
    return roots


def _reference_tree_roots(commitments: list[str], parameters: dict) -> list[str]:
    depth = parameters["merkle_depth"]
    empty_roots = _reference_empty_roots(
        depth,
        parameters["empty_leaf_domain"],
        parameters["node_hash_domain"],
    )
    nodes = [dict() for _ in range(depth + 1)]
    roots = []
    for position, commitment_hex in enumerate(commitments):
        value = bytes.fromhex(commitment_hex)
        R.bytes_to_field_elements(value)
        nodes[0][position] = value
        index = position
        for level in range(depth):
            parent = index >> 1
            left_index = parent << 1
            left = nodes[level].get(left_index, empty_roots[level])
            right = nodes[level].get(
                left_index + 1,
                empty_roots[level],
            )
            nodes[level + 1][parent] = R.field_hash(
                parameters["node_hash_domain"],
                R.bytes_to_field_elements(left)
                + R.bytes_to_field_elements(right),
            )
            index = parent
        roots.append(nodes[depth][0].hex())
    return roots


def _reference_bundle_statement_digest(
    bundle: dict,
    sighash_hex: str,
    parameters: dict,
) -> str:
    empty_root = _reference_empty_roots(
        parameters["merkle_depth"],
        parameters["empty_leaf_domain"],
        parameters["node_hash_domain"],
    )[-1]
    spends = bundle["spends"]
    outputs = bundle["outputs"]
    anchor = (
        bytes.fromhex(spends[0]["anchor"])
        if spends
        else empty_root
    )
    parts = [
        parameters["bundle_statement_tag"].encode("ascii"),
        anchor,
        struct.pack("<I", len(spends)),
        b"".join(bytes.fromhex(spend["nullifier"]) for spend in spends),
        struct.pack("<I", len(outputs)),
        b"".join(bytes.fromhex(output["commitment"]) for output in outputs),
        struct.pack("<q", bundle["value_balance"]),
        bytes.fromhex(sighash_hex),
    ]
    payload = b"".join(struct.pack("<I", len(part)) + part for part in parts)
    return R.pool_hash(payload).hex()


def _validate_shielded_rescue_reference(scenario: dict) -> dict:
    R.self_check()
    parameters = scenario["parameters"]
    expected = scenario["expected"]
    shielded_transactions = [
        (block["height"], transaction)
        for block in scenario["blocks"]
        for transaction in block["transactions"][1:]
        if transaction["shielded_bundle"] is not None
    ]
    commitments = [
        output["commitment"]
        for _, transaction in shielded_transactions
        for output in transaction["shielded_bundle"]["outputs"]
    ]
    roots = _reference_tree_roots(commitments, parameters)
    expected_anchors = expected["anchors"]
    assert [row["anchor"] for row in expected_anchors] == roots
    assert expected["tree_root"] == roots[-1]
    assert expected["disconnect"]["tree_root"] == roots[0]

    digests = [
        _reference_bundle_statement_digest(
            transaction["shielded_bundle"],
            sighash,
            parameters,
        )
        for (_, transaction), sighash in zip(
            shielded_transactions,
            expected["sighashes"],
            strict=True,
        )
    ]
    assert digests == expected["statement_digests"]
    return {
        "roots": roots,
        "statement_digests": digests,
    }


def test_committed_fixture_replays_to_exact_independent_state():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema"] == "wepo-state-transition-oracle-v1"
    assert fixture["test_only"] is True
    assert fixture["expected"]["height"] == 3
    assert len(fixture["blocks"]) == 4
    assert (
        "canonical signed masternode registration and deactivation"
        in fixture["coverage"]["covered"]
    )
    assert (
        "masternode lifecycle and reward indexes" not in fixture["coverage"]["not_covered"]
    )
    assert (
        "RWA asset uniqueness, ownership, and derived indexes"
        in fixture["coverage"]["covered"]
    )
    assert (
        "RWA and messaging-key indexes" not in fixture["coverage"]["not_covered"]
    )
    assert (
        "RWA and messaging-key disconnect/reconnect "
        "under cumulative-work reorganization"
        in fixture["coverage"]["covered"]
    )
    assert (
        "shielded commitments, anchors, nullifiers, "
        "and transparent-pool supply reconciliation"
        in fixture["coverage"]["covered"]
    )
    assert (
        "shielded disconnect/reconnect and proof-statement digest binding"
        in fixture["coverage"]["covered"]
    )
    assert fixture["coverage"]["not_covered"] == [
        "external cryptographic audit of the real shielded prover and verifier"
    ]
    fork = fixture["fork_choice"]
    slow, fast = fork["branches"]
    assert slow["name"] == "long_slow_difficulty_1"
    assert slow["expected"]["height"] == 15
    assert slow["expected"]["score"]["pow_work"] == "256"
    assert fast["name"] == "short_fast_retargeted"
    assert fast["expected"]["height"] == 10
    assert fast["expected"]["score"]["pow_work"] == "416"
    assert [block["header"]["bits"] for block in fast["blocks"][1:]] == (
        [1] * 9 + [2]
    )
    assert slow["expected"]["rwa_assets"][0]["asset_id"] == "rwa_losing_branch"
    assert fast["expected"]["rwa_assets"][0]["asset_id"] == "rwa_winning_branch"
    assert (
        slow["expected"]["messaging_keys"][0]["register_txid"]
        != fast["expected"]["messaging_keys"][0]["register_txid"]
    )
    assert fast["expected"]["tip"] == (
        "ba09a23b0fc47db9768d529ba15411209c46e0400b0d1da4ad0ebf50bb13c95f"
    )
    assert fast["expected"]["messaging_keys"][0]["register_txid"] == (
        "f7051ac107aa4cc1fee81dc04dccc2acf45d5ec20f33b093ebac67e75c910e7a"
    )
    assert fork["expected"]["winner"] == fast["name"]
    assert fork["expected"]["canonical_rwa_assets"] == fast["expected"]["rwa_assets"]
    assert (
        fork["expected"]["canonical_messaging_keys"]
        == fast["expected"]["messaging_keys"]
    )
    assert fork["expected"]["losing_rwa_assets_removed"] is True
    assert fork["expected"]["winning_rwa_assets_present"] is True
    assert fork["expected"]["losing_messaging_keys_replaced"] is True
    assert fork["expected"]["winning_messaging_keys_selected"] is True
    assert fork["expected"]["losing_tip_preserved_noncanonical"] is True
    pos = fixture["pos_scenario"]
    assert pos["parent"]["expected"]["height"] == 14
    assert len(pos["active_stakes"]) == 1
    assert pos["active_stakes"][0]["amount"] == 100 * 100_000_000
    assert pos["expected"]["selected_validator"] == pos["active_stakes"][0]["staker_address"]
    assert pos["expected"]["candidate_height"] == 15
    assert len(pos["expected"]["validator_signature"]) == 2420 * 2
    assert pos["expected"]["candidate_hash"] == (
        "39ffadc1682e15784e813c1951d6706b2de2fad6dd444e15095e04f289bee6e9"
    )
    assert len(pos["continuation_blocks"]) == 8
    registered = pos["active_masternodes_after_registration"]
    assert len(registered) == 1
    assert registered[0]["status"] == "active"
    assert registered[0]["total_rewards"] == 0

    lifecycle = pos["expected_final"]
    assert lifecycle["height"] == 23
    assert lifecycle["tip"] == (
        "a4d1ab4211aa12f17d56287fc5d56cbe365fd64aef8e63b695dbdc7bc799059a"
    )
    assert lifecycle["stakes"][0]["status"] == "inactive"
    assert lifecycle["stakes"][0]["unlock_height"] == 19
    assert lifecycle["stakes"][0]["last_reward_height"] == 18
    assert lifecycle["stakes"][0]["total_rewards"] == 45 * 100_000_000
    assert lifecycle["masternodes"][0]["status"] == "inactive"
    assert lifecycle["masternodes"][0]["total_rewards"] == 5 * 100_000_000
    assert lifecycle["stake_rewards"] == 45 * 100_000_000
    assert lifecycle["masternode_rewards"] == 5 * 100_000_000
    assert lifecycle["total_pos_rewards"] == 50 * 100_000_000
    assert len(lifecycle["rewards"]) == 5
    assert lifecycle["masternode_id"] == (
        "mn_wepo1q26e5e12b5a553b16d0a93e21b4f247cdf204cd2_1700000236"
    )
    assert lifecycle["masternode_registration_txid"] == (
        "dde007ae88c18028f7fbc869db13f00dcc35429d9a2efb4967f15703e3663ca7"
    )
    assert lifecycle["stake_deactivation_txid"] == (
        "f89b560b5e884aee3835803c9148d57ff79b46261614e41a3aabddb3a6d9a617"
    )
    assert lifecycle["masternode_deactivation_txid"] == (
        "de4c1850d0d7dad9d0838e5ce3cb52dd3b7bf9f3ed13854c7a7bec69d04b7ffd"
    )
    assert lifecycle["state_commitment"] == (
        "3d3e07b1a94cc2776b8e4ba31adc2600e0557a645e0d3081bd28490fd1d767af"
    )
    assert len(lifecycle["rwa_assets"]) == 1
    assert lifecycle["rwa_assets"][0]["asset_id"] == "rwa_state_oracle_001"
    assert lifecycle["rwa_assets"][0]["create_height"] == 21
    assert lifecycle["rwa_create_txid"] == (
        "ffcd34ec0578a242cb454a24a848d01ba1537b4537ea7fa41d252bbefd59478f"
    )
    assert len(lifecycle["messaging_keys"]) == 1
    assert lifecycle["messaging_keys"][0]["register_height"] == 23
    assert lifecycle["messaging_registration_txids"] == [
        "b21caa5698dcae7f44d698d78dfbddcfd8c044fe53e477fd77ac2affac2c0008",
        "a58b0c441b945ef2e1df29ae13c823b11ef773014c357e8a83b8490f406062fe",
    ]
    assert lifecycle["messaging_keys"][0]["register_txid"] == (
        lifecycle["messaging_registration_txids"][-1]
    )
    assert lifecycle["metadata_fee_total"] == 30_000
    assert lifecycle["metadata_fee_redistributed_total"] == 30_000
    assert lifecycle["supply_minus_utxo_total"] == 0

    shielded = fixture["shielded_scenario"]
    shielded_expected = shielded["expected"]
    assert shielded_expected["height"] == 2
    assert shielded_expected["tip"] == (
        "2d9eff2ad2c9a0dc3aed2367a29f378c0c8b886dbf8cc145ce5e00af1cfcf01e"
    )
    assert shielded_expected["shielded_pool_balance"] == 5 * 100_000_000
    assert shielded_expected["supply_minus_transparent_utxo_total"] == (
        shielded_expected["shielded_pool_balance"]
    )
    assert len(shielded_expected["commitments"]) == 2
    assert len(shielded_expected["nullifiers"]) == 1
    assert shielded_expected["tree_root"] == (
        "f94d7acc96668781c2d6acb9fc76e257df44c8be486dba5a0d9772d99eef69c4"
    )
    assert shielded_expected["transaction_ids"] == [
        "b635e1441761d932f0acd3149f751c347fb43905234fd81aa78097a9583a8a10",
        "120aca68395edd579681a5fc7e0a7f47292b80617fbcd4795a7491a04fe49db6",
    ]
    assert shielded_expected["reconnect_restored_exact_state"] is True
    reference_result = _validate_shielded_rescue_reference(shielded)
    assert reference_result["roots"][-1] == shielded_expected["tree_root"]
    assert reference_result["statement_digests"] == (
        shielded_expected["statement_digests"]
    )

    result = _run_oracle(FIXTURE)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    actual = json.loads(result.stdout)

    assert actual == {
        "status": "pass",
        "height": fixture["expected"]["height"],
        "tip": fixture["expected"]["tip"],
        "issued_supply": fixture["expected"]["issued_supply"],
        "utxo_count": len(fixture["expected"]["utxos"]),
        "state_commitment": fixture["expected"]["state_commitment"],
        "fork_winner": fork["expected"]["winner"],
        "fork_height": fork["expected"]["canonical_height"],
        "fork_tip": fork["expected"]["canonical_tip"],
        "fork_pow_work": fast["expected"]["score"]["pow_work"],
        "fork_rwa_asset_id": fast["expected"]["rwa_assets"][0]["asset_id"],
        "fork_messaging_key_txid": fast["expected"]["messaging_keys"][0][
            "register_txid"
        ],
        "fork_metadata_fee_total": 20_000,
        "fork_metadata_fee_redistributed_total": 20_000,
        "shielded_height": shielded_expected["height"],
        "shielded_tip": shielded_expected["tip"],
        "shielded_tree_root": shielded_expected["tree_root"],
        "shielded_pool_balance": shielded_expected["shielded_pool_balance"],
        "shielded_commitment_count": len(shielded_expected["commitments"]),
        "shielded_nullifier_count": len(shielded_expected["nullifiers"]),
        "shielded_transaction_ids": shielded_expected["transaction_ids"],
        "shielded_sighashes": shielded_expected["sighashes"],
        "shielded_statement_digests": shielded_expected["statement_digests"],
        "pos_validator": pos["expected"]["selected_validator"],
        "pos_height": pos["expected"]["candidate_height"],
        "pos_tip": pos["expected"]["candidate_hash"],
        "pos_signing_message": pos["expected"]["signing_message_hex"],
        "lifecycle_height": lifecycle["height"],
        "lifecycle_tip": lifecycle["tip"],
        "lifecycle_state_commitment": lifecycle["state_commitment"],
        "lifecycle_pos_rewards": lifecycle["total_pos_rewards"],
        "lifecycle_stake_rewards": lifecycle["stake_rewards"],
        "lifecycle_masternode_rewards": lifecycle["masternode_rewards"],
        "stake_deactivation_txid": lifecycle["stake_deactivation_txid"],
        "masternode_id": lifecycle["masternode_id"],
        "masternode_registration_txid": lifecycle["masternode_registration_txid"],
        "rwa_asset_id": lifecycle["rwa_assets"][0]["asset_id"],
        "rwa_create_txid": lifecycle["rwa_create_txid"],
        "messaging_latest_txid": lifecycle["messaging_keys"][0]["register_txid"],
        "messaging_registration_txids": lifecycle[
            "messaging_registration_txids"
        ],
        "metadata_fee_total": lifecycle["metadata_fee_total"],
        "metadata_fee_redistributed_total": lifecycle[
            "metadata_fee_redistributed_total"
        ],
        "supply_minus_utxo_total": lifecycle["supply_minus_utxo_total"],
        "masternode_deactivation_txid": lifecycle["masternode_deactivation_txid"],
    }


def test_fixture_generator_is_byte_reproducible(tmp_path):
    regenerated = tmp_path / "state-transition.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--output",
            str(regenerated),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert _canonical_fixture_bytes(regenerated) == _canonical_fixture_bytes(FIXTURE)

    oracle_result = _run_oracle(regenerated)
    assert oracle_result.returncode == 0, (
        oracle_result.stdout + "\n" + oracle_result.stderr
    )


def test_oracle_rejects_transaction_and_state_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    signature_tamper = copy.deepcopy(original)
    transaction = signature_tamper["blocks"][2]["transactions"][1]
    signature = transaction["inputs"][0]["quantum_signature"]
    transaction["inputs"][0]["quantum_signature"] = (
        ("00" if signature[:2] != "00" else "01") + signature[2:]
    )
    signature_path = tmp_path / "signature-tamper.json"
    _write_fixture(signature_path, signature_tamper)
    signature_result = _run_oracle(signature_path)
    assert signature_result.returncode != 0

    maturity_tamper = copy.deepcopy(original)
    maturity_tamper["coinbase_maturity"] = 3
    maturity_path = tmp_path / "maturity-tamper.json"
    _write_fixture(maturity_path, maturity_tamper)
    maturity_result = _run_oracle(maturity_path)
    assert maturity_result.returncode != 0
    assert "immature coinbase" in maturity_result.stderr

    state_tamper = copy.deepcopy(original)
    state_tamper["expected"]["utxos"][0]["amount"] += 1
    state_path = tmp_path / "state-tamper.json"
    _write_fixture(state_path, state_tamper)
    state_result = _run_oracle(state_path)
    assert state_result.returncode != 0
    assert "UTXO set mismatch" in state_result.stderr


def test_oracle_rejects_pow_and_difficulty_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    nonce_tamper = copy.deepcopy(original)
    nonce_tamper["blocks"][0]["header"]["nonce"] += 1
    nonce_path = tmp_path / "nonce-tamper.json"
    _write_fixture(nonce_path, nonce_tamper)
    nonce_result = _run_oracle(nonce_path)
    assert nonce_result.returncode != 0
    assert "cross-runtime PoW hash mismatch" in nonce_result.stderr

    parameter_tamper = copy.deepcopy(original)
    parameter_tamper["pow"]["timestamp_bits"] = 32
    parameter_path = tmp_path / "pow-parameter-tamper.json"
    _write_fixture(parameter_path, parameter_tamper)
    parameter_result = _run_oracle(parameter_path)
    assert parameter_result.returncode != 0
    assert "unexpected PoW parameters" in parameter_result.stderr

    difficulty_tamper = copy.deepcopy(original)
    difficulty_tamper["difficulty"]["cases"][0]["expected_next_bits"] += 1
    difficulty_path = tmp_path / "difficulty-tamper.json"
    _write_fixture(difficulty_path, difficulty_tamper)
    difficulty_result = _run_oracle(difficulty_path)
    assert difficulty_result.returncode != 0
    assert "difficulty vector failed" in difficulty_result.stderr

def test_oracle_rejects_fork_choice_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    difficulty_tamper = copy.deepcopy(original)
    winning_branch = difficulty_tamper["fork_choice"]["branches"][1]
    winning_branch["blocks"][10]["header"]["bits"] = 1
    difficulty_path = tmp_path / "fork-live-difficulty-tamper.json"
    _write_fixture(difficulty_path, difficulty_tamper)
    difficulty_result = _run_oracle(difficulty_path)
    assert difficulty_result.returncode != 0
    assert "live difficulty mismatch" in difficulty_result.stderr

    score_tamper = copy.deepcopy(original)
    score_tamper["fork_choice"]["branches"][1]["expected"]["score"][
        "pow_work"
    ] = "417"
    score_path = tmp_path / "fork-score-tamper.json"
    _write_fixture(score_path, score_tamper)
    score_result = _run_oracle(score_path)
    assert score_result.returncode != 0
    assert "branch score mismatch" in score_result.stderr

    winner_tamper = copy.deepcopy(original)
    winner_tamper["fork_choice"]["expected"][
        "winner"
    ] = "long_slow_difficulty_1"
    winner_path = tmp_path / "fork-winner-tamper.json"
    _write_fixture(winner_path, winner_tamper)
    winner_result = _run_oracle(winner_path)
    assert winner_result.returncode != 0
    assert "fork winner mismatch" in winner_result.stderr

    rwa_index_tamper = copy.deepcopy(original)
    rwa_index_tamper["fork_choice"]["expected"]["canonical_rwa_assets"][0][
        "asset_id"
    ] = "forged_winner_asset"
    rwa_index_path = tmp_path / "fork-rwa-index-tamper.json"
    _write_fixture(rwa_index_path, rwa_index_tamper)
    rwa_index_result = _run_oracle(rwa_index_path)
    assert rwa_index_result.returncode != 0
    assert "fork canonical RWA index mismatch" in rwa_index_result.stderr

    messaging_index_tamper = copy.deepcopy(original)
    messaging_index_tamper["fork_choice"]["expected"][
        "canonical_messaging_keys"
    ][0]["register_txid"] = original["fork_choice"]["branches"][0][
        "expected"
    ]["messaging_keys"][0]["register_txid"]
    messaging_index_path = tmp_path / "fork-messaging-index-tamper.json"
    _write_fixture(messaging_index_path, messaging_index_tamper)
    messaging_index_result = _run_oracle(messaging_index_path)
    assert messaging_index_result.returncode != 0
    assert "fork canonical messaging index mismatch" in messaging_index_result.stderr

    reorg_evidence_tamper = copy.deepcopy(original)
    reorg_evidence_tamper["fork_choice"]["expected"][
        "losing_rwa_assets_removed"
    ] = False
    reorg_evidence_path = tmp_path / "fork-reorg-evidence-tamper.json"
    _write_fixture(reorg_evidence_path, reorg_evidence_tamper)
    reorg_evidence_result = _run_oracle(reorg_evidence_path)
    assert reorg_evidence_result.returncode != 0
    assert "Python RWA reorganization evidence is missing" in (
        reorg_evidence_result.stderr
    )


def test_oracle_rejects_pos_candidate_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    stake_tamper = copy.deepcopy(original)
    stake_tamper["pos_scenario"]["active_stakes"][0]["amount"] += 1
    stake_path = tmp_path / "pos-stake-tamper.json"
    _write_fixture(stake_path, stake_tamper)
    stake_result = _run_oracle(stake_path)
    assert stake_result.returncode != 0
    assert "active-stake derivation mismatch" in stake_result.stderr

    slot_tamper = copy.deepcopy(original)
    slot_tamper["pos_scenario"]["candidate"]["header"]["timestamp"] = (
        slot_tamper["pos_scenario"]["expected"]["slot_anchor"]
        + slot_tamper["pos_scenario"]["parameters"]["block_time_pos"]
        - 1
    )
    slot_path = tmp_path / "pos-slot-tamper.json"
    _write_fixture(slot_path, slot_tamper)
    slot_result = _run_oracle(slot_path)
    assert slot_result.returncode != 0
    assert "slot pacing" in slot_result.stderr

    signature_tamper = copy.deepcopy(original)
    signature = signature_tamper["pos_scenario"]["candidate"]["header"][
        "validator_signature"
    ]
    forged_signature = ("00" if signature[:2] != "00" else "01") + signature[2:]
    signature_tamper["pos_scenario"]["candidate"]["header"][
        "validator_signature"
    ] = forged_signature
    signature_tamper["pos_scenario"]["expected"][
        "validator_signature"
    ] = forged_signature
    signature_path = tmp_path / "pos-signature-tamper.json"
    _write_fixture(signature_path, signature_tamper)
    signature_result = _run_oracle(signature_path)
    assert signature_result.returncode != 0
    assert "ML-DSA validator signature is invalid" in signature_result.stderr

    digest_tamper = copy.deepcopy(original)
    digest = digest_tamper["pos_scenario"]["expected"]["signing_message_hex"]
    digest_tamper["pos_scenario"]["expected"]["signing_message_hex"] = (
        ("00" if digest[:2] != "00" else "01") + digest[2:]
    )
    digest_path = tmp_path / "pos-digest-tamper.json"
    _write_fixture(digest_path, digest_tamper)
    digest_result = _run_oracle(digest_path)
    assert digest_result.returncode != 0
    assert "cross-runtime signing digest mismatch" in digest_result.stderr


def test_oracle_rejects_protocol_lifecycle_and_reward_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    stake_status_tamper = copy.deepcopy(original)
    stake_status_tamper["pos_scenario"]["expected_final"]["stakes"][0][
        "status"
    ] = "active"
    stake_status_path = tmp_path / "stake-final-status-tamper.json"
    _write_fixture(stake_status_path, stake_status_tamper)
    stake_status_result = _run_oracle(stake_status_path)
    assert stake_status_result.returncode != 0
    assert "final stake state mismatch" in stake_status_result.stderr

    masternode_status_tamper = copy.deepcopy(original)
    masternode_status_tamper["pos_scenario"]["expected_final"]["masternodes"][0][
        "status"
    ] = "active"
    masternode_status_path = tmp_path / "masternode-final-status-tamper.json"
    _write_fixture(masternode_status_path, masternode_status_tamper)
    masternode_status_result = _run_oracle(masternode_status_path)
    assert masternode_status_result.returncode != 0
    assert "final masternode state mismatch" in masternode_status_result.stderr

    registration_tamper = copy.deepcopy(original)
    registration_tamper["pos_scenario"][
        "active_masternodes_after_registration"
    ][0]["collateral_vout"] += 1
    registration_path = tmp_path / "masternode-registration-state-tamper.json"
    _write_fixture(registration_path, registration_tamper)
    registration_result = _run_oracle(registration_path)
    assert registration_result.returncode != 0
    assert "active-masternode derivation mismatch" in registration_result.stderr

    reward_tamper = copy.deepcopy(original)
    masternode_reward = next(
        reward
        for reward in reward_tamper["pos_scenario"]["expected_final"]["rewards"]
        if reward["recipient_type"] == "masternode"
    )
    masternode_reward["amount"] += 1
    reward_path = tmp_path / "masternode-reward-history-tamper.json"
    _write_fixture(reward_path, reward_tamper)
    reward_result = _run_oracle(reward_path)
    assert reward_result.returncode != 0
    assert "reward history mismatch" in reward_result.stderr

    eligibility_tamper = copy.deepcopy(original)
    forged_reward = copy.deepcopy(
        next(
            reward
            for reward in eligibility_tamper["pos_scenario"]["expected_final"][
                "rewards"
            ]
            if reward["recipient_type"] == "masternode"
        )
    )
    forged_reward["reward_id"] = forged_reward["reward_id"].replace(
        "reward_masternode_18_", "reward_masternode_19_"
    )
    forged_reward["block_height"] = 19
    forged_reward["timestamp"] = eligibility_tamper["pos_scenario"][
        "continuation_blocks"
    ][3]["header"]["timestamp"]
    eligibility_tamper["pos_scenario"]["expected_final"]["rewards"].append(
        forged_reward
    )
    eligibility_path = tmp_path / "protocol-same-block-eligibility-tamper.json"
    _write_fixture(eligibility_path, eligibility_tamper)
    eligibility_result = _run_oracle(eligibility_path)
    assert eligibility_result.returncode != 0
    assert "reward history mismatch" in eligibility_result.stderr


def test_oracle_rejects_metadata_index_and_fee_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    rwa_tamper = copy.deepcopy(original)
    rwa_tamper["pos_scenario"]["expected_final"]["rwa_assets"][0][
        "asset_hash"
    ] = "00" * 32
    rwa_path = tmp_path / "rwa-index-tamper.json"
    _write_fixture(rwa_path, rwa_tamper)
    rwa_result = _run_oracle(rwa_path)
    assert rwa_result.returncode != 0
    assert "RWA derived index mismatch" in rwa_result.stderr

    messaging_tamper = copy.deepcopy(original)
    messaging_tamper["pos_scenario"]["expected_final"]["messaging_keys"][0][
        "register_txid"
    ] = messaging_tamper["pos_scenario"]["expected_final"][
        "messaging_registration_txids"
    ][0]
    messaging_path = tmp_path / "messaging-latest-wins-tamper.json"
    _write_fixture(messaging_path, messaging_tamper)
    messaging_result = _run_oracle(messaging_path)
    assert messaging_result.returncode != 0
    assert "messaging-key derived index mismatch" in messaging_result.stderr

    history_tamper = copy.deepcopy(original)
    history_tamper["pos_scenario"]["expected_final"][
        "messaging_registration_txids"
    ].reverse()
    history_path = tmp_path / "messaging-history-tamper.json"
    _write_fixture(history_path, history_tamper)
    history_result = _run_oracle(history_path)
    assert history_result.returncode != 0
    assert "messaging registration history mismatch" in history_result.stderr

    fee_tamper = copy.deepcopy(original)
    fee_tamper["pos_scenario"]["expected_final"]["metadata_fee_blocks"][0][
        "redistributed_fee"
    ] += 1
    fee_path = tmp_path / "metadata-fee-redistribution-tamper.json"
    _write_fixture(fee_path, fee_tamper)
    fee_result = _run_oracle(fee_path)
    assert fee_result.returncode != 0
    assert "metadata fee redistribution evidence mismatch" in fee_result.stderr

    supply_tamper = copy.deepcopy(original)
    supply_tamper["pos_scenario"]["expected_final"][
        "supply_minus_utxo_total"
    ] = 1
    supply_path = tmp_path / "metadata-supply-delta-tamper.json"
    _write_fixture(supply_path, supply_tamper)
    supply_result = _run_oracle(supply_path)
    assert supply_result.returncode != 0
    assert "metadata fee conservation changed" in supply_result.stderr

def test_oracles_reject_shielded_state_and_statement_tampering(tmp_path):
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))

    commitment_tamper = copy.deepcopy(original)
    commitment_tamper["shielded_scenario"]["expected"]["commitments"][0][
        "commitment"
    ] = "00" * 32
    commitment_path = tmp_path / "shielded-commitment-index-tamper.json"
    _write_fixture(commitment_path, commitment_tamper)
    commitment_result = _run_oracle(commitment_path)
    assert commitment_result.returncode != 0
    assert "shielded commitment index mismatch" in commitment_result.stderr

    sighash_tamper = copy.deepcopy(original)
    sighash_tamper["shielded_scenario"]["expected"]["sighashes"][0] = "00" * 32
    sighash_path = tmp_path / "shielded-sighash-tamper.json"
    _write_fixture(sighash_path, sighash_tamper)
    sighash_result = _run_oracle(sighash_path)
    assert sighash_result.returncode != 0
    assert "shielded canonical sighash mismatch" in sighash_result.stderr

    reconnect_tamper = copy.deepcopy(original)
    reconnect_tamper["shielded_scenario"]["expected"][
        "reconnect_restored_exact_state"
    ] = False
    reconnect_path = tmp_path / "shielded-reconnect-tamper.json"
    _write_fixture(reconnect_path, reconnect_tamper)
    reconnect_result = _run_oracle(reconnect_path)
    assert reconnect_result.returncode != 0
    assert "Python shielded reconnect evidence is missing" in (
        reconnect_result.stderr
    )

    root_tamper = copy.deepcopy(
        original["shielded_scenario"]
    )
    root_tamper["expected"]["anchors"][0]["anchor"] = "00" * 32
    with pytest.raises(AssertionError):
        _validate_shielded_rescue_reference(root_tamper)

    statement_tamper = copy.deepcopy(
        original["shielded_scenario"]
    )
    statement_tamper["expected"]["statement_digests"][1] = "00" * 32
    with pytest.raises(AssertionError):
        _validate_shielded_rescue_reference(statement_tamper)
