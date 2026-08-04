#!/usr/bin/env python3
"""Fail-closed subprocess boundary for WEPO Ghost bundle verification."""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence


PROTOCOL_MAGIC = b"WEPO_GHOST_VERIFY_V1\x00"
STATEMENT_DIGEST_BYTES = 32
MAX_PROOF_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CONCURRENT_PROCESSES = 2
MAX_CONCURRENT_PROCESSES_LIMIT = 16
VERIFIER_COMMAND_ENV = "WEPO_SHIELDED_VERIFIER_COMMAND_JSON"

# These are release-source gates, never environment switches. They remain
# closed until an independent audit approves a reproducible verifier artifact.
SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED = False
SHIELDED_VERIFIER_RELEASE_SHA256: Optional[str] = None



@dataclass(frozen=True)
class SubprocessShieldedVerifier:
    """Verify one Ghost proof in an isolated process.

    Request framing:
        magic || statement_digest[32] || proof_len_le_u32 || proof

    Exit 0 means valid. Every other exit, exception, timeout, malformed input,
    or missing executable means invalid. The child has no stdout/stderr channel
    back into node memory.
    """

    command: Sequence[str]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_proof_bytes: int = MAX_PROOF_BYTES
    environment: Optional[Mapping[str, str]] = None
    expected_executable_sha256: Optional[str] = None
    max_concurrent_processes: int = DEFAULT_MAX_CONCURRENT_PROCESSES
    _process_slots: threading.BoundedSemaphore = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        command = tuple(self.command)
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("Shielded verifier command must contain non-empty arguments")
        if self.timeout_seconds <= 0:
            raise ValueError("Shielded verifier timeout must be positive")
        if not 0 < self.max_proof_bytes <= 0xFFFFFFFF:
            raise ValueError("Shielded verifier proof limit is invalid")
        if (
            type(self.max_concurrent_processes) is not int
            or not 1 <= self.max_concurrent_processes <= MAX_CONCURRENT_PROCESSES_LIMIT
        ):
            raise ValueError("Shielded verifier concurrency limit is invalid")
        if self.expected_executable_sha256 is not None and (
            len(self.expected_executable_sha256) != 64
            or any(
                char not in "0123456789abcdef"
                for char in self.expected_executable_sha256
            )
        ):
            raise ValueError("Shielded verifier executable SHA-256 is invalid")
        object.__setattr__(self, "command", command)
        object.__setattr__(
            self, "_process_slots", threading.BoundedSemaphore(self.max_concurrent_processes)
        )

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

    def verify(self, statement_digest: bytes, proof: bytes) -> bool:
        if (
            not isinstance(statement_digest, (bytes, bytearray))
            or len(statement_digest) != STATEMENT_DIGEST_BYTES
            or not isinstance(proof, (bytes, bytearray))
            or not proof
            or len(proof) > self.max_proof_bytes
        ):
            return False

        if self.expected_executable_sha256 is not None:
            if len(self.command) != 1:
                return False
            try:
                actual_digest = _sha256_file(self.command[0])
            except OSError:
                return False
            if actual_digest != self.expected_executable_sha256:
                return False

        proof = bytes(proof)
        request = (
            PROTOCOL_MAGIC
            + bytes(statement_digest)
            + struct.pack("<I", len(proof))
            + proof
        )
        if not self._process_slots.acquire(blocking=False):
            return False
        try:
            completed = subprocess.run(
                list(self.command),
                input=request,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                close_fds=True,
                env=self._subprocess_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            self._process_slots.release()
        return completed.returncode == 0


def load_shielded_verifier_from_env() -> Optional[SubprocessShieldedVerifier]:
    """Load an explicit JSON argv array; never interpret a shell command."""
    raw_command = os.getenv(VERIFIER_COMMAND_ENV, "").strip()
    if not raw_command:
        return None
    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{VERIFIER_COMMAND_ENV} must be a JSON array of command arguments"
        ) from exc
    if not isinstance(command, list):
        raise ValueError(
            f"{VERIFIER_COMMAND_ENV} must be a JSON array of command arguments"
        )

    timeout_raw = os.getenv("WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS", "").strip()
    proof_limit_raw = os.getenv("WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES", "").strip()
    concurrency_raw = os.getenv("WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT", "").strip()
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
        proof_limit = int(proof_limit_raw) if proof_limit_raw else MAX_PROOF_BYTES
        concurrency = int(concurrency_raw) if concurrency_raw else DEFAULT_MAX_CONCURRENT_PROCESSES
    except ValueError as exc:
        raise ValueError("Shielded verifier numeric configuration is invalid") from exc

    return SubprocessShieldedVerifier(
        command=command,
        timeout_seconds=timeout,
        max_proof_bytes=proof_limit,
        max_concurrent_processes=concurrency,
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as executable:
        while True:
            chunk = executable.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_release_shielded_verifier_from_env(
    *,
    audit_approved: bool = SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED,
    expected_sha256: Optional[str] = SHIELDED_VERIFIER_RELEASE_SHA256,
) -> SubprocessShieldedVerifier:
    """Load the exact independently audited verifier artifact.

    The general loader remains useful for development and tests. Consensus
    activation uses this stricter boundary: source-controlled audit approval,
    one direct executable (no interpreter/shell/arguments), and a pinned digest.
    """
    if audit_approved is not True:
        raise RuntimeError(
            "shielded consensus cannot start before release audit approval"
        )
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
    ):
        raise RuntimeError("audited shielded verifier SHA-256 is not frozen")

    verifier = load_shielded_verifier_from_env()
    if verifier is None:
        raise RuntimeError(f"{VERIFIER_COMMAND_ENV} is required for shielded consensus")
    if len(verifier.command) != 1:
        raise RuntimeError(
            "release shielded verifier must be one direct executable with no arguments"
        )

    configured_path = verifier.command[0]
    if os.path.dirname(configured_path):
        resolved_path = os.path.realpath(os.path.abspath(configured_path))
    else:
        discovered = shutil.which(configured_path)
        if not discovered:
            raise RuntimeError("configured shielded verifier executable was not found")
        resolved_path = os.path.realpath(discovered)

    if not os.path.isfile(resolved_path) or not os.access(resolved_path, os.X_OK):
        raise RuntimeError("configured shielded verifier is not an executable regular file")
    actual_sha256 = _sha256_file(resolved_path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError("configured shielded verifier does not match audited SHA-256")

    return SubprocessShieldedVerifier(
        command=(resolved_path,),
        timeout_seconds=verifier.timeout_seconds,
        max_proof_bytes=verifier.max_proof_bytes,
        environment=verifier.environment,
        expected_executable_sha256=expected_sha256,
    )
