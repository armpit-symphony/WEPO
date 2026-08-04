#!/usr/bin/env python3
"""Reproduce decision evidence for relay fee, maturity, and emission policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
WALLET_VECTOR = ROOT / "tests" / "vectors" / "wallet_signing_v3.json"
EMISSION_VECTOR = ROOT / "tests" / "vectors" / "emission_schedule_v1.json"
COIN = 100_000_000
MAX_BLOCK_SIZE = 2 * 1024 * 1024


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_to_wepo(value: int) -> str:
    whole, fraction = divmod(value, COIN)
    return f"{whole}.{fraction:08d}"


def required_fee(rate_atomic_per_kb: int, canonical_bytes: int) -> int:
    return (rate_atomic_per_kb * canonical_bytes + 999) // 1000


def build_evidence() -> dict:
    wallet = json.loads(WALLET_VECTOR.read_text(encoding="utf-8"))
    emission = json.loads(EMISSION_VECTOR.read_text(encoding="utf-8"))

    signed_payload_hex = wallet["expected"]["signed_transaction_payload_utf8_hex"]
    canonical_bytes = len(bytes.fromhex(signed_payload_hex))
    default_fee = int(wallet["unsigned_tx"]["fee"])
    max_compatible_rate = default_fee * 1000 // canonical_bytes
    candidate_rates = (0, 100, 1000, max_compatible_rate, max_compatible_rate + 1)
    fee_candidates = []
    for rate in candidate_rates:
        required = required_fee(rate, canonical_bytes)
        fee_candidates.append(
            {
                "rate_atomic_per_kb": rate,
                "required_fee_atomic": required,
                "required_fee_wepo": atomic_to_wepo(required),
                "default_fee_passes": default_fee >= required,
                "default_fee_headroom_atomic": default_fee - required,
            }
        )

    maturity_candidates = []
    for depth in (50, 100, 200):
        maturity_candidates.append(
            {
                "blocks": depth,
                "pre_pos_minutes_at_6m": depth * 6,
                "hybrid_fast_minutes_at_3m": depth * 3,
                "hybrid_slow_minutes_at_9m": depth * 9,
            }
        )

    parameters = emission["parameters"]
    expected = emission["expected"]
    cap = int(parameters["hard_cap_atomic"])
    pow_total = int(expected["pow_total_atomic"])
    maximum = int(expected["maximum_qualifying_issuance_atomic"])
    no_eligible = int(expected["no_eligible_pos_recipients_atomic"])
    shortfall = int(expected["cap_shortfall_atomic"])

    return {
        "schema": "wepo-mainnet-parameter-decision-evidence-v1",
        "source_vectors": {
            "wallet_signing_v3_sha256": file_sha256(WALLET_VECTOR),
            "emission_schedule_v1_sha256": file_sha256(EMISSION_VECTOR),
        },
        "relay_fee": {
            "representative_transaction": {
                "description": "committed one-input/two-output ML-DSA wallet vector",
                "canonical_bytes": canonical_bytes,
                "default_fee_atomic": default_fee,
                "default_fee_wepo": atomic_to_wepo(default_fee),
                "maximum_compatible_rate_atomic_per_kb": max_compatible_rate,
                "transparent_transactions_per_2mib_upper_bound": (
                    MAX_BLOCK_SIZE // canonical_bytes
                ),
            },
            "candidate_rates": fee_candidates,
            "compatible_round_candidate_atomic_per_kb": 1000,
            "caveat": (
                "This vector proves compatibility for its exact shape only; wallets "
                "must calculate fees from final canonical bytes for larger inputs or metadata."
            ),
        },
        "coinbase_maturity": {
            "candidates": maturity_candidates,
            "conservative_candidate_blocks": 100,
            "candidate_time_envelope": {
                "pre_pos_minutes": 600,
                "hybrid_fast_minutes": 300,
                "hybrid_slow_minutes": 900,
            },
            "caveat": (
                "Elapsed time is descriptive, not consensus; maturity is counted in "
                "canonical blocks and must be reviewed against reorg and pool behavior."
            ),
        },
        "emission": {
            "hard_cap_atomic": str(cap),
            "hard_cap_wepo": atomic_to_wepo(cap),
            "maximum_qualifying_issuance_atomic": str(maximum),
            "maximum_qualifying_issuance_wepo": atomic_to_wepo(maximum),
            "maximum_path_shortfall_atomic": str(shortfall),
            "maximum_path_shortfall_wepo": atomic_to_wepo(shortfall),
            "no_eligible_pos_issuance_atomic": str(no_eligible),
            "no_eligible_pos_issuance_wepo": atomic_to_wepo(no_eligible),
            "no_eligible_pos_shortfall_atomic": str(cap - no_eligible),
            "no_eligible_pos_shortfall_wepo": atomic_to_wepo(cap - no_eligible),
            "pow_total_atomic": str(pow_total),
            "last_nonzero_pos_height": expected["last_nonzero_pos_height"],
            "cap_reachable_under_current_schedule": expected["cap_reachable"],
            "implemented_policy": "ceiling_only",
            "exact_target_requirements": [
                "scheduled qualifying issuance must be at least the hard cap",
                "unpaid or ineligible reward treatment must be deterministic and reorg-safe",
                "every valid continuing-chain path needs an eventually payable issuance recipient",
                "the final payout must clamp exactly to remaining cap headroom",
                "new cross-runtime vectors and independent review are required",
            ],
            "finding": (
                "The current schedule cannot guarantee an exact terminal supply; even "
                "its maximum qualifying path ends below the hard cap."
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        type=Path,
        help="compare the derived document with a committed JSON file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = build_evidence()
    if args.check is not None:
        try:
            committed = json.loads(args.check.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"INVALID EVIDENCE FILE: {exc}\n")
            return 2
        if committed != evidence:
            sys.stderr.write("DECISION EVIDENCE MISMATCH\n")
            return 2
        sys.stdout.write("DECISION EVIDENCE MATCH\n")
        return 0
    sys.stdout.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
