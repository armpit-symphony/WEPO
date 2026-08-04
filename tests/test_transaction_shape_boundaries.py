#!/usr/bin/env python3
"""Consensus transaction shape and deterministic-deserialization regressions."""

import copy
import os
import sys

CORE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
)
sys.path.insert(0, CORE)

import blockchain as B  # noqa: E402


FAILURES = []
ADDRESS = "wepo1q111111111111111111111111111111111111111"


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


def fixture():
    return B.Transaction(
        version=B.TRANSACTION_VERSION,
        inputs=[
            B.TransactionInput(
                prev_txid="1" * 64,
                prev_vout=0,
                script_sig=b"",
                sequence=B.MAX_SEQUENCE,
            )
        ],
        outputs=[
            B.TransactionOutput(
                value=1,
                address=ADDRESS,
                script_pubkey=b"output",
            )
        ],
        lock_time=0,
        fee=0,
        tx_type=B.TX_TYPE_TRANSFER,
        extra_data={
            "nested": {"\ue000": 1, "\U0001f600": 2},
            "types": [None, True, "caf\u00e9"],
        },
        timestamp=1_800_000_000,
    )


def changed(base, mutator):
    candidate = copy.deepcopy(base)
    mutator(candidate)
    return candidate


def decode_rejected(payload):
    try:
        B.Transaction.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return True
    return False


