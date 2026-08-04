#!/usr/bin/env python3
"""Fail-closed mainnet release-decision contract."""

import hashlib
import json
import os
import sys

import pytest


CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import network_profile as profiles  # noqa: E402
import wepo_node  # noqa: E402


CURRENT_REQUIRED_BLOCKERS = {
    "genesis_parameters_unfinalized",
    "genesis_timestamp_is_rehearsal_placeholder",
    "genesis_address_is_rehearsal_placeholder",
    "genesis_reward_policy_unset",
    "emission_policy_unset",
    "coinbase_maturity_unset",
    "minimum_relay_fee_unset",
    "pos_disposition_unset",
    "ghost_disposition_unset",
    "parameter_manifest_sha256_unset",
}


def _set_complete_deferred_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_TIMESTAMP",
        profiles.REHEARSAL_MAINNET_GENESIS_TIMESTAMP + 1,
    )
    monkeypatch.setattr(
        profiles,
        "MAINNET_GENESIS_ADDRESS",
        "wepo1q" + ("2" * 39),
    )
    monkeypatch.setattr(profiles, "MAINNET_GENESIS_FINALIZED", True)
    monkeypatch.setattr(
        profiles, "MAINNET_GENESIS_REWARD_POLICY", "auditable_distribution"
    )
    monkeypatch.setattr(profiles, "MAINNET_EMISSION_POLICY", "ceiling_only")
    monkeypatch.setattr(profiles, "MAINNET_COINBASE_MATURITY", 100)
    monkeypatch.setattr(profiles, "MAINNET_MINIMUM_RELAY_FEE_PER_KB", 1000)
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_POS_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", 1)
    monkeypatch.setattr(
        wepo_node.blockchain_core, "PRIVACY_CONSENSUS_ENABLED", True
    )
    profile = profiles.get_network_profile("mainnet")
    manifest_path = tmp_path / "MAINNET_PARAMETER_MANIFEST.json"
    manifest_bytes = profiles.render_mainnet_parameter_manifest(profile)
    manifest_path.write_bytes(manifest_bytes)
    monkeypatch.setattr(
        profiles, "MAINNET_PARAMETER_MANIFEST_SHA256", hashlib.sha256(manifest_bytes).hexdigest()
    )
    return profile, manifest_path


def test_current_mainnet_reports_every_unresolved_release_decision():
    blockers = set(profiles.mainnet_release_blockers())

    assert CURRENT_REQUIRED_BLOCKERS <= blockers
    assert not profiles.mainnet_release_ready()


def test_flipping_genesis_finalized_alone_cannot_open_mainnet(monkeypatch, tmp_path):
    monkeypatch.setattr(profiles, "MAINNET_GENESIS_FINALIZED", True)
    monkeypatch.setattr(wepo_node, "require_real_mldsa", lambda: None)

    blockers = set(profiles.mainnet_release_blockers())
    assert "genesis_parameters_unfinalized" not in blockers
    assert CURRENT_REQUIRED_BLOCKERS - {"genesis_parameters_unfinalized"} <= blockers

    with pytest.raises(RuntimeError, match="Mainnet release gate is closed") as exc:
        wepo_node.WepoFullNode(
            data_dir=str(tmp_path / "mainnet"),
            p2p_port=0,
            api_port=0,
            enable_mining=False,
            network_profile="mainnet",
        )

    for blocker in blockers:
        assert blocker in str(exc.value)
    assert not (tmp_path / "mainnet").exists()


def test_complete_consistent_decision_set_can_clear_the_profile_gate(monkeypatch, tmp_path):
    profile, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)

    assert profiles.mainnet_release_blockers(profile, manifest_path) == ()
    assert profiles.mainnet_release_ready(profile, manifest_path)
    parameters = profiles.build_mainnet_parameter_manifest(profile)["parameters"]
    assert parameters["supply_cap_atomic"] == wepo_node.SUPPLY_CAP
    assert (
        parameters["genesis_bootstrap_atomic"]
        == wepo_node.blockchain_core.GENESIS_BOOTSTRAP_REWARD
    )
    assert parameters["coinbase_maturity_blocks"] == profile.coinbase_maturity
    assert (
        parameters["ghost_consensus_ready"]
        == wepo_node.blockchain_core.PRIVACY_CONSENSUS_ENABLED
    )
    assert parameters["ghost_activation_height"] == 1
    assert parameters["rwa_disposition"] == "deferred"
    assert parameters["rwa_consensus_ready"] is False
    assert parameters["messaging_disposition"] == "deferred"
    assert parameters["messaging_consensus_ready"] is False


@pytest.mark.parametrize(
    ("disposition", "consensus_ready", "expected"),
    [
        ("enabled", False, "pos_enabled_but_consensus_not_ready"),
        ("deferred", True, "pos_deferred_but_consensus_enabled"),
    ],
)
def test_pos_disposition_must_match_consensus_activation(
    monkeypatch, tmp_path, disposition, consensus_ready, expected
):
    _, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", disposition)
    monkeypatch.setattr(profiles, "MAINNET_POS_CONSENSUS_READY", consensus_ready)

    profile = profiles.get_network_profile("mainnet")
    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert expected in blockers
    assert not profiles.mainnet_release_ready(profile, manifest_path)


