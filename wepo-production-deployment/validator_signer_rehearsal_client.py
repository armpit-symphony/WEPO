#!/usr/bin/env python3
"""Unprivileged client for the disposable Linux validator-signer rehearsal."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path


POS_DOMAIN = b"WEPO_POS_BLOCK_SIGNATURE_V1\x00"
HEADER_DOMAIN = b"WEPO_BLOCK_HEADER_V2\x00"


def length_prefixed(value: bytes) -> bytes:
    return struct.pack("<I", len(value)) + value


def signing_payload(
    network: str,
    address: str,
    public_key: bytes,
    *,
    height: int,
    previous_hash: str,
    merkle_byte: int,
) -> bytes:
    header = (
        HEADER_DOMAIN
        + struct.pack(
            "<I32s32sQII",
            1,
            bytes.fromhex(previous_hash),
            bytes([merkle_byte]) * 32,
            1_800_000_000 + height,
            0,
            0,
        )
        + length_prefixed(b"pos")
        + length_prefixed(address.encode("ascii"))
        + length_prefixed(public_key)
        + length_prefixed(b"")
    )
    network_bytes = network.encode("ascii")
    return POS_DOMAIN + length_prefixed(network_bytes) + struct.pack("<Q", height) + header


def invoke(command: list[str], request: dict[str, object], *, expect_success: bool) -> dict[str, object]:
    completed = subprocess.run(
        command,
        input=(json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    if expect_success:
        if completed.returncode != 0:
            raise RuntimeError(f"signer failed closed unexpectedly: rc={completed.returncode}")
        response = json.loads(completed.stdout.decode("ascii"))
        if response.get("version") != 3 or response.get("ok") is not True:
            raise RuntimeError("signer returned an invalid success response")
        return response
    if completed.returncode == 0:
        raise RuntimeError("conflicting signer request was accepted")
    if b"anti-equivocation refusal" not in completed.stderr:
        raise RuntimeError("conflicting request failed for the wrong reason")
    return {"returncode": completed.returncode}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-json", required=True)
    parser.add_argument("--public-metadata", type=Path, required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--core-dir", type=Path, required=True)
    args = parser.parse_args()

    command = json.loads(args.command_json)
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise RuntimeError("signer command is not an explicit JSON argv array")
    if "--allow-insecure-permissions-for-test" in command:
        raise RuntimeError("test-only permission bypass is forbidden")

    with args.public_metadata.open(encoding="utf-8") as source:
        public = json.load(source)
    if public["network"] != args.network:
        raise RuntimeError("public metadata network mismatch")
    address = public["validator_address"]
    public_key = bytes.fromhex(public["public_key"])

    public_response = invoke(
        command,
        {"version": 3, "operation": "public_key", "validator_address": address},
        expect_success=True,
    )
    if bytes.fromhex(public_response["public_key"]) != public_key:
        raise RuntimeError("public-key query mismatch")

    previous_hash = f"{args.height % 256:02x}" * 32
    payload = signing_payload(
        args.network,
        address,
        public_key,
        height=args.height,
        previous_hash=previous_hash,
        merkle_byte=0x44,
    )
    message = hashlib.sha3_256(payload).hexdigest()
    request = {
        "version": 3,
        "operation": "sign",
        "validator_address": address,
        "network": args.network,
        "block_height": args.height,
        "previous_block_hash": previous_hash,
        "message": message,
        "signing_payload": payload.hex(),
    }
    first = invoke(command, request, expect_success=True)
    retry = invoke(command, request, expect_success=True)
    if first["signature"] != retry["signature"]:
        raise RuntimeError("idempotent retry returned a different signature")

    conflicting_payload = signing_payload(
        args.network,
        address,
        public_key,
        height=args.height,
        previous_hash=previous_hash,
        merkle_byte=0x55,
    )
    conflicting_request = dict(request)
    conflicting_request["message"] = hashlib.sha3_256(conflicting_payload).hexdigest()
    conflicting_request["signing_payload"] = conflicting_payload.hex()
    refusal = invoke(command, conflicting_request, expect_success=False)

    sys.path.insert(0, str(args.core_dir))
    with contextlib.redirect_stdout(sys.stderr):
        from dilithium import verify_dilithium_signature  # pylint: disable=import-outside-toplevel

    signature = bytes.fromhex(first["signature"])
    if not verify_dilithium_signature(bytes.fromhex(message), signature, public_key):
        raise RuntimeError("returned signature failed independent verification")

    print(
        json.dumps(
            {
                "height": args.height,
                "idempotent_retry": True,
                "conflict_refused": True,
                "conflict_returncode": refusal["returncode"],
                "signature_bytes": len(signature),
                "signature_sha256": hashlib.sha256(signature).hexdigest(),
                "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
