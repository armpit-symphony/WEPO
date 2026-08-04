#!/usr/bin/env python3
"""Fail-closed validator signing boundary for WEPO PoS block production.

The blockchain process never receives a validator private key. A configured
signer is invoked once per operation using a small JSON request/response
protocol over stdin/stdout.
"""

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Sequence

try:
    from .dilithium import DILITHIUM_PUBKEY_SIZE, DILITHIUM_SIGNATURE_SIZE
except ImportError:
    from dilithium import DILITHIUM_PUBKEY_SIZE, DILITHIUM_SIGNATURE_SIZE


PROTOCOL_VERSION = 3
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 64 * 1024
MAX_SIGNING_MESSAGE_BYTES = 4096
MAX_VALIDATOR_ADDRESS_CHARS = 128
SIGNER_COMMAND_ENV = "WEPO_VALIDATOR_SIGNER_COMMAND_JSON"


class ValidatorSignerError(RuntimeError):
    """A signer operation failed without exposing signer-internal details."""


@dataclass(frozen=True)
class PosSigningContext:
    """Canonical block context required by an anti-equivocation signer."""

    network: str
    block_height: int
    previous_block_hash: str
    signing_payload: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.network, str)
            or not self.network
            or len(self.network) > 32
            or not self.network.isascii()
        ):
            raise ValueError("PoS signing network must be non-empty ASCII")
        if type(self.block_height) is not int or not 0 <= self.block_height <= 0x7FFFFFFFFFFFFFFF:
            raise ValueError("PoS signing height is invalid")
        if not isinstance(self.previous_block_hash, str) or len(self.previous_block_hash) != 64:
            raise ValueError("PoS signing parent hash is invalid")
        try:
            previous_hash = bytes.fromhex(self.previous_block_hash)
        except ValueError as exc:
            raise ValueError("PoS signing parent hash is invalid") from exc
        if len(previous_hash) != 32:
            raise ValueError("PoS signing parent hash is invalid")
        if not isinstance(self.signing_payload, bytes) or not self.signing_payload:
            raise ValueError("PoS signing payload is invalid")
        if len(self.signing_payload) > MAX_SIGNING_MESSAGE_BYTES * 4:
            raise ValueError("PoS signing payload is too large")

@dataclass(frozen=True)
class _BoundedProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    output_exceeded_limit: bool


class ValidatorSigner(Protocol):
    """Minimal signing capability consumed by block-production code."""

    def get_public_key(self, validator_address: str) -> bytes:
        """Return the validator's ML-DSA-44 public key."""

    def sign(
        self,
        validator_address: str,
        message: bytes,
        *,
        context: PosSigningContext,
    ) -> bytes:
        """Sign one canonical PoS message without exporting the private key."""

    def sign_stake_transaction(
        self,
        validator_address: str,
        unsigned_tx: Mapping[str, object],
        input_utxos: Sequence[Mapping[str, object]],
        network: str,
        sighash: str,
    ) -> bytes:
        """Sign one pre-authorized, policy-checked stake transaction."""



