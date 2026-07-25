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

# Binary location. Overridable for deployment, but the known-answer test above
# runs against whatever this resolves to, so pointing it at the wrong binary
# fails loudly at startup rather than producing wrong roots at runtime.
_ENV_VAR = "WEPO_POOLHASH_BIN"


class RescueBackendError(RuntimeError):
    """Raised when the Rescue hashing backend cannot be trusted."""


def _default_binary() -> Path:
    root = Path(__file__).resolve().parents[2]
    name = "poolhash.exe" if os.name == "nt" else "poolhash"
    return root / "zk" / "target" / "release" / name


def binary_path() -> Path:
    override = os.environ.get(_ENV_VAR)
    return Path(override) if override else _default_binary()


class PoolHasher:
    """One long-lived `poolhash` process, serialised by a lock."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else binary_path()
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
        got = self._exchange(proc, _KAT_INPUT)
        if got != _KAT_DIGEST:
            proc.kill()
            raise RescueBackendError(
                f"{self._path} failed the known-answer test; refusing to use it.\n"
                f"  input  {_KAT_INPUT!r}\n"
                f"  got    {got.hex()}\n"
                f"  want   {_KAT_DIGEST.hex()}\n"
                "A binary that disagrees here would corrupt every commitment in "
                "the pool."
            )

    # -- the exchange -------------------------------------------------------

    @staticmethod
    def _exchange(proc: subprocess.Popen, data: bytes) -> bytes:
        if proc.stdin is None or proc.stdout is None:
            raise RescueBackendError("hashing process has no pipes")
        try:
            proc.stdin.write(data.hex() + "\n")
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

    def digest(self, data: bytes) -> bytes:
        with self._lock:
            proc = self._ensure()
            return self._exchange(proc, data)

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


_DEFAULT = PoolHasher()


def rescue_pool_hash(data: bytes) -> bytes:
    """pool_hash(B) = as_bytes(hash_elements(encode_bytes_as_field_elements(B)))."""
    return _DEFAULT.digest(data)


def available() -> bool:
    """True if the backend can be used. Never raises — for probing only."""
    try:
        rescue_pool_hash(b"")
        return True
    except RescueBackendError:
        return False


def close() -> None:
    _DEFAULT.close()
