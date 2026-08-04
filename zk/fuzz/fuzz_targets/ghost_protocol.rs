#![no_main]

use libfuzzer_sys::fuzz_target;
use wepo_zk::ghost::protocol::{parse_envelope, parse_request, statement_digest};

fuzz_target!(|data: &[u8]| {
    // Exercise both parsers independently because an envelope can arrive only
    // after request framing in production, while each parser has its own length
    // and allocation boundaries.
    let _ = parse_envelope(data);

    if let Some((declared_digest, envelope_bytes)) = parse_request(data) {
        if let Some(envelope) = parse_envelope(envelope_bytes) {
            // Recompute the public statement digest on every fully parsed case.
            // Equality is not asserted: mismatches are valid rejected inputs for
            // the verifier, while panics, overflows, and unsafe allocations are
            // always fuzzing failures.
            let _ = declared_digest == statement_digest(&envelope.statement);
        }
    }
});
