"""Import BEFORE `shielded` to make the shielded tests runnable without Rust.

The hash swap made `shielded.py` fail hard when the Rust hashing binaries are
missing. That is correct for a node — a node that cannot hash correctly must not
start. But it also stopped this repository from running its own shielded tests
on any machine without a Rust toolchain, including CI runners.

Those are two different failures wearing the same clothes:

    falling back to SHA3          -> DIFFERENT digests -> silent chain split
    falling back to pure Rescue   -> IDENTICAL digests -> ~1000x slower

The first must stay forbidden. The second is an availability problem, not a
consensus one: every digest is bit-identical, the tests verify exactly what they
verified before, they just take longer.

So this shim opts in to the pure-Python path *only* when the binaries are
genuinely absent. If they are present it does nothing, and the tests run against
Rust as normal — which matters, because the oracle's independence depends on the
node and the oracle being different implementations.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_ENV = "WEPO_POOLHASH_PURE_PYTHON"


def _binary(stem: str) -> Path:
    name = f"{stem}.exe" if os.name == "nt" else stem
    return REPO / "zk" / "target" / "release" / name


def rust_backend_available() -> bool:
    return _binary("poolhash").exists() and _binary("fieldhash").exists()


def using_pure_python() -> bool:
    return os.environ.get(_ENV) == "1"


if not rust_backend_available() and not using_pure_python():
    os.environ[_ENV] = "1"
    print(
        "[backend shim] Rust hashing binaries not found under zk/target/release.\n"
        "[backend shim] Falling back to pure-Python Rescue: identical digests,\n"
        "[backend shim] roughly 1000x slower. Build them with:\n"
        "[backend shim]   cargo build --release --bin poolhash --bin fieldhash\n",
        file=sys.stderr,
    )
