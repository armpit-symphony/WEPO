# Ghost verifier subprocess protocol

Status: Python/node boundary, complete Rust Winterfell CLI, versioned proof
envelope, and honest cross-runtime proof integration implemented 2026-07-28.
A deterministic real-executable adversarial baseline now covers structural,
random, maximum-size, concurrent, tampered-proof, crash, and timeout cases.
Long-running coverage-guided fuzzing, intended-host resource qualification, and
independent audit remain required. Privacy consensus and shipping feature flags
remain disabled. See `GHOST_VERIFIER_ADVERSARIAL_TESTING.md`.

## Security boundary

The verifier runs out of process because malformed Winterfell proof metadata can
panic. A panic, crash, timeout, missing executable, invalid request, or any
nonzero exit fails closed and is treated as an invalid proof.

The node invokes an explicit argument vector with `shell=False`. The command is
configured as JSON in `WEPO_SHIELDED_VERIFIER_COMMAND_JSON`; shell command
strings are rejected. The child receives no stdout or stderr pipe into node
memory.

Development may use a JSON argument vector for harnesses. An enabled release is
stricter: `SHIELDED_VERIFIER_RELEASE_AUDIT_APPROVED` must be set in reviewed
source, `SHIELDED_VERIFIER_RELEASE_SHA256` must contain the independently
audited artifact digest, and the configured command must resolve to exactly one
regular executable with no arguments or interpreter indirection. The node
rehashes that executable at startup and before every proof, and refuses startup
or verification if the audit flag, activation height, command, file, or digest
is missing or invalid. The release artifact and its containing directory must
also be administrator/root-owned and non-writable by the node service account to close
the replacement window after startup.

## Request framing

One process verifies one proof. The node writes exactly:

| Field | Size | Encoding |
|---|---:|---|
| Magic | 21 bytes | ASCII `WEPO_GHOST_VERIFY_V1` followed by `0x00` |
| Statement digest | 32 bytes | Raw `bundle.statement_digest(sighash)` |
| Proof length | 4 bytes | Unsigned little-endian |
| Proof | `proof_length` bytes | Versioned Ghost proof envelope |

The verifier must reject:

- wrong or truncated magic;
- a statement digest of any length other than 32 bytes;
- a truncated or overflowing length;
- a proof length above the configured consensus/runtime limit;
- empty proofs;
- trailing bytes after the declared proof; and
- proofs for any circuit other than the complete five-condition Ghost bundle
  circuit.

The Python boundary defaults to a 1 MiB proof limit and a 5-second wall-clock
timeout. It admits at most two verifier children concurrently by default; a
saturated boundary returns invalid without spawning or waiting. Configuration
must remain from 1 through 16. Operators may lower these values with
`WEPO_SHIELDED_VERIFIER_MAX_PROOF_BYTES` and
`WEPO_SHIELDED_VERIFIER_TIMEOUT_SECONDS`, or select concurrency with
`WEPO_SHIELDED_VERIFIER_MAX_CONCURRENT`. Raising any value is a release
parameter change that requires rehearsal and review.

The production node cgroup additionally enforces `TasksMax=128`,
`CPUQuota=200%`, `MemoryHigh=60%`, and `MemoryMax=75%` across the node and all
verifier children. Intended-host resource qualification remains required.

The Rust verifier preflights untrusted Winterfell proof metadata before vector
reservation. A 2026-08-01 libFuzzer run found the previous top-level path could
request about 15 GB of allocation from malformed proof metadata; the bounded
reader rejects that class before allocation. A retained verifier fuzz run then
found a nested `BatchMerkleProof` allocation path inside FRI query metadata after
10,369 executions; the verifier now preflights nested Merkle proof byte buffers
before handing them to Winterfell. Parser panics are still contained as invalid
proofs by the subprocess and verifier catch boundary, and extended resource
qualification remains required before any activation decision.

## Versioned Ghost proof envelope

The outer proof field is not an unstructured Winterfell blob. It is the
following envelope, whose magic selects only the complete five-condition
circuit:

| Field | Size | Encoding |
|---|---:|---|
| Magic | 20 bytes | ASCII `WEPO_GHOST_PROOF_V1` followed by `0x00` |
| Spend count | 1 byte | Unsigned; `0..4` |
| Output count | 1 byte | Unsigned; `0..2` |
| Anchor | 32 bytes | Four canonical little-endian Goldilocks limbs |
| Nullifiers | `32 * spends` | Public nullifiers in transaction order |
| Commitments | `32 * outputs` | Public output commitments in transaction order |
| Value balance | 8 bytes | Signed little-endian, bounded by `2^61-1` |
| Sighash | 32 bytes | Raw transaction signature hash |
| Winterfell proof length | 4 bytes | Unsigned little-endian |
| Winterfell proof | declared length | Complete-bundle proof bytes |

The verifier rejects empty bundles, more than four spends, more than two
outputs, values outside the 61-bit bound, non-canonical field limbs, empty or
oversized proofs, truncated fields, and trailing bytes.

The envelope contains only public transaction data. It contains no note values,
spending keys, paths, or other witness data. The verifier recomputes
`bundle.statement_digest(sighash)` from these fields, compares it to the digest
supplied by the node, and then verifies the raw proof with the bundle fields and
an injective five-Goldilocks-element encoding of the 32-byte sighash as
Winterfell public inputs. Both layers are required: the envelope binds the
node/verifier protocol, while the STARK public input prevents an attacker from
rewriting the sighash, recomputing the outer digest, and reusing a raw proof.

## Response

The protocol has no response body:

- exit `0`: proof valid for the supplied statement;
- any nonzero exit: invalid proof or verifier failure.

The Rust CLI should emit diagnostics only to its own bounded operational log,
never include witness data, and never rely on stdout/stderr for the consensus
result.

## Audit gate

Registering a verifier no longer marks it audited. `register_verifier()` defaults
to `audit_approved=False`; the explicit audit state is separate and is cleared
when `RejectAllVerifier` is restored.

Setting an environment variable never grants audit approval. The approval flag
and expected executable digest are source-controlled release parameters, and
ordinary `WepoBlockchain` construction also refuses enabled consensus unless an
audited verifier is already registered.

No production code should pass `audit_approved=True` until:

1. the Rust CLI verifies the complete membership, nullifier, authority, range,
   and balance circuit;
2. Rust/Python vectors and real proof fixtures pass;
3. malformed-proof and resource-exhaustion testing passes;
4. the bundle layout and proof-size policy are frozen; and
5. an independent cryptographic review closes all critical and high findings.

Even after those conditions, privacy consensus and client feature gates require
a separate explicit enablement decision.