@dataclass(frozen=True)
class SubprocessValidatorSigner:
    """Invoke a validator signer with no shell and a bounded JSON protocol."""

    command: Sequence[str]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = MAX_RESPONSE_BYTES
    environment: Optional[Mapping[str, str]] = None

    def __post_init__(self) -> None:
        command = tuple(self.command)
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("Validator signer command must contain non-empty arguments")
        if self.timeout_seconds <= 0:
            raise ValueError("Validator signer timeout must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("Validator signer response limit must be positive")
        object.__setattr__(self, "command", command)

    def _subprocess_environment(self) -> Mapping[str, str]:
        if self.environment is not None:
            return dict(self.environment)

        allowed_names = (
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "LANG",
            "LC_ALL",
        )
        return {name: os.environ[name] for name in allowed_names if name in os.environ}

    def _run_bounded(self, request_bytes: bytes) -> _BoundedProcessResult:
        """Run one signer request without ever retaining unbounded child output."""
        process = subprocess.Popen(
            list(self.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            env=self._subprocess_environment(),
        )
        streams = (process.stdout, process.stderr)
        if process.stdin is None or any(stream is None for stream in streams):
            process.kill()
            process.wait()
            raise OSError("Validator signer pipes were not created")

        retained = [bytearray(), bytearray()]
        exceeded = threading.Event()

        def drain(index: int) -> None:
            stream = streams[index]
            assert stream is not None
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    remaining = self.max_response_bytes + 1 - len(retained[index])
                    if remaining > 0:
                        retained[index].extend(chunk[:remaining])
                    if len(retained[index]) > self.max_response_bytes:
                        exceeded.set()
                        try:
                            process.kill()
                        except OSError:
                            pass
            finally:
                stream.close()

        readers = [
            threading.Thread(target=drain, args=(index,), daemon=True)
            for index in range(2)
        ]
        for reader in readers:
            reader.start()

        try:
            process.stdin.write(request_bytes)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            # A signer may reject and exit before consuming all of stdin.
            try:
                process.stdin.close()
            except OSError:
                pass

        try:
            returncode = process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            for reader in readers:
                reader.join()
            raise

        for reader in readers:
            reader.join()
        return _BoundedProcessResult(
            returncode=returncode,
            stdout=bytes(retained[0]),
            stderr=bytes(retained[1]),
            output_exceeded_limit=exceeded.is_set(),
        )

    def _request(self, operation: str, validator_address: str, **fields) -> dict:
        if (
            not isinstance(validator_address, str)
            or not validator_address
            or len(validator_address) > MAX_VALIDATOR_ADDRESS_CHARS
        ):
            raise ValidatorSignerError("Validator signer request is invalid")
        try:
            validator_address.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValidatorSignerError("Validator signer request is invalid") from exc

        request = {
            "version": PROTOCOL_VERSION,
            "operation": operation,
            "validator_address": validator_address,
            **fields,
        }
        request_bytes = (
            json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")

        try:
            completed = self._run_bounded(request_bytes)
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise ValidatorSignerError("Validator signer invocation failed") from exc

        if completed.output_exceeded_limit:
            raise ValidatorSignerError("Validator signer output exceeded the limit")
        if completed.returncode != 0:
            raise ValidatorSignerError("Validator signer rejected the request")

        try:
            response = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (json.JSONDecodeError, TypeError, UnicodeError) as exc:
            raise ValidatorSignerError("Validator signer returned invalid JSON") from exc

        if (
            not isinstance(response, dict)
            or response.get("version") != PROTOCOL_VERSION
            or response.get("ok") is not True
        ):
            raise ValidatorSignerError("Validator signer returned an invalid response")
        return response

    @staticmethod
    def _decode_exact_hex(value, expected_size: int, field_name: str) -> bytes:
        if not isinstance(value, str) or len(value) != expected_size * 2:
            raise ValidatorSignerError(f"Validator signer returned an invalid {field_name}")
        try:
            decoded = bytes.fromhex(value)
        except ValueError as exc:
            raise ValidatorSignerError(
                f"Validator signer returned an invalid {field_name}"
            ) from exc
        if len(decoded) != expected_size:
            raise ValidatorSignerError(f"Validator signer returned an invalid {field_name}")
        return decoded

    def get_public_key(self, validator_address: str) -> bytes:
        response = self._request("public_key", validator_address)
        return self._decode_exact_hex(
            response.get("public_key"),
            DILITHIUM_PUBKEY_SIZE,
            "public key",
        )

    def sign(
        self,
        validator_address: str,
        message: bytes,
        *,
        context: PosSigningContext,
    ) -> bytes:
        if (
            not isinstance(message, (bytes, bytearray))
            or not message
            or len(message) > MAX_SIGNING_MESSAGE_BYTES
        ):
            raise ValidatorSignerError("Validator signing message is invalid")
        if not isinstance(context, PosSigningContext):
            raise ValidatorSignerError("Validator signing context is invalid")
        if len(context.signing_payload) > MAX_SIGNING_MESSAGE_BYTES * 4:
            raise ValidatorSignerError("Validator signing payload is invalid")
        import hashlib
        if hashlib.sha3_256(context.signing_payload).digest() != bytes(message):
            raise ValidatorSignerError(
                "Validator signing payload does not match its message"
            )
        response = self._request(
            "sign",
            validator_address,
            message=bytes(message).hex(),
            network=context.network,
            block_height=context.block_height,
            previous_block_hash=context.previous_block_hash,
            signing_payload=context.signing_payload.hex(),
        )
        return self._decode_exact_hex(
            response.get("signature"),
            DILITHIUM_SIGNATURE_SIZE,
            "signature",
        )

    def sign_stake_transaction(
        self,
        validator_address: str,
        unsigned_tx: Mapping[str, object],
        input_utxos: Sequence[Mapping[str, object]],
        network: str,
        sighash: str,
    ) -> bytes:
        """Request one signature for every same-owner input in a stake tx.

        The isolated signer independently reconstructs the canonical sighash,
        validates the stake-only value-flow policy, and requires an exact
        operator authorization already present in its private state database.
        """
        if not isinstance(unsigned_tx, Mapping) or not isinstance(input_utxos, Sequence):
            raise ValidatorSignerError("Validator stake signing context is invalid")
        if (
            not isinstance(network, str)
            or not network
            or len(network) > 32
            or not network.isascii()
        ):
            raise ValidatorSignerError("Validator stake signing network is invalid")
        if not isinstance(sighash, str) or len(sighash) != 64:
            raise ValidatorSignerError("Validator stake signing sighash is invalid")
        try:
            bytes.fromhex(sighash)
        except ValueError as exc:
            raise ValidatorSignerError("Validator stake signing sighash is invalid") from exc
        if isinstance(input_utxos, (str, bytes, bytearray)):
            raise ValidatorSignerError("Validator stake signing context is invalid")
        if any(not isinstance(item, Mapping) for item in input_utxos):
            raise ValidatorSignerError("Validator stake signing context is invalid")
        try:
            tx_document = json.loads(json.dumps(dict(unsigned_tx)))
            utxo_document = json.loads(json.dumps([dict(item) for item in input_utxos]))
        except (TypeError, ValueError) as exc:
            raise ValidatorSignerError("Validator stake signing context is invalid") from exc
        response = self._request(
            "sign_stake_transaction",
            validator_address,
            unsigned_tx=tx_document,
            network=network,
            sighash=sighash.lower(),
            input_utxos=utxo_document,
        )
        return self._decode_exact_hex(
            response.get("signature"),
            DILITHIUM_SIGNATURE_SIZE,
            "signature",
        )


def load_validator_signer_from_env() -> Optional[SubprocessValidatorSigner]:
    """Load the configured signer command from an explicit JSON argv array."""
    raw_command = os.getenv(SIGNER_COMMAND_ENV, "").strip()
    if not raw_command:
        return None

    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError as exc:
        raise ValidatorSignerError(
            f"{SIGNER_COMMAND_ENV} must be a JSON array of command arguments"
        ) from exc
    if not isinstance(command, list):
        raise ValidatorSignerError(
            f"{SIGNER_COMMAND_ENV} must be a JSON array of command arguments"
        )

    timeout_raw = os.getenv("WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS", "").strip()
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError as exc:
        raise ValidatorSignerError(
            "WEPO_VALIDATOR_SIGNER_TIMEOUT_SECONDS must be numeric"
        ) from exc

    return SubprocessValidatorSigner(command=command, timeout_seconds=timeout)
