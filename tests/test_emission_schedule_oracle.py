"""Independent monetary-schedule contract and fail-closed tamper tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
FIXTURE = ROOT / "tests" / "vectors" / "emission_schedule_v1.json"
ORACLE = ROOT / "tests" / "emission_schedule_oracle.mjs"

sys.path.insert(0, str(CORE))
import blockchain as B  # noqa: E402
import network_profile as N  # noqa: E402


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _run_oracle(path: Path = FIXTURE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(ORACLE), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bind_mainnet_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = N.get_network_profile("mainnet")
    for name, value in {
        "PRE_POS_DURATION_BLOCKS": profile.pre_pos_duration_blocks,
        "POS_ACTIVATION_HEIGHT": profile.pos_activation_height,
        "BLOCKS_PER_YEAR_LONGTERM": 58_440,
        "PHASE_2A_END_HEIGHT": profile.phase_2a_end_height,
        "PHASE_2B_END_HEIGHT": profile.phase_2b_end_height,
        "PHASE_2C_END_HEIGHT": profile.phase_2c_end_height,
        "PHASE_2D_END_HEIGHT": profile.phase_2d_end_height,
    }.items():
        monkeypatch.setattr(B, name, value)


def test_checked_in_oracle_recomputes_complete_schedule():
    result = _run_oracle()
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["cap_reachable"] is False
    assert actual["clamp_triggered"] is False
    assert actual["maximum_qualifying_issuance_atomic"] == "2600646886718600"
    assert actual["cap_shortfall_atomic"] == "4299353413281400"
    assert actual["first_zero_pos_height"] == 9_189_600


def test_vector_parameters_match_mainnet_consensus(monkeypatch: pytest.MonkeyPatch):
    fixture = _fixture()
    parameters = fixture["parameters"]
    profile = N.get_network_profile("mainnet")
    phases = parameters["pow_phases"]

    assert parameters["unit_atomic"] == str(N.COIN)
    assert parameters["hard_cap_atomic"] == str(B.SUPPLY_CAP)
    assert parameters["genesis_bootstrap_atomic"] == str(N.GENESIS_BOOTSTRAP_REWARD)
    assert parameters["blocks_per_year_longterm"] == 58_440
    assert parameters["pos_activation_height"] == profile.pos_activation_height
    assert parameters["pow_end_height"] == profile.pow_end_height
    assert [phase["end_height"] for phase in phases] == [
        profile.pre_pos_duration_blocks,
        profile.phase_2a_end_height,
        profile.phase_2b_end_height,
        profile.phase_2c_end_height,
        profile.phase_2d_end_height,
    ]
    assert [phase["reward_atomic"] for phase in phases] == [
        str(N.PRE_POS_REWARD),
        str(N.PHASE_2A_REWARD),
        str(N.PHASE_2B_REWARD),
        str(N.PHASE_2C_REWARD),
        str(N.PHASE_2D_REWARD),
    ]
    expected = fixture["expected"]
    assert str(B.PRE_POS_TOTAL_SUPPLY) == expected["phase_totals"][0]["total_atomic"]
    assert str(B.TOTAL_POW_SUPPLY + N.GENESIS_BOOTSTRAP_REWARD) == (
        expected["pow_total_atomic"]
    )

    _bind_mainnet_schedule(monkeypatch)
    for boundary in fixture["expected"]["boundary_rewards"]:
        height = boundary["height"]
        assert str(B.WepoBlockchain.calculate_block_reward(None, height)) == boundary["pow_base_atomic"]
        assert str(B.WepoBlockchain.calculate_pos_reward(None, height)) == boundary["pos_pool_atomic"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["parameters"]["pow_phases"][1].__setitem__("reward_atomic", "3317000001"),
            "PoW phase totals changed",
        ),
        (
            lambda value: value["parameters"]["pow_phases"][2].__setitem__("start_height", 306722),
            "non-contiguous start height",
        ),
        (
            lambda value: value["parameters"].__setitem__("hard_cap_atomic", "6900000299999999"),
            "cap_shortfall_atomic changed",
        ),
        (
            lambda value: value["expected"].__setitem__("maximum_qualifying_issuance_atomic", "2600646886718601"),
            "maximum_qualifying_issuance_atomic changed",
        ),
        (
            lambda value: value["expected"].__setitem__("first_zero_pos_height", 9_189_601),
            "first_zero_pos_height changed",
        ),
    ],
)
def test_oracle_rejects_one_unit_and_one_height_tampering(tmp_path: Path, mutate, message: str):
    tampered = copy.deepcopy(_fixture())
    mutate(tampered)
    path = tmp_path / "tampered-emission.json"
    _write(path, tampered)
    result = _run_oracle(path)
    assert result.returncode != 0
    assert message in result.stderr
