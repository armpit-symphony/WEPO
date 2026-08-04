#!/usr/bin/env python3
"""Isolated, anti-equivocation ML-DSA signer for WEPO PoS validators.

The full node invokes this program once per request through the bounded
``SubprocessValidatorSigner`` protocol.  In production it must run as a
dedicated OS account whose key and state files are unreadable and unwritable by
the node account.  The signer validates the complete canonical PoS signing
payload and refuses to authorize two different blocks at the same height.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


CORE = Path(__file__).resolve().parents[1] / "core"
sys.path.insert(0, str(CORE))
with contextlib.redirect_stdout(sys.stderr):
    from address_utils import generate_wepo_address
    from dilithium import (
        DILITHIUM_PRIVKEY_SIZE,
        DILITHIUM_PUBKEY_SIZE,
        DILITHIUM_SIGNATURE_SIZE,
        generate_dilithium_keypair,
        sign_with_dilithium,
        verify_dilithium_signature,
    )

from stake_transaction_policy import (
    AUTHORIZATION_FORMAT,
    StakeAuthorization,
    StakePolicyRefusal,
    validate_stake_authorization,
)


PROTOCOL_VERSION = 3
KEY_FORMAT = "wepo-validator-key-v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_SIGNING_PAYLOAD_BYTES = 16 * 1024
POS_DOMAIN = b"WEPO_POS_BLOCK_SIGNATURE_V1\x00"
HEADER_DOMAIN = b"WEPO_BLOCK_HEADER_V2\x00"


class SignerRefusal(RuntimeError):
    """A request is invalid or conflicts with previously authorized state."""


@dataclass(frozen=True)
class ValidatorKey:
    network: str
    validator_address: str
    public_key: bytes
    private_key: bytes


@dataclass(frozen=True)
class ParsedSigningPayload:
    network: str
    height: int
    previous_block_hash: str
    validator_address: str
    validator_public_key: bytes


def _decode_exact_hex(value: object, size: int, name: str) -> bytes:
    if not isinstance(value, str) or len(value) != size * 2:
        raise SignerRefusal(f"invalid {name}")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise SignerRefusal(f"invalid {name}") from exc
    if len(decoded) != size:
        raise SignerRefusal(f"invalid {name}")
    return decoded


def _require_private_file(path: Path, *, allow_insecure_permissions: bool) -> None:
    if not path.is_file() or path.is_symlink():
        raise SignerRefusal("key file must be a regular non-symlink file")
    if os.name == "posix" and not allow_insecure_permissions:
        if (
            not path.parent.is_dir()
            or path.parent.is_symlink()
            or path.parent.stat().st_mode & 0o077
        ):
            raise SignerRefusal("key directory must be a private real directory")
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise SignerRefusal("key file must not grant group or other permissions")
    elif os.name != "posix" and not allow_insecure_permissions:
        raise SignerRefusal("production signer permission checks require a POSIX host")


def load_validator_key(
    path: Path,
    expected_network: str,
    *,
    allow_insecure_permissions: bool = False,
) -> ValidatorKey:
    _require_private_file(path, allow_insecure_permissions=allow_insecure_permissions)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SignerRefusal("unable to read validator key") from exc
    if len(raw) > 32 * 1024:
        raise SignerRefusal("validator key file is oversized")
    try:
        document = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SignerRefusal("validator key file is invalid") from exc
    if not isinstance(document, dict) or set(document) != {
        "format",
        "network",
        "validator_address",
        "public_key",
        "private_key",
    }:
        raise SignerRefusal("validator key file schema is invalid")
    if document["format"] != KEY_FORMAT or document["network"] != expected_network:
        raise SignerRefusal("validator key file has the wrong format or network")
    address = document["validator_address"]
    if not isinstance(address, str) or not address or len(address) > 128:
        raise SignerRefusal("validator address is invalid")
    public_key = _decode_exact_hex(document["public_key"], DILITHIUM_PUBKEY_SIZE, "public key")
    private_key = _decode_exact_hex(document["private_key"], DILITHIUM_PRIVKEY_SIZE, "private key")
    if generate_wepo_address(public_key, address_type="quantum") != address:
        raise SignerRefusal("validator public key does not own the configured address")
    self_test = b"WEPO_VALIDATOR_SIGNER_KEYPAIR_SELF_TEST_V1\x00"
    signature = sign_with_dilithium(self_test, private_key)
    if not verify_dilithium_signature(self_test, signature, public_key):
        raise SignerRefusal("validator public and private keys do not match")
    return ValidatorKey(expected_network, address, public_key, private_key)


def initialize_validator_key(path: Path, network: str) -> dict[str, str]:
    if not network or not network.isascii() or len(network) > 32:
        raise SignerRefusal("network name is invalid")
    keypair = generate_dilithium_keypair()
    address = generate_wepo_address(keypair.public_key, address_type="quantum")
    document = {
        "format": KEY_FORMAT,
        "network": network,
        "validator_address": address,
        "public_key": keypair.public_key.hex(),
        "private_key": keypair.private_key.hex(),
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    serialized = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise SignerRefusal("refusing to overwrite validator key file") from exc
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return {"network": network, "validator_address": address, "public_key": keypair.public_key.hex()}


class _Cursor:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    def take(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.payload):
            raise SignerRefusal("signing payload is truncated")
        value = self.payload[self.offset : self.offset + length]
        self.offset += length
        return value

    def length_prefixed(self, maximum: int) -> bytes:
        length = struct.unpack("<I", self.take(4))[0]
        if length > maximum:
            raise SignerRefusal("signing payload field is oversized")
        return self.take(length)


def parse_signing_payload(payload: bytes) -> ParsedSigningPayload:
    if not payload or len(payload) > MAX_SIGNING_PAYLOAD_BYTES:
        raise SignerRefusal("signing payload size is invalid")
    cursor = _Cursor(payload)
    if cursor.take(len(POS_DOMAIN)) != POS_DOMAIN:
        raise SignerRefusal("signing payload domain is invalid")
    try:
        network = cursor.length_prefixed(32).decode("ascii", errors="strict")
    except UnicodeError as exc:
        raise SignerRefusal("signing payload network is invalid") from exc
    height = struct.unpack("<Q", cursor.take(8))[0]
    if cursor.take(len(HEADER_DOMAIN)) != HEADER_DOMAIN:
        raise SignerRefusal("block-header domain is invalid")
    version, previous_hash, _merkle_root, _timestamp, bits, nonce = struct.unpack(
        "<I32s32sQII", cursor.take(struct.calcsize("<I32s32sQII"))
    )
    try:
        consensus = cursor.length_prefixed(16).decode("ascii", errors="strict")
        address = cursor.length_prefixed(128).decode("ascii", errors="strict")
    except UnicodeError as exc:
        raise SignerRefusal("block-header text is invalid") from exc
    public_key = cursor.length_prefixed(DILITHIUM_PUBKEY_SIZE)
    validator_signature = cursor.length_prefixed(DILITHIUM_SIGNATURE_SIZE)
    if cursor.offset != len(payload):
        raise SignerRefusal("signing payload has trailing bytes")
    if version != 1 or consensus != "pos" or bits != 0 or nonce != 0:
        raise SignerRefusal("signing payload is not a canonical PoS header")
    if len(public_key) != DILITHIUM_PUBKEY_SIZE or validator_signature:
        raise SignerRefusal("signing payload validator fields are invalid")
    return ParsedSigningPayload(
        network=network,
        height=height,
        previous_block_hash=previous_hash.hex(),
        validator_address=address,
        validator_public_key=public_key,
    )


class AntiEquivocationStore:
    def __init__(self, path: Path, *, allow_insecure_permissions: bool = False):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise SignerRefusal("signer state directory must be a real directory")
        if os.name == "posix" and not allow_insecure_permissions:
            if path.parent.stat().st_mode & 0o077:
                raise SignerRefusal(
                    "signer state directory must not grant group or other permissions"
                )
            if path.exists() and (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_mode & 0o077
            ):
                raise SignerRefusal(
                    "signer state database must be a private regular file"
                )
        elif os.name != "posix" and not allow_insecure_permissions:
            raise SignerRefusal(
                "production signer state checks require a POSIX host"
            )
        self.connection = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS signed_blocks (
                network TEXT NOT NULL,
                validator_address TEXT NOT NULL,
                height INTEGER NOT NULL,
                previous_block_hash TEXT NOT NULL,
                message BLOB NOT NULL,
                signature BLOB NOT NULL,
                PRIMARY KEY (network, validator_address, height)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS stake_authorizations (
                network TEXT NOT NULL,
                validator_address TEXT NOT NULL,
                sighash BLOB NOT NULL,
                operation TEXT NOT NULL,
                stake_id TEXT NOT NULL,
                transaction_json TEXT NOT NULL,
                input_utxos_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('approved', 'signed')),
                signature BLOB,
                PRIMARY KEY (network, validator_address, sighash)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS stake_authorized_outpoints (
                network TEXT NOT NULL,
                validator_address TEXT NOT NULL,
                prev_txid TEXT NOT NULL,
                prev_vout INTEGER NOT NULL,
                sighash BLOB NOT NULL,
                PRIMARY KEY (network, validator_address, prev_txid, prev_vout),
                FOREIGN KEY (network, validator_address, sighash)
                    REFERENCES stake_authorizations
                    (network, validator_address, sighash)
            )"""
        )
        self.connection.execute("PRAGMA foreign_keys=ON")
        if os.name == "posix":
            os.chmod(path, 0o600)

    def authorize(
        self,
        key: ValidatorKey,
        parsed: ParsedSigningPayload,
        message: bytes,
    ) -> bytes:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                """SELECT previous_block_hash, message, signature
                   FROM signed_blocks
                   WHERE network = ? AND validator_address = ? AND height = ?""",
                (key.network, key.validator_address, parsed.height),
            ).fetchone()
            if existing is not None:
                previous_hash, stored_message, stored_signature = existing
                if previous_hash != parsed.previous_block_hash or bytes(stored_message) != message:
                    raise SignerRefusal("anti-equivocation refusal: height already signed")
                self.connection.execute("COMMIT")
                return bytes(stored_signature)
            highest = self.connection.execute(
                """SELECT MAX(height) FROM signed_blocks
                   WHERE network = ? AND validator_address = ?""",
                (key.network, key.validator_address),
            ).fetchone()[0]
            if highest is not None and parsed.height < highest:
                raise SignerRefusal("anti-equivocation refusal: stale unsigned height")
            signature = sign_with_dilithium(message, key.private_key)
            self.connection.execute(
                """INSERT INTO signed_blocks
                   (network, validator_address, height, previous_block_hash, message, signature)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    key.network,
                    key.validator_address,
                    parsed.height,
                    parsed.previous_block_hash,
                    message,
                    signature,
                ),
            )
            self.connection.execute("COMMIT")
            return signature
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


    def approve_stake(self, authorization: StakeAuthorization) -> str:
        """Persist one exact operator-reviewed transaction before signing."""
        transaction_json = authorization.canonical_transaction_json
        input_utxos_json = authorization.canonical_utxos_json
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                """SELECT operation, stake_id, transaction_json, input_utxos_json, status
                   FROM stake_authorizations
                   WHERE network = ? AND validator_address = ? AND sighash = ?""",
                (
                    authorization.network,
                    authorization.validator_address,
                    authorization.sighash,
                ),
            ).fetchone()
            if existing is not None:
                if existing[:4] != (
                    authorization.operation,
                    authorization.stake_id,
                    transaction_json,
                    input_utxos_json,
                ):
                    raise SignerRefusal("stake authorization digest conflicts with stored policy")
                self.connection.execute("COMMIT")
                return str(existing[4])
            self.connection.execute(
                """INSERT INTO stake_authorizations
                   (network, validator_address, sighash, operation, stake_id,
                    transaction_json, input_utxos_json, status, signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', NULL)""",
                (
                    authorization.network,
                    authorization.validator_address,
                    authorization.sighash,
                    authorization.operation,
                    authorization.stake_id,
                    transaction_json,
                    input_utxos_json,
                ),
            )
            for prev_txid, prev_vout in authorization.outpoints:
                self.connection.execute(
                    """INSERT INTO stake_authorized_outpoints
                       (network, validator_address, prev_txid, prev_vout, sighash)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        authorization.network,
                        authorization.validator_address,
                        prev_txid,
                        prev_vout,
                        authorization.sighash,
                    ),
                )
            self.connection.execute("COMMIT")
            return "approved"
        except sqlite3.IntegrityError as exc:
            self.connection.execute("ROLLBACK")
            raise SignerRefusal(
                "stake authorization conflicts with an already authorized outpoint"
            ) from exc
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def sign_stake(self, key: ValidatorKey, authorization: StakeAuthorization) -> bytes:
        """Sign only an exact approved intent and make retries idempotent."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """SELECT operation, stake_id, transaction_json, input_utxos_json,
                          status, signature
                   FROM stake_authorizations
                   WHERE network = ? AND validator_address = ? AND sighash = ?""",
                (key.network, key.validator_address, authorization.sighash),
            ).fetchone()
            expected = (
                authorization.operation,
                authorization.stake_id,
                authorization.canonical_transaction_json,
                authorization.canonical_utxos_json,
            )
            if row is None or row[:4] != expected:
                raise SignerRefusal("stake transaction has no exact operator authorization")
            if row[4] == "signed":
                if row[5] is None:
                    raise SignerRefusal("signed stake authorization has no retained signature")
                self.connection.execute("COMMIT")
                return bytes(row[5])
            signature = sign_with_dilithium(authorization.sighash, key.private_key)
            updated = self.connection.execute(
                """UPDATE stake_authorizations
                   SET status = 'signed', signature = ?
                   WHERE network = ? AND validator_address = ? AND sighash = ?
                     AND status = 'approved'""",
                (signature, key.network, key.validator_address, authorization.sighash),
            ).rowcount
            if updated != 1:
                raise SignerRefusal("stake authorization changed during signing")
            self.connection.execute("COMMIT")
            return signature
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

class ProductionValidatorSigner:
    def __init__(
        self,
        key: ValidatorKey,
        state_path: Path,
        *,
        allow_insecure_permissions: bool = False,
    ):
        self.key = key
        self.store = AntiEquivocationStore(
            state_path,
            allow_insecure_permissions=allow_insecure_permissions,
        )
    def approve_stake(self, document: object) -> tuple[StakeAuthorization, str]:
        try:
            authorization = validate_stake_authorization(
                document,
                expected_network=self.key.network,
                validator_address=self.key.validator_address,
            )
        except StakePolicyRefusal as exc:
            raise SignerRefusal(str(exc)) from exc
        return authorization, self.store.approve_stake(authorization)


    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
            raise SignerRefusal("request protocol is invalid")
        operation = request.get("operation")
        if operation == "public_key":
            if set(request) != {"version", "operation", "validator_address"}:
                raise SignerRefusal("public-key request schema is invalid")
            if request["validator_address"] != self.key.validator_address:
                raise SignerRefusal("validator address is not configured")
            return {"version": PROTOCOL_VERSION, "ok": True, "public_key": self.key.public_key.hex()}
        if operation == "sign_stake_transaction":
            if set(request) != {
                "version", "operation", "validator_address", "network",
                "sighash", "unsigned_tx", "input_utxos",
            }:
                raise SignerRefusal("stake sign request schema is invalid")
            if request["validator_address"] != self.key.validator_address:
                raise SignerRefusal("validator address is not configured")
            if request["network"] != self.key.network:
                raise SignerRefusal("stake sign request network is invalid")
            document = {
                "format": AUTHORIZATION_FORMAT,
                "network": request["network"],
                "validator_address": request["validator_address"],
                "unsigned_tx": request["unsigned_tx"],
                "input_utxos": request["input_utxos"],
                "sighash": request["sighash"],
            }
            try:
                authorization = validate_stake_authorization(
                    document,
                    expected_network=self.key.network,
                    validator_address=self.key.validator_address,
                )
            except StakePolicyRefusal as exc:
                raise SignerRefusal(str(exc)) from exc
            signature = self.store.sign_stake(self.key, authorization)
            return {
                "version": PROTOCOL_VERSION,
                "ok": True,
                "sighash": authorization.sighash.hex(),
                "signature": signature.hex(),
            }

        if operation != "sign" or set(request) != {
            "version",
            "operation",
            "validator_address",
            "network",
            "block_height",
            "previous_block_hash",
            "message",
            "signing_payload",
        }:
            raise SignerRefusal("sign request schema is invalid")
        if request["validator_address"] != self.key.validator_address:
            raise SignerRefusal("validator address is not configured")
        if request["network"] != self.key.network:
            raise SignerRefusal("sign request network is invalid")
        if type(request["block_height"]) is not int or not 0 <= request["block_height"] <= 0x7FFFFFFFFFFFFFFF:
            raise SignerRefusal("sign request height is invalid")
        message = _decode_exact_hex(request["message"], 32, "signing message")
        if not isinstance(request["signing_payload"], str) or len(request["signing_payload"]) > MAX_SIGNING_PAYLOAD_BYTES * 2:
            raise SignerRefusal("signing payload is invalid")
        try:
            payload = bytes.fromhex(request["signing_payload"])
        except ValueError as exc:
            raise SignerRefusal("signing payload is invalid") from exc
        parsed = parse_signing_payload(payload)
        if hashlib.sha3_256(payload).digest() != message:
            raise SignerRefusal("signing payload digest does not match")
        if (
            parsed.network != request["network"]
            or parsed.height != request["block_height"]
            or parsed.previous_block_hash != request["previous_block_hash"]
            or parsed.validator_address != request["validator_address"]
            or parsed.validator_public_key != self.key.public_key
        ):
            raise SignerRefusal("sign request context does not match its payload")
        signature = self.store.authorize(self.key, parsed, message)
        return {"version": PROTOCOL_VERSION, "ok": True, "signature": signature.hex()}


def _read_one_request(stream: BinaryIO) -> object:
    raw = stream.readline(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES or stream.read(1):
        raise SignerRefusal("request framing is invalid")
    try:
        return json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SignerRefusal("request JSON is invalid") from exc


def _write_response(response: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read_authorization_file(path: Path) -> object:
    if not path.is_file() or path.is_symlink():
        raise SignerRefusal("stake authorization must be a regular non-symlink file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SignerRefusal("unable to read stake authorization") from exc
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise SignerRefusal("stake authorization file size is invalid")
    try:
        return json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SignerRefusal("stake authorization JSON is invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="WEPO isolated validator signer")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--network", required=True)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--init-key", action="store_true")
    parser.add_argument("--authorize-stake-request", type=Path)
    parser.add_argument("--allow-insecure-permissions-for-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.init_key:
            if (
                args.stdio
                or args.authorize_stake_request is not None
                or args.state_db is not None
                or args.key_file is None
            ):
                raise SignerRefusal("key initialization arguments are invalid")
            public = initialize_validator_key(args.key_file, args.network)
            _write_response({"ok": True, **public})
            return 0
        if (
            args.key_file is None
            or args.state_db is None
            or args.stdio == (args.authorize_stake_request is not None)
        ):
            raise SignerRefusal("signer arguments are invalid")
        key = load_validator_key(
            args.key_file,
            args.network,
            allow_insecure_permissions=args.allow_insecure_permissions_for_test,
        )
        signer = ProductionValidatorSigner(
            key,
            args.state_db,
            allow_insecure_permissions=args.allow_insecure_permissions_for_test,
        )
        if args.authorize_stake_request is not None:
            authorization, status = signer.approve_stake(
                _read_authorization_file(args.authorize_stake_request)
            )
            _write_response({
                "version": PROTOCOL_VERSION,
                "ok": True,
                "authorization_format": AUTHORIZATION_FORMAT,
                "network": authorization.network,
                "validator_address": authorization.validator_address,
                "operation": authorization.operation,
                "stake_id": authorization.stake_id,
                "sighash": authorization.sighash.hex(),
                "status": status,
            })
            return 0
        _write_response(signer.handle(_read_one_request(sys.stdin.buffer)))
        return 0
    except SignerRefusal as exc:
        print(f"validator signer refused request: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"validator signer failed closed: {type(exc).__name__}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
