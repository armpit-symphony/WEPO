#!/usr/bin/env python3
"""Canonical transaction sighash and txid field-coverage regressions."""

import copy
import os
import sys

CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

from blockchain import Transaction, TransactionInput, TransactionOutput  # noqa: E402


FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def fixture():
    return Transaction(
        version=1,
        inputs=[
            TransactionInput(
                prev_txid="1" * 64,
                prev_vout=2,
                script_sig=b"",
                sequence=3,
            )
        ],
        outputs=[
            TransactionOutput(
                value=4,
                address="wepo1q111111111111111111111111111111111111111",
                script_pubkey=b"marker",
            )
        ],
        lock_time=5,
        fee=6,
        tx_type="transfer",
        extra_data={"purpose": "identity-test"},
        timestamp=1_800_000_000,
    )


def changed(base, mutator):
    candidate = copy.deepcopy(base)
    mutator(candidate)
    return candidate


def main():
    tx = fixture()
    base_sighash = tx.get_canonical_sighash()
    base_txid = tx.calculate_txid()

    print("Canonical sighash field coverage:")
    for name, mutator in (
        ("timestamp", lambda value: setattr(value, "timestamp", value.timestamp + 1)),
        ("fee", lambda value: setattr(value, "fee", value.fee + 1)),
        ("lock_time", lambda value: setattr(value, "lock_time", value.lock_time + 1)),
        ("input outpoint", lambda value: setattr(value.inputs[0], "prev_vout", 9)),
        ("input sequence", lambda value: setattr(value.inputs[0], "sequence", 10)),
        ("output value", lambda value: setattr(value.outputs[0], "value", 11)),
        ("output address", lambda value: setattr(value.outputs[0], "address", value.outputs[0].address + "x")),
        ("output script", lambda value: setattr(value.outputs[0], "script_pubkey", b"other")),
        ("transaction type", lambda value: setattr(value, "tx_type", "other")),
        ("extra data", lambda value: value.extra_data.update({"purpose": "changed"})),
    ):
        check(
            f"sighash binds {name}",
            changed(tx, mutator).get_canonical_sighash() != base_sighash,
        )

    signature_variant = copy.deepcopy(tx)
    signature_variant.inputs[0].signature_type = "dilithium"
    signature_variant.inputs[0].quantum_public_key = b"p" * 1312
    signature_variant.inputs[0].quantum_signature = b"s" * 2420
    check(
        "signature attachment does not change sighash",
        signature_variant.get_canonical_sighash() == base_sighash,
    )

    print("\nCanonical txid field coverage:")
    for name, mutator in (
        ("timestamp", lambda value: setattr(value, "timestamp", value.timestamp + 1)),
        ("fee", lambda value: setattr(value, "fee", value.fee + 1)),
        ("script signature", lambda value: setattr(value.inputs[0], "script_sig", b"sig")),
        ("quantum public key and signature", lambda value: (
            setattr(value.inputs[0], "quantum_public_key", b"p" * 1312),
            setattr(value.inputs[0], "quantum_signature", b"s" * 2420),
            setattr(value.inputs[0], "signature_type", "dilithium"),
        )),
        ("extra data", lambda value: value.extra_data.update({"new": True})),
    ):
        check(f"txid binds {name}", changed(tx, mutator).calculate_txid() != base_txid)

    round_trip = Transaction.from_dict(tx.to_dict())
    check("serialized round-trip preserves txid", round_trip.calculate_txid() == base_txid)

    # The old delimiter-free algorithm encoded both outputs below as the same
    # string fragment, "123". Length-delimited canonical JSON keeps them apart.
    ambiguous_a = fixture()
    ambiguous_a.outputs[0].value = 1
    ambiguous_a.outputs[0].address = "23"
    ambiguous_b = fixture()
    ambiguous_b.outputs[0].value = 12
    ambiguous_b.outputs[0].address = "3"
    check(
        "txid has no delimiter ambiguity",
        ambiguous_a.calculate_txid() != ambiguous_b.calculate_txid(),
    )

    # The old pipe-joined sighash encoded these distinct address/script pairs
    # identically. Structured canonical serialization must keep field boundaries.
    sighash_ambiguous_a = fixture()
    sighash_ambiguous_a.outputs[0].address = "alpha|beta"
    sighash_ambiguous_a.outputs[0].script_pubkey = b"gamma"
    sighash_ambiguous_b = fixture()
    sighash_ambiguous_b.outputs[0].address = "alpha"
    sighash_ambiguous_b.outputs[0].script_pubkey = b"beta|gamma"
    check(
        "sighash has no delimiter ambiguity",
        sighash_ambiguous_a.get_canonical_sighash()
        != sighash_ambiguous_b.get_canonical_sighash(),
    )

    if FAILURES:
        print(f"\nRESULT: {len(FAILURES)} FAILURE(S)")
        raise SystemExit(1)
    print("\nRESULT: ALL CHECKS PASSED")


def test_regression_suite():
    main()


if __name__ == "__main__":
    main()
