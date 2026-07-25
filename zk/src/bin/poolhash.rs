//! The WEPO shielded-pool hash under Rescue-Prime, as a line-oriented service.
//!
//! This is the node's production hashing path until the tree/anchor refactor
//! (Phase 2 option 2) lands. Python keeps one of these alive and does a
//! write-line / read-line round trip per digest, which amortises the ~4.5 ms
//! process spawn that made naive per-hash shelling out hopeless.
//!
//!   pool_hash(B) = as_bytes( hash_elements( encode_bytes_as_field_elements(B) ) )
//!
//! Deliberately uses `hash_elements`, never `Rp64_256::hash()`: the latter
//! panics for every input length > 56 that is not a multiple of 7, and a node
//! hash input is ~103 bytes. See `rescue_len_probe`.
//!
//! Protocol: one hex-encoded input per line on stdin, one hex-encoded 32-byte
//! digest per line on stdout, flushed per line so it works as a live service.
//! Malformed input yields `ERR` -- never a plausible-looking digest.

use std::io::{self, BufRead, Write};

use winterfell::{
    crypto::{hashers::Rp64_256, Digest, ElementHasher},
    math::fields::f64::BaseElement,
};

/// 7 bytes per element, not 8: a full 64-bit chunk can exceed p and would need
/// reduction, which is not injective. The leading length element keeps the
/// final chunk's zero padding distinguishable from real trailing zero bytes.
const FELT_BYTES: usize = 7;

fn encode_bytes_as_field_elements(data: &[u8]) -> Vec<BaseElement> {
    let mut out = Vec::with_capacity(1 + data.len() / FELT_BYTES + 1);
    out.push(BaseElement::new(data.len() as u64));
    for chunk in data.chunks(FELT_BYTES) {
        let mut buf = [0u8; 8];
        buf[..chunk.len()].copy_from_slice(chunk);
        out.push(BaseElement::new(u64::from_le_bytes(buf)));
    }
    out
}

fn pool_hash(data: &[u8]) -> [u8; 32] {
    let elements = encode_bytes_as_field_elements(data);
    Rp64_256::hash_elements(&elements).as_bytes()
}

fn unhex(s: &str) -> Option<Vec<u8>> {
    let s = s.trim();
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}

fn hex(b: &[u8]) -> String {
    use std::fmt::Write as _;
    let mut s = String::with_capacity(b.len() * 2);
    for x in b {
        let _ = write!(s, "{x:02x}");
    }
    s
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        // NOTE: an empty line is a valid request -- it means "hash empty bytes",
        // which is exactly what register_hash_algorithm probes with. Strictly
        // one line in, one line out; skipping blanks would desynchronise the
        // request/response pairing for a persistent client.
        match unhex(&line) {
            Some(bytes) => {
                let _ = writeln!(out, "{}", hex(&pool_hash(&bytes)));
            },
            None => {
                let _ = writeln!(out, "ERR");
            },
        }
        // flush per line: this runs as a live request/response service
        let _ = out.flush();
    }
}
