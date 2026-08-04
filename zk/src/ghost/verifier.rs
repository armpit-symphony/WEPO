//! Shared fail-closed verification core used by the production subprocess.

use super::{complete_bundle, protocol};

pub const MAX_REQUEST_BYTES: usize =
    protocol::REQUEST_MAGIC.len() + 32 + 4 + protocol::MAX_PROOF_BYTES;

/// Verify one complete, versioned node-to-verifier request.
///
/// This is the sole in-process entry point used by the production verifier
/// binary and by verifier fuzzing. Framing, statement binding, AIR shape, proof
/// parsing, and Winterfell verification therefore cannot drift between them.
pub fn verify_request(request: &[u8]) -> bool {
    let (expected_digest, encoded_envelope) = match protocol::parse_request(request) {
        Some(value) => value,
        None => return false,
    };
    let envelope = match protocol::parse_envelope(encoded_envelope) {
        Some(value) => value,
        None => return false,
    };
    if protocol::statement_digest(&envelope.statement) != expected_digest {
        return false;
    }
    complete_bundle::production::verify_complete_bundle(
        &envelope.statement.anchor,
        &envelope.statement.nullifiers,
        &envelope.statement.commitments,
        envelope.statement.value_balance,
        &envelope.statement.sighash,
        envelope.raw_proof,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_framing_fails_closed() {
        assert!(!verify_request(b""));
        assert!(!verify_request(protocol::REQUEST_MAGIC));
        assert!(!verify_request(&vec![0u8; MAX_REQUEST_BYTES + 1]));
    }
}
