"""The browser Ghost planner must bind every privacy flow to canonical sighash."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "frontend" / "src" / "utils" / "ghostTransactionPlanner.js"
TEST = ROOT / "frontend" / "src" / "utils" / "ghostTransactionPlanner.test.js"


def test_planner_contract_is_fail_closed_and_flow_explicit():
    source = PLANNER.read_text(encoding="utf-8")
    for marker in (
        "wepo-ghost-transaction-plan-v1",
        "SHIELDING: 'shielding'",
        "SHIELDED: 'shielded'",
        "UNSHIELDING: 'unshielding'",
        "canonicalSighashHex",
        "canonicalTxidHex",
        "a local proof producer is required",
        "prover did not explicitly bind its proof",
        "attaching the proof changed the canonical sighash",
        "candidate transaction does not match the planned canonical sighash",
        "duplicate shielded nullifier",
        "MAX_SHIELDED_SPENDS = 4",
        "MAX_SHIELDED_OUTPUTS = 2",
    ):
        assert marker in source


def test_focused_frontend_cases_cover_all_flows_and_mutation_rejection():
    source = TEST.read_text(encoding="utf-8")
    for marker in (
        "plans ${flow} with an exact proof binding",
        "rejects a prover that omits or changes the requested sighash",
        "rejects a mutation of a planned public field before submission",
        "GHOST_TRANSACTION_FLOWS.SHIELDING",
        "GHOST_TRANSACTION_FLOWS.SHIELDED",
        "GHOST_TRANSACTION_FLOWS.UNSHIELDING",
    ):
        assert marker in source
