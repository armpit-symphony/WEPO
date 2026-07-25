"""Rescue-Prime pool hashing for the node, by delegation to the Rust binary.

Phase 2 measured all three ways of giving Python a Rescue digest:

    Rescue in pure Python              853,570 ns/hash   (28.5 min per 1M-note rebuild)
    subprocess spawn per hash        4,509,837 ns/hash   (4.5 ms of spawn, per hash)
    persistent subprocess, this file    28,129 ns/hash   (measured, end to end)
    same binary, pipelined in bulk       6,771 ns/hash
    native Rust (the eventual answer)     3,921 ns/hash

Pure Python is disqualified by two orders of magnitude and spawn-per-hash by
three. What makes delegation viable is keeping **one** process alive, which
amortises the spawn to nothing.

Note the gap between the two subprocess rows. 6,771 ns is *pipelined* throughput
-- thousands of inputs streamed in with no per-hash synchronisation. This class
pays a synchronous round trip per digest instead (write, flush, readline), which
costs ~28 us regardless of how fast the hash itself is. That is the price of
fitting behind `HashAlgorithm.fn`, which is a one-digest-at-a-time interface.

The obvious next optimisation is a batch entry point: tree layer rebuilds and
block anchor validation both hash many independent inputs at once, and issuing
those as one write of N lines followed by N reads would recover most of the 4x.
That needs a structural change to how `NoteCommitmentTree` hashes, so it is
deliberately not part of the atomic hash swap.

This is the interim. The long-term answer is Phase 2 option 2 — move tree and
anchor maintenance into Rust so there is one implementation and no boundary at
all. That is a project of its own; this exists so the hash swap can land before
genesis without waiting for a consensus refactor.

Fails closed, always. Any error — missing binary, dead process, malformed reply,
wrong digest length — raises. There is no path here that returns a plausible
digest it did not compute.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

HASH_LEN = 32

# Known-answer test, run against the binary before it is trusted.
#
# This is the guard against a stale or wrong binary silently corrupting every
# commitment in the pool. The digest is pinned here, cross-validated three ways:
# winter-crypto's Rust, an independent pure-Python implementation
# (tests/rescue_reference.py), and that implementation's agreement with the
# upstream Sage reference vector.
_KAT_INPUT = b"abc"
_KAT_DIGEST = bytes.fromhex(
    "734f4ad1787930bd85e4e9a07469a6169b2ff3322ed35422a7ec3ee23aa15cff"
)

# Same guard for the field-native service: H_dom(domain=1, elements=[1]).
_FIELD_KAT_REQUEST = "1:0100000000000000"
_FIELD_KAT_DIGEST = bytes.fromhex(
    "a027e36598687d9207f5d5c3370b352c3f891c313771bcb459821d69e3f87914"
)

# Binary location. Overridable for deployment, but the known-answer test above
# runs against whatever this resolves to, so pointing it at the wrong binary
# fails loudly at startup rather than producing wrong roots at runtime.
_ENV_VAR = "WEPO_POOLHASH_BIN"


class RescueBackendError(RuntimeError):
    """Raised when the Rescue hashing backend cannot be trusted."""


def _default_binary(stem: str = "poolhash") -> Path:
    root = Path(__file__).resolve().parents[2]
    name = f"{stem}.exe" if os.name == "nt" else stem
    return root / "zk" / "target" / "release" / name


def binary_path(stem: str = "poolhash") -> Path:
    override = os.environ.get(_ENV_VAR if stem == "poolhash" else f"WEPO_{stem.upper()}_BIN")
    return Path(override) if override else _default_binary(stem)


class PoolHasher:
    """One long-lived hashing process, serialised by a lock.

    Drives either `poolhash` (byte-oriented, for the bundle statement digest)
    or `fieldhash` (domain-separated field-native, for everything in-circuit).
    The request line format differs; the trust model does not.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        kat_request: str = "",
        kat_digest: bytes = b"",
    ):
        self._path = Path(path) if path else binary_path()
        self._kat_request = kat_request
        self._kat_digest = kat_digest
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    # -- process management -------------------------------------------------

    def _spawn(self) -> subprocess.Popen:
        if not self._path.exists():
            raise RescueBackendError(
                f"Rescue hashing binary not found at {self._path}. "
                f"Build it with: cargo build --release --bin poolhash "
                f"(or set {_ENV_VAR})"
            )
        try:
            proc = subprocess.Popen(
                [str(self._path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,  # line buffered
            )
        except OSError as exc:
            raise RescueBackendError(f"cannot start {self._path}: {exc}") from exc
        return proc

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = self._spawn()
            self._self_test(self._proc)
        return self._proc

    def _self_test(self, proc: subprocess.Popen) -> None:
        """Refuse to use a binary that does not reproduce the known answer."""
        got = self._exchange(proc, self._kat_request)
        if got != self._kat_digest:
            proc.kill()
            raise RescueBackendError(
                f"{self._path} failed the known-answer test; refusing to use it.\n"
                f"  request {self._kat_request!r}\n"
                f"  got     {got.hex()}\n"
                f"  want    {self._kat_digest.hex()}\n"
                "A binary that disagrees here would corrupt every commitment in "
                "the pool."
            )

    # -- the exchange -------------------------------------------------------

    @staticmethod
    def _exchange(proc: subprocess.Popen, request: str) -> bytes:
        if proc.stdin is None or proc.stdout is None:
            raise RescueBackendError("hashing process has no pipes")
        try:
            proc.stdin.write(request + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise RescueBackendError(f"hashing process died: {exc}") from exc

        if not line:
            raise RescueBackendError(
                "hashing process closed its output; it may have panicked"
            )
        line = line.strip()
        if line == "ERR":
            raise RescueBackendError("hashing process rejected the input")
        try:
            digest = bytes.fromhex(line)
        except ValueError as exc:
            raise RescueBackendError(f"malformed reply {line!r}") from exc
        if len(digest) != HASH_LEN:
            raise RescueBackendError(
                f"expected {HASH_LEN}-byte digest, got {len(digest)}"
            )
        return digest

    def request(self, line: str) -> bytes:
        with self._lock:
            proc = self._ensure()
            return self._exchange(proc, line)

    def digest(self, data: bytes) -> bytes:
        return self.request(data.hex())

    def close(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    if self._proc.stdin is not None:
                        self._proc.stdin.close()
                    self._proc.wait(timeout=5)
                except Exception:
                    self._proc.kill()
            self._proc = None


_DEFAULT = PoolHasher(
    binary_path("poolhash"), _KAT_INPUT.hex(), _KAT_DIGEST
)

_FIELD = PoolHasher(
    binary_path("fieldhash"), _FIELD_KAT_REQUEST, _FIELD_KAT_DIGEST
)


def rescue_pool_hash(data: bytes) -> bytes:
    """pool_hash(B) = as_bytes(hash_elements(encode_bytes_as_field_elements(B))).

    Byte-oriented. Used only for the bundle statement digest, which is never
    computed inside the circuit.
    """
    return _DEFAULT.digest(data)


def field_hash(domain: int, elements: bytes) -> bytes:
    """H_dom(domain, elements) — the field-native, in-circuit pool hash.

    `elements` is 8*n bytes encoding n little-endian Goldilocks elements, each
    of which must be canonical. Non-canonical limbs are rejected by the backend
    rather than reduced, because reduction is not injective.
    """
    if len(elements) % 8 != 0:
        raise RescueBackendError(
            f"field hash input must be a multiple of 8 bytes, got {len(elements)}"
        )
    return _FIELD.request(f"{domain}:{elements.hex()}")


def available() -> bool:
    """True if the backend can be used. Never raises — for probing only."""
    try:
        rescue_pool_hash(b"")
        field_hash(1, (1).to_bytes(8, "little"))
        return True
    except RescueBackendError:
        return False


def close() -> None:
    _DEFAULT.close()
    _FIELD.close()
