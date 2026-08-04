#!/usr/bin/env python3
"""End-to-end tests for the real complete-circuit Ghost verifier process."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(CORE))

import _backend_shim  # noqa: F401,E402
import blockchain as B  # noqa: E402
import shielded as S  # noqa: E402
from address_utils import generate_wepo_address  # noqa: E402
from dilithium import generate_dilithium_keypair  # noqa: E402
from shielded_verifier import SubprocessShieldedVerifier  # noqa: E402


REQUEST_MAGIC = b"WEPO_GHOST_VERIFY_V1\x00"
PROOF_MAGIC = b"WEPO_GHOST_PROOF_V1\x00"
EXE = ".exe" if os.name == "nt" else ""
VERIFIER = ROOT / "zk" / "target" / "release" / f"ghost_verifier{EXE}"
FIXTURE = ROOT / "zk" / "target" / "release" / f"ghost_fixture{EXE}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_verifier(request: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VERIFIER)],
        input=request,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )


def split_request(request: bytes) -> tuple[bytes, bytes]:
    require(request.startswith(REQUEST_MAGIC), "wrong outer request magic")
    cursor = len(REQUEST_MAGIC)
    digest = request[cursor : cursor + 32]
    require(len(digest) == 32, "truncated statement digest")
    cursor += 32
    envelope_len = struct.unpack("<I", request[cursor : cursor + 4])[0]
    cursor += 4
    envelope = request[cursor : cursor + envelope_len]
    require(len(envelope) == envelope_len, "truncated proof envelope")
    require(cursor + envelope_len == len(request), "trailing request bytes")
    return digest, envelope


def raw_proof_offset(envelope: bytes) -> int:
    require(envelope.startswith(PROOF_MAGIC), "wrong proof-envelope magic")
    cursor = len(PROOF_MAGIC)
    spends = envelope[cursor]
    outputs = envelope[cursor + 1]
    cursor += 2 + 32 + spends * 32 + outputs * 32 + 8 + 32
    proof_len = struct.unpack("<I", envelope[cursor : cursor + 4])[0]
    cursor += 4
    require(proof_len > 0, "empty generated proof")
    require(cursor + proof_len == len(envelope), "bad generated proof length")
    return cursor


def parse_statement(envelope: bytes):
    require(envelope.startswith(PROOF_MAGIC), "wrong proof-envelope magic")
    cursor = len(PROOF_MAGIC)
    spend_count = envelope[cursor]
    output_count = envelope[cursor + 1]
    cursor += 2
    anchor = envelope[cursor : cursor + 32]
    cursor += 32
    nullifiers = []
    for _ in range(spend_count):
        nullifiers.append(envelope[cursor : cursor + 32])
        cursor += 32
    commitments = []
    for _ in range(output_count):
        commitments.append(envelope[cursor : cursor + 32])
        cursor += 32
    value_balance = struct.unpack("<q", envelope[cursor : cursor + 8])[0]
    cursor += 8
    sighash = envelope[cursor : cursor + 32]
    cursor += 32
    proof_len = struct.unpack("<I", envelope[cursor : cursor + 4])[0]
    cursor += 4
    require(cursor + proof_len == len(envelope), "bad proof length")
    return {
        "anchor": anchor,
        "nullifiers": nullifiers,
        "commitments": commitments,
        "value_balance": value_balance,
        "sighash": sighash,
    }


def main() -> None:
    require(
        VERIFIER.is_file() and FIXTURE.is_file(),
        "build first: cargo build --release --bin ghost_verifier --bin ghost_fixture",
    )

    with tempfile.TemporaryDirectory(prefix="wepo-ghost-verifier-") as temp:
        request_path = Path(temp) / "honest-request.bin"
        generated = subprocess.run(
            [str(FIXTURE), str(request_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        require(generated.returncode == 0, "honest proof generation failed")
        require(
            generated.stdout == b"" and generated.stderr == b"",
            "fixture generator emitted unexpected output",
        )
        request = request_path.read_bytes()

    digest, envelope = split_request(request)
    require(len(request) <= 1024 * 1024 + len(REQUEST_MAGIC) + 36,
            "honest request exceeds verifier limit")

    clean = run_verifier(request)
    require(clean.returncode == 0, "honest complete-circuit proof was rejected")
    require(clean.stdout == b"" and clean.stderr == b"",
            "verifier emitted output for an honest proof")

    boundary = SubprocessShieldedVerifier([str(VERIFIER)], timeout_seconds=15)
    require(boundary.verify(digest, envelope),
            "Python subprocess boundary rejected the honest Rust proof")

    # Build a real node transaction, ask the honest prover for this transaction's
    # exact sighash, and verify through the complete Python -> subprocess -> Rust
    # consensus path. This closes the gap between a valid standalone fixture and
    # a proof actually bound to WEPO transaction serialization.
    original_statement = parse_statement(envelope)
    old_enabled = B.PRIVACY_CONSENSUS_ENABLED
    old_activation = B.SHIELDED_ACTIVATION_HEIGHT
    B.PRIVACY_CONSENSUS_ENABLED = True
    B.SHIELDED_ACTIVATION_HEIGHT = 1
    S.register_verifier(boundary, audit_approved=True)
    try:
        with tempfile.TemporaryDirectory(prefix="wepo-ghost-node-") as node_temp:
            chain = B.WepoBlockchain(node_temp, network_profile="test")
            owner = generate_dilithium_keypair()
            owner_address = generate_wepo_address(
                owner.public_key,
                address_type="quantum",
            )
            funding_txid = "a" * 64
            funding_amount = original_statement["value_balance"]
            require(funding_amount > 0, "fixture must shield positive transparent value")
            chain.conn.execute(
                "INSERT INTO utxos "
                "(txid, vout, address, amount, script_pubkey, spent) "
                "VALUES (?, 0, ?, ?, ?, FALSE)",
                (funding_txid, owner_address, funding_amount, b"fixture-funding"),
            )
            chain.conn.commit()

            node_bundle = S.ShieldedBundle(
                spends=[
                    S.SpendDescription(
                        anchor=original_statement["anchor"],
                        nullifier=nullifier,
                    )
                    for nullifier in original_statement["nullifiers"]
                ],
                outputs=[
                    S.OutputDescription(commitment=commitment, enc_note=b"")
                    for commitment in original_statement["commitments"]
                ],
                value_balance=funding_amount,
                proof=envelope,
            )
            transaction = B.Transaction(
                version=1,
                inputs=[
                    B.TransactionInput(
                        prev_txid=funding_txid,
                        prev_vout=0,
                        script_sig=b"",
                    )
                ],
                outputs=[],
                lock_time=0,
                fee=0,
                shielded_bundle=node_bundle,
                timestamp=1_800_000_001,
            )
            transaction_sighash = transaction.get_canonical_sighash()

            rebound_path = Path(node_temp) / "transaction-bound-request.bin"
            generated = subprocess.run(
                [str(FIXTURE), str(rebound_path), transaction_sighash.hex()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            require(generated.returncode == 0, "transaction-bound proof generation failed")
            _, rebound_envelope = split_request(rebound_path.read_bytes())
            rebound_statement = parse_statement(rebound_envelope)
            require(
                rebound_statement["sighash"] == transaction_sighash,
                "fixture did not bind the requested transaction sighash",
            )
            require(
                rebound_statement["anchor"] == original_statement["anchor"]
                and rebound_statement["nullifiers"] == original_statement["nullifiers"]
                and rebound_statement["commitments"] == original_statement["commitments"]
                and rebound_statement["value_balance"] == funding_amount,
                "custom-sighash proof changed another public bundle field",
            )
            transaction.shielded_bundle.proof = rebound_envelope
            transaction.sign_all_inputs(owner.private_key, owner.public_key)
            chain.shielded_anchors.add(original_statement["anchor"], 0)
            require(
                transaction.get_canonical_sighash() == transaction_sighash,
                "signing or proof attachment changed the transaction sighash",
            )
            require(chain.validate_transaction(transaction, validation_height=1),
                    "node consensus rejected an honest transaction-bound proof")

            transaction.timestamp += 1
            changed_sighash = transaction.get_canonical_sighash()
            malicious_envelope = bytearray(rebound_envelope)
            sighash_offset = (
                len(PROOF_MAGIC)
                + 2
                + 32
                + len(rebound_statement["nullifiers"]) * 32
                + len(rebound_statement["commitments"]) * 32
                + 8
            )
            malicious_envelope[sighash_offset : sighash_offset + 32] = changed_sighash
            transaction.shielded_bundle.proof = bytes(malicious_envelope)
            transaction.sign_all_inputs(owner.private_key, owner.public_key)
            require(not chain.validate_transaction(transaction, validation_height=1),
                    "node consensus accepted a proof rebound to another transaction")
            chain.conn.close()
    finally:
        B.PRIVACY_CONSENSUS_ENABLED = old_enabled
        B.SHIELDED_ACTIVATION_HEIGHT = old_activation
        S.register_verifier(S.RejectAllVerifier(), audit_approved=False)

    wrong_digest = bytearray(digest)
    wrong_digest[0] ^= 1
    require(not boundary.verify(bytes(wrong_digest), envelope),
            "proof was accepted for the wrong statement digest")

    tampered_envelope = bytearray(envelope)
    proof_start = raw_proof_offset(envelope)
    tampered_envelope[proof_start + (len(envelope) - proof_start) // 2] ^= 1
    require(not boundary.verify(digest, bytes(tampered_envelope)),
            "tampered Winterfell proof was accepted")

    wrong_outer = bytearray(request)
    wrong_outer[len(REQUEST_MAGIC)] ^= 1
    require(run_verifier(bytes(wrong_outer)).returncode != 0,
            "outer statement tampering was accepted")
    require(run_verifier(request[:-1]).returncode != 0,
            "truncated request was accepted")
    require(run_verifier(request + b"\x00").returncode != 0,
            "request with trailing bytes was accepted")

    length_offset = len(REQUEST_MAGIC) + 32
    wrong_length = bytearray(request)
    wrong_length[length_offset : length_offset + 4] = struct.pack(
        "<I", len(envelope) + 1
    )
    require(run_verifier(bytes(wrong_length)).returncode != 0,
            "incorrect envelope length was accepted")

    oversized_length = 1024 * 1024 + 1
    oversized = (
        REQUEST_MAGIC
        + b"\x00" * 32
        + struct.pack("<I", oversized_length)
        + b"\x00" * oversized_length
    )
    require(run_verifier(oversized).returncode != 0,
            "oversized request was accepted")

    # Deterministically sample the whole request, including framing, public
    # fields, proof metadata, and the Winterfell proof body. Every single-bit
    # mutation must fail closed and remain silent.
    positions = sorted({
        index * (len(request) - 1) // 63 for index in range(64)
    })
    for position in positions:
        mutated = bytearray(request)
        mutated[position] ^= 1
        result = run_verifier(bytes(mutated))
        require(result.returncode != 0,
                f"single-bit mutation at byte {position} was accepted")
        require(result.stdout == b"" and result.stderr == b"",
                f"mutation at byte {position} produced verifier output")

    # Exercise parser boundaries without trusting the producer's encoder. This
    # corpus is deterministic so a failure is exactly reproducible on another
    # runner and every case reaches the real release-mode Rust executable.
    envelope_start = len(REQUEST_MAGIC) + 32 + 4
    proof_length_offset = envelope_start + raw_proof_offset(envelope) - 4
    spend_count_offset = envelope_start + len(PROOF_MAGIC)
    output_count_offset = spend_count_offset + 1
    value_balance_offset = (
        output_count_offset
        + 1
        + 32
        + envelope[len(PROOF_MAGIC)] * 32
        + envelope[len(PROOF_MAGIC) + 1] * 32
    )

    hostile_cases: list[tuple[str, bytes]] = []
    truncation_points = {
        0,
        1,
        len(REQUEST_MAGIC) - 1,
        len(REQUEST_MAGIC),
        len(REQUEST_MAGIC) + 31,
        len(REQUEST_MAGIC) + 32,
        envelope_start - 1,
        envelope_start,
        spend_count_offset,
        output_count_offset,
        value_balance_offset,
        proof_length_offset,
        proof_start + envelope_start,
        len(request) - 1,
    }
    for cutoff in sorted(truncation_points):
        hostile_cases.append((f"truncated-at-{cutoff}", request[:cutoff]))

    for declared_length in (0, 1, len(envelope) - 1, len(envelope) + 1, 0xFFFFFFFF):
        candidate = bytearray(request)
        candidate[length_offset : length_offset + 4] = struct.pack(
            "<I", declared_length
        )
        hostile_cases.append((f"outer-length-{declared_length}", bytes(candidate)))

    for offset, label, values in (
        (spend_count_offset, "spend-count", (5, 0xFF)),
        (output_count_offset, "output-count", (3, 0xFF)),
    ):
        for value in values:
            candidate = bytearray(request)
            candidate[offset] = value
            hostile_cases.append((f"{label}-{value}", bytes(candidate)))

    for value in (-(1 << 63), -(1 << 61), 1 << 61, (1 << 63) - 1):
        candidate = bytearray(request)
        candidate[value_balance_offset : value_balance_offset + 8] = struct.pack(
            "<q", value
        )
        hostile_cases.append((f"value-balance-{value}", bytes(candidate)))

    raw_proof_length = len(envelope) - raw_proof_offset(envelope)
    for declared_length in (0, 1, raw_proof_length - 1, raw_proof_length + 1, 0xFFFFFFFF):
        candidate = bytearray(request)
        candidate[proof_length_offset : proof_length_offset + 4] = struct.pack(
            "<I", declared_length
        )
        hostile_cases.append((f"raw-proof-length-{declared_length}", bytes(candidate)))

    rng = random.Random(0x5745504F)
    random_sizes = (0, 1, 20, 21, 32, 56, 57, 128, 1024, 4096)
    for index in range(64):
        size = random_sizes[index % len(random_sizes)]
        hostile_cases.append((f"random-{index}-size-{size}", rng.randbytes(size)))

    require(
        len(hostile_cases) == 96,
        f"adversarial corpus contract changed: {len(hostile_cases)} cases",
    )
    for label, hostile_request in hostile_cases:
        result = run_verifier(hostile_request)
        require(result.returncode != 0, f"{label} was accepted")
        require(
            result.stdout == b"" and result.stderr == b"",
            f"{label} produced verifier output",
        )

    # Run maximum-sized invalid requests concurrently. This exercises the
    # bounded stdin read and process isolation under pressure without embedding
    # an unbounded workload in the maintained suite.
    max_sized_invalid = REQUEST_MAGIC + bytes(32) + struct.pack(
        "<I", 1024 * 1024
    ) + b"X" * (1024 * 1024)
    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent_results = list(
            executor.map(run_verifier, [max_sized_invalid] * 8)
        )
    for index, result in enumerate(concurrent_results):
        require(result.returncode != 0, f"concurrent max request {index} was accepted")
        require(result.stdout == b"" and result.stderr == b"",
                f"concurrent max request {index} produced verifier output")

    post_corpus = run_verifier(request)
    require(post_corpus.returncode == 0,
            "honest proof failed after adversarial verifier corpus")
    require(post_corpus.stdout == b"" and post_corpus.stderr == b"",
            "post-corpus honest proof produced verifier output")

    bad_magic = bytearray(request)
    bad_magic[0] ^= 1
    rejected = run_verifier(bytes(bad_magic))
    require(rejected.returncode != 0, "bad request magic was accepted")
    require(rejected.stdout == b"" and rejected.stderr == b"",
            "invalid proof produced verifier output")

    print("Ghost verifier integration: ALL CHECKS PASSED")


def test_regression_suite():
    main()


if __name__ == "__main__":
    main()