@pytest.mark.parametrize(
    ("disposition", "consensus_ready", "expected"),
    [
        ("enabled", False, "ghost_enabled_but_consensus_not_ready"),
        ("deferred", True, "ghost_deferred_but_consensus_enabled"),
    ],
)
def test_ghost_disposition_must_match_consensus_activation(
    monkeypatch, tmp_path, disposition, consensus_ready, expected
):
    _, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", disposition)
    monkeypatch.setattr(
        profiles, "MAINNET_GHOST_CONSENSUS_READY", consensus_ready
    )

    profile = profiles.get_network_profile("mainnet")
    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert expected in blockers
    assert not profiles.mainnet_release_ready(profile, manifest_path)


@pytest.mark.parametrize(
    ("feature", "disposition_constant", "readiness_constant", "profile_field"),
    [
        (
            "rwa",
            "MAINNET_RWA_DISPOSITION",
            "MAINNET_RWA_CONSENSUS_READY",
            "rwa_consensus_ready",
        ),
        (
            "messaging",
            "MAINNET_MESSAGING_DISPOSITION",
            "MAINNET_MESSAGING_CONSENSUS_READY",
            "messaging_consensus_ready",
        ),
    ],
)
@pytest.mark.parametrize(
    ("disposition", "consensus_ready", "suffix"),
    [
        ("enabled", False, "enabled_but_consensus_not_ready"),
        ("deferred", True, "deferred_but_consensus_enabled"),
    ],
)
def test_optional_feature_disposition_must_match_consensus_activation(
    monkeypatch, tmp_path, feature, disposition_constant, readiness_constant,
    profile_field, disposition, consensus_ready, suffix
):
    _, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    monkeypatch.setattr(profiles, disposition_constant, disposition)
    monkeypatch.setattr(profiles, readiness_constant, consensus_ready)

    profile = profiles.get_network_profile("mainnet")
    assert getattr(profile, profile_field) is consensus_ready
    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert f"{feature}_{suffix}" in blockers
    assert not profiles.mainnet_release_ready(profile, manifest_path)


def test_invalid_policy_values_and_manifest_fail_closed(monkeypatch, tmp_path):
    _set_complete_deferred_profile(monkeypatch, tmp_path)
    monkeypatch.setattr(profiles, "MAINNET_GENESIS_REWARD_POLICY", "pending")
    monkeypatch.setattr(profiles, "MAINNET_EMISSION_POLICY", "exact_someday")
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", "maybe")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "audit_later")
    monkeypatch.setattr(profiles, "MAINNET_PARAMETER_MANIFEST_SHA256", "ABC123")
    monkeypatch.setattr(profiles, "MAINNET_RWA_DISPOSITION", "maybe")
    monkeypatch.setattr(profiles, "MAINNET_MESSAGING_DISPOSITION", "audit_later")

    assert set(profiles.mainnet_release_blockers()) >= {
        "genesis_reward_policy_invalid",
        "emission_policy_invalid",
        "pos_disposition_invalid",
        "ghost_disposition_invalid",
        "rwa_disposition_invalid",
        "messaging_disposition_invalid",
        "parameter_manifest_sha256_invalid",
    }


@pytest.mark.parametrize(
    ("constant", "value", "expected"),
    [
        ("MAINNET_GENESIS_REWARD_POLICY", "burn", "genesis_reward_policy_not_implemented"),
        ("MAINNET_EMISSION_POLICY", "redesigned_target_cap", "emission_policy_not_implemented"),
        ("MAINNET_EMISSION_POLICY", "lowered_cap", "emission_policy_not_implemented"),
    ],
)
def test_allowed_but_unimplemented_policy_labels_cannot_clear_the_gate(
    monkeypatch, tmp_path, constant, value, expected
):
    profile, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    monkeypatch.setattr(profiles, constant, value)

    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert expected in blockers
    assert not profiles.mainnet_release_ready(profile, manifest_path)


def test_manifest_file_is_required_when_a_digest_is_frozen(monkeypatch, tmp_path):
    profile, _ = _set_complete_deferred_profile(monkeypatch, tmp_path)

    blockers = profiles.mainnet_release_blockers(
        profile, tmp_path / "missing.json"
    )
    assert "parameter_manifest_missing" in blockers


def test_manifest_byte_tampering_fails_the_frozen_digest(monkeypatch, tmp_path):
    profile, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert "parameter_manifest_sha256_mismatch" in blockers


def test_rehashed_semantic_manifest_tampering_still_fails(monkeypatch, tmp_path):
    profile, manifest_path = _set_complete_deferred_profile(monkeypatch, tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["parameters"]["coinbase_maturity_blocks"] = 1
    tampered = (
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(tampered)
    monkeypatch.setattr(
        profiles,
        "MAINNET_PARAMETER_MANIFEST_SHA256",
        hashlib.sha256(tampered).hexdigest(),
    )

    blockers = profiles.mainnet_release_blockers(profile, manifest_path)
    assert "parameter_manifest_content_mismatch" in blockers


def test_non_mainnet_profile_cannot_be_used_for_release_acceptance():
    with pytest.raises(ValueError, match="requires the mainnet profile"):
        profiles.mainnet_release_blockers(profiles.get_network_profile("test"))
