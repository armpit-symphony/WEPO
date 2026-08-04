"""Release policy contracts for mandatory Ghost and PoS launch consensus."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))

import network_profile as profiles  # noqa: E402


def test_pos_cannot_be_deferred_from_mainnet_launch(monkeypatch):
    monkeypatch.setattr(profiles, "MAINNET_POS_DISPOSITION", "deferred")
    monkeypatch.setattr(profiles, "MAINNET_POS_CONSENSUS_READY", False)

    blockers = profiles.mainnet_release_blockers()

    assert "pos_required_at_launch_but_deferred" in blockers


def test_ghost_cannot_be_deferred_from_mainnet_launch(monkeypatch):
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "deferred")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", False)

    blockers = profiles.mainnet_release_blockers()

    assert "ghost_required_at_launch_but_deferred" in blockers


def test_mandatory_launch_features_require_enabled_dispositions():
    assert profiles.MANDATORY_MAINNET_FEATURE_DISPOSITIONS == {

        "pos": "enabled",
        "ghost": "enabled",
    }

def test_ghost_activation_height_is_required_for_mainnet(monkeypatch):
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", None)

    blockers = profiles.mainnet_release_blockers()

    assert "ghost_activation_height_unset" in blockers


def test_ghost_activation_height_must_be_a_positive_integer(monkeypatch):
    monkeypatch.setattr(profiles, "MAINNET_GHOST_DISPOSITION", "enabled")
    monkeypatch.setattr(profiles, "MAINNET_GHOST_CONSENSUS_READY", True)
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", 0)

    blockers = profiles.mainnet_release_blockers()

    assert "ghost_activation_height_invalid" in blockers


def test_ghost_activation_height_is_bound_into_parameter_manifest(monkeypatch):
    monkeypatch.setattr(profiles, "MAINNET_GHOST_ACTIVATION_HEIGHT", 1)
    assert profiles.build_mainnet_parameter_manifest()["parameters"]["ghost_activation_height"] == 1
