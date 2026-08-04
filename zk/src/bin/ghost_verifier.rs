//! Fail-closed verifier process for complete WEPO Ghost bundle proofs.
//!
//! Reads one binary request from stdin and communicates the consensus result
//! solely through its exit status: zero means valid, every other status means
//! invalid or verifier failure. It deliberately emits no proof-controlled data.

use std::io::{self, Read};
use std::panic;
use std::process;

use wepo_zk::ghost::verifier::{verify_request, MAX_REQUEST_BYTES};

#[cfg(test)]
use wepo_zk::ghost::{complete_bundle, protocol as ghost_protocol};

fn main() {
    // Winterfell can panic while parsing adversarial proof metadata. The process
    // boundary contains the unwind; suppressing the hook also prevents hostile
    // inputs from turning stderr into an unbounded logging channel.
    panic::set_hook(Box::new(|_| {}));

    let mut request = Vec::new();
    let read_result = io::stdin()
        .take((MAX_REQUEST_BYTES + 1) as u64)
        .read_to_end(&mut request);
    if read_result.is_err() || request.len() > MAX_REQUEST_BYTES || !verify_request(&request) {
        process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_requests_fail_closed() {
        assert!(!verify_request(b""));
        assert!(!verify_request(ghost_protocol::REQUEST_MAGIC));

        let statement = ghost_protocol::PublicStatement {
            anchor: [1u8; 32],
            nullifiers: vec![[2u8; 32]],
            commitments: vec![[3u8; 32]],
            value_balance: 0,
            sighash: [4u8; 32],
        };
        let envelope = ghost_protocol::encode_envelope(&statement, b"not-a-proof").unwrap();
        let digest = ghost_protocol::statement_digest(&statement);
        let request = ghost_protocol::encode_request(&digest, &envelope).unwrap();
        assert!(!verify_request(&request));

        let mut wrong_statement = request;
        wrong_statement[ghost_protocol::REQUEST_MAGIC.len()] ^= 1;
        assert!(!verify_request(&wrong_statement));
    }

    #[test]
    #[cfg_attr(
        debug_assertions,
        ignore = "real Winterfell proof regression runs under cargo test --release"
    )]
    fn proof_cannot_be_rebound_to_another_transaction_sighash() {
        let fixture = complete_bundle::fixture::build();
        let original = ghost_protocol::PublicStatement {
            anchor: fixture.anchor,
            nullifiers: fixture.nullifiers,
            commitments: fixture.commitments,
            value_balance: fixture.value_balance,
            sighash: fixture.sighash,
        };
        let mut rebound = original.clone();
        rebound.sighash[0] ^= 1;
        let envelope = ghost_protocol::encode_envelope(&rebound, &fixture.raw_proof).unwrap();
        let digest = ghost_protocol::statement_digest(&rebound);
        let request = ghost_protocol::encode_request(&digest, &envelope).unwrap();
        assert!(!verify_request(&request));
    }
}