def main():
    chain = object.__new__(B.WepoBlockchain)
    chain.network_profile = B.get_network_profile("test")
    tx = fixture()

    def shape(value):
        return chain._validate_transaction_consensus_shape(
            value,
            height=1,
            allow_coinbase=True,
            context="shape-test",
        )

    check("canonical transaction shape is accepted", shape(tx))
    transfer_without_outputs = changed(
        tx,
        lambda value: setattr(value, "outputs", []),
    )
    check(
        "ordinary transfer still requires a transparent output",
        not shape(transfer_without_outputs),
    )
    for anchor_type, minimum_fee in (
        (B.TX_TYPE_RWA_CREATE, B.RWA_CREATION_MIN_FEE),
        (B.TX_TYPE_KEY_REGISTER, B.MSG_KEY_REGISTER_MIN_FEE),
    ):
        exact_fee_anchor = copy.deepcopy(tx)
        exact_fee_anchor.tx_type = anchor_type
        exact_fee_anchor.fee = minimum_fee
        exact_fee_anchor.outputs = []
        check(
            f"{anchor_type} permits an exact-fee metadata anchor with no change",
            shape(exact_fee_anchor),
        )
        exact_fee_anchor.inputs = []
        check(
            f"{anchor_type} cannot create a metadata anchor without an input",
            not shape(exact_fee_anchor),
        )

    too_deep = 0
    for _ in range(B.MAX_CONSENSUS_JSON_DEPTH + 2):
        too_deep = [too_deep]

    invalid_cases = (
        ("unknown version", lambda value: setattr(value, "version", 2)),
        ("nonzero unsupported lock_time", lambda value: setattr(value, "lock_time", 1)),
        ("boolean version", lambda value: setattr(value, "version", True)),
        ("negative lock_time", lambda value: setattr(value, "lock_time", -1)),
        (
            "oversized lock_time",
            lambda value: setattr(value, "lock_time", B.MAX_LOCK_TIME + 1),
        ),
        ("zero timestamp", lambda value: setattr(value, "timestamp", 0)),
        (
            "unsafe timestamp integer",
            lambda value: setattr(value, "timestamp", B.MAX_SAFE_JSON_INTEGER + 1),
        ),
        ("unknown transaction type", lambda value: setattr(value, "tx_type", "future")),
        ("negative fee", lambda value: setattr(value, "fee", -1)),
        ("oversized fee", lambda value: setattr(value, "fee", B.SUPPLY_CAP + 1)),
        (
            "non-hex input txid",
            lambda value: setattr(value.inputs[0], "prev_txid", "g" * 64),
        ),
        (
            "oversized output index",
            lambda value: setattr(value.inputs[0], "prev_vout", B.MAX_OUTPUT_INDEX + 1),
        ),
        (
            "negative sequence",
            lambda value: setattr(value.inputs[0], "sequence", -1),
        ),
        (
            "nonfinal unsupported sequence",
            lambda value: setattr(value.inputs[0], "sequence", B.MAX_SEQUENCE - 1),
        ),
        (
            "nonempty legacy script_sig",
            lambda value: setattr(value.inputs[0], "script_sig", b"malleable"),
        ),
        (
            "noncanonical missing output script",
            lambda value: setattr(value.outputs[0], "script_pubkey", None),
        ),
        (
            "excessive input count",
            lambda value: setattr(
                value,
                "inputs",
                value.inputs * (B.MAX_TRANSACTION_INPUTS + 1),
            ),
        ),
        (
            "excessive output count",
            lambda value: setattr(
                value,
                "outputs",
                value.outputs * (B.MAX_TRANSACTION_OUTPUTS + 1),
            ),
        ),
        (
            "oversized input script",
            lambda value: setattr(
                value.inputs[0],
                "script_sig",
                b"x" * (B.MAX_TRANSACTION_SCRIPT_BYTES + 1),
            ),
        ),
        (
            "non-byte input script",
            lambda value: setattr(value.inputs[0], "script_sig", "not-bytes"),
        ),
        (
            "non-byte output script",
            lambda value: setattr(value.outputs[0], "script_pubkey", "not-bytes"),
        ),
        (
            "oversized output script",
            lambda value: setattr(
                value.outputs[0],
                "script_pubkey",
                b"x" * (B.MAX_TRANSACTION_SCRIPT_BYTES + 1),
            ),
        ),
        (
            "floating-point metadata",
            lambda value: value.extra_data.update({"float": 1.5}),
        ),
        (
            "unsafe metadata integer",
            lambda value: value.extra_data.update(
                {"integer": B.MAX_SAFE_JSON_INTEGER + 1}
            ),
        ),
        (
            "oversized metadata",
            lambda value: setattr(
                value,
                "extra_data",
                {"payload": "x" * B.MAX_TRANSACTION_EXTRA_DATA_BYTES},
            ),
        ),
        (
            "excessively nested metadata",
            lambda value: setattr(value, "extra_data", {"root": too_deep}),
        ),
    )
    for name, mutator in invalid_cases:
        check(f"rejects {name}", not shape(changed(tx, mutator)))

    encoded = tx.to_dict()
    encoded["timestamp"] = 0
    first = B.Transaction.from_dict(encoded)
    second = B.Transaction.from_dict(encoded)
    check("wire timestamp zero remains zero", first.timestamp == second.timestamp == 0)
    check("wire timestamp zero is rejected", not shape(first))

    unknown_root = copy.deepcopy(encoded)
    unknown_root["future_consensus_field"] = 1
    check(
        "wire transaction rejects unknown root fields",
        decode_rejected(unknown_root),
    )

    coerced_version = copy.deepcopy(encoded)
    coerced_version["version"] = str(B.TRANSACTION_VERSION)
    check(
        "wire transaction rejects integer coercion",
        decode_rejected(coerced_version),
    )

    coerced_vout = copy.deepcopy(encoded)
    coerced_vout["inputs"][0]["prev_vout"] = 0.0
    check(
        "wire transaction rejects input integer coercion",
        decode_rejected(coerced_vout),
    )

    malformed_hex = copy.deepcopy(encoded)
    malformed_hex["inputs"][0]["script_sig"] = "not-hex"
    check(
        "wire transaction rejects malformed hexadecimal bytes",
        decode_rejected(malformed_hex),
    )

    unknown_input = copy.deepcopy(encoded)
    unknown_input["inputs"][0]["future_field"] = 1
    check(
        "wire transaction rejects unknown input fields",
        decode_rejected(unknown_input),
    )

    excessive_wire_inputs = copy.deepcopy(encoded)
    excessive_wire_inputs["inputs"] *= B.MAX_TRANSACTION_INPUTS + 1
    check(
        "wire transaction rejects excessive inputs before construction",
        decode_rejected(excessive_wire_inputs),
    )

    missing = tx.to_dict()
    missing.pop("timestamp")
    decoded_missing = B.Transaction.from_dict(missing)
    check("missing wire timestamp remains deterministic", decoded_missing.timestamp == 0)
    check("missing wire timestamp is rejected", not shape(decoded_missing))

    if FAILURES:
        print(f"\nRESULT: {len(FAILURES)} FAILURE(S)")
        raise SystemExit(1)
    print("\nRESULT: ALL CHECKS PASSED")


def test_regression_suite():
    main()


if __name__ == "__main__":
    main()
