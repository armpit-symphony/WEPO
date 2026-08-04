"""The Ghost planner is reachable through the node and wallet custody paths."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "wepo-blockchain" / "core" / "wepo_node.py"
WALLET = ROOT / "frontend" / "src" / "contexts" / "WalletContext.jsx"


def test_node_exposes_fail_closed_unsigned_ghost_builder():
    source = NODE.read_text(encoding="utf-8")
    for marker in (
        '"/api/transaction/build-ghost-unsigned"',
        '"shielding", "shielded", "unshielding"',
        "Transaction.from_dict(parse_data)",
        "bundle.check_shape()",
        "get_transaction_input_utxo_context",
        "Ghost value conservation failed",
        '"sighash": tx.get_canonical_sighash(network).hex()',
        '"shielded_bundle"]["proof"] = None',
    ):
        assert marker in source


def test_wallet_context_proves_signs_rechecks_and_submits_locally():
    source = WALLET.read_text(encoding="utf-8")
    for marker in (
        "createGhostTransactionPlan",
        "assertGhostTransactionPlan",
        "An audited local Ghost bridge is required",
        "/api/transaction/build-ghost-unsigned",
        "/api/transaction/send",
        "canonicalSighashHex(build.unsigned_tx, NETWORK_PROFILE)",
        "signTransaction(",
        "canonicalTxidHex(signedTx)",
        "sendGhostTransaction",
        "createGhostBridgeProofProducer",
        "buildGhostBridgeWitness",
        "loadGhostState(password)",
        "spendNotes",
    ):
        assert marker in source
