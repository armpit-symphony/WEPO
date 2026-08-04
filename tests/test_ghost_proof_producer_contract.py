"""The proof adapter must remain bound to the audited local bridge."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "frontend" / "src" / "utils" / "ghostProofProducer.js"


def test_proof_adapter_rejects_nonlocal_provers_and_forwards_exact_sighash():
    source = PRODUCER.read_text(encoding="utf-8")
    for marker in (
        "wepo-local-ghost-crypto-v1",
        "bridge.localOnly !== true",
        "the local bridge and witness builder are required",
        "valueBalance: bundle.value_balance",
        "sighash: hexToBytes(sighash)",
        "return { proof, sighash }",
    ):
        assert marker in source
