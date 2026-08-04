"""Mandatory launch contract for Ghost + PoS validator-signing rehearsal."""
from __future__ import annotations
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seven_day_evidence_requires_every_ghost_pos_drill_and_hash():
    template = json.loads((ROOT / "wepo-production-deployment/seven-day-rehearsal-evidence.template.json").read_text(encoding="utf-8"))
    drills = template["drills"]
    for key in (
        "ghost_valid_transfer_passed",
        "ghost_invalid_proof_refused",
        "ghost_verifier_timeout_crash_refused",
        "ghost_wallet_backup_restore_recovery_passed",
        "pos_live_signing_passed",
        "pos_partition_reorg_passed",
        "validator_anti_equivocation_refused",
        "validator_signer_fencing_failover_passed",
    ):
        assert drills[key] is False
    supporting = template["supporting_evidence"]
    for key in ("pos_multinode_rehearsal_sha256", "validator_signer_host_qualification_sha256", "validator_fencing_failover_sha256"):
        assert supporting[key].startswith("REPLACE_WITH_")
    verifier = (ROOT / "wepo-production-deployment/verify-seven-day-rehearsal-evidence.py").read_text(encoding="utf-8")
    for key in drills:
        assert f'"{key}"' in verifier


def test_signer_and_rehearsal_are_explicitly_network_bound_and_private_key_free():
    signer = ROOT / "wepo-blockchain/core/validator_signer.py"
    rehearsal = ROOT / "wepo-blockchain/scripts/wepo_pos_multinode_rehearsal.py"
    ceremony = ROOT / "wepo-production-deployment/validator_stake_ceremony.py"
    ast.parse(signer.read_text(encoding="utf-8"), filename=str(signer))
    signer_text = signer.read_text(encoding="utf-8")
    rehearsal_text = rehearsal.read_text(encoding="utf-8")
    ceremony_text = ceremony.read_text(encoding="utf-8")
    for marker in ("PosSigningContext", "previous_block_hash", "signing_payload", "sighash.lower()", "shell=False", "close_fds=True"):
        assert marker in signer_text
    for marker in ("network_bound_sighash", "controller_loaded_private_key", "private_key_in_evidence", "anti_equivocation_quick_check", "continued_above_retained_height", "semantic_state_equal"):
        assert marker in rehearsal_text
    for marker in ("response.get(\"sighash\")", "verify_dilithium_signature", "get_canonical_sighash", "expected_txid"):
        assert marker in ceremony_text
    assert '"private_key": key.private_key' not in rehearsal_text


def test_mandatory_runbook_keeps_domain_and_thirty_day_clock_explicit():
    runbook = (ROOT / "docs/runbooks/MANDATORY_GHOST_POS_LAUNCH_QUALIFICATION.md").read_text(encoding="utf-8")
    for marker in ("mandatory for mainnet v1", "wepocoin.org", "three independently hosted", "TCP 22567", "30 full days later", "seven-day candidate"):
        assert marker in runbook
