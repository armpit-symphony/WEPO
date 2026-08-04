//! Domain-separated field-native pool hash, as a line-oriented service.
//!
//!   H_dom(domain, elements):
//!     state           = [0; 12]
//!     state[0]        = elements.len()   // capacity[0], as hash_elements does
//!     state[1]        = domain           // capacity[1], free in the stock sponge
//!     absorb elements into rate (4..12), permuting whenever the rate fills
//!     if anything was absorbed since the last permutation, permute once more
//!     digest          = state[4..8]
//!
//! This is winter-crypto's `hash_elements` with exactly one added assignment.
//! The permutation is untouched, so it is not a new primitive -- but it *is* a
//! new cross-runtime agreement surface, which is why it is pinned by vectors
//! before any AIR is built on it.
//!
//! Why capacity rather than prepending a domain element to the input: a node
//! hash is 8 elements, exactly the rate. Prepending would make it 9, spilling
//! into a second permutation and doubling the cost of the single most repeated
//! operation in the circuit. The capacity elements are already inside the
//! 12-wide state the AIR pays for, so this costs nothing.
//!
//! Protocol: one request per line, `<domain>:<hex>`, where <hex> is 8*n bytes
//! encoding n little-endian field elements, each of which must be canonical
//! (< p). Replies with a 32-byte hex digest, or `ERR`. Flushed per line.

use std::io::{self, BufRead, Write};

use winterfell::{
    crypto::hashers::Rp64_256,
    math::{fields::f64::BaseElement, FieldElement, StarkField},
};

const STATE_WIDTH: usize = 12;
const RATE_START: usize = 4;
const RATE_WIDTH: usize = 8;
const DIGEST_START: usize = 4;
const DIGEST_LEN: usize = 4;

fn h_dom(domain: u64, elements: &[BaseElement]) -> [u8; 32] {
    let mut state = [BaseElement::ZERO; STATE_WIDTH];
    state[0] = BaseElement::new(elements.len() as u64);
    state[1] = BaseElement::new(domain);

    let mut i = 0;
    let mut permuted = false;
    for &e in elements.iter() {
        state[RATE_START + i] += e;
        i += 1;
        if i == RATE_WIDTH {
            Rp64_256::apply_permutation(&mut state);
            permuted = true;
            i = 0;
        }
    }
    // Permute if anything is unabsorbed, and also for an entirely empty input:
    // stock hash_elements would return the untouched state, i.e. an all-zero
    // digest. The empty-subtree ladder starts from an empty leaf, so that zero
    // would become a real anchor value.
    if i > 0 || !permuted {
        Rp64_256::apply_permutation(&mut state);
    }

    let mut out = [0u8; 32];
    for k in 0..DIGEST_LEN {
        out[k * 8..(k + 1) * 8].copy_from_slice(&state[DIGEST_START + k].as_int().to_le_bytes());
    }
    out
}

fn unhex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}

/// Bytes -> canonical field elements, 8 bytes each little-endian.
/// Rejects non-canonical limbs rather than reducing them: reduction is not
/// injective, so two different byte strings would hash identically.
fn to_elements(bytes: &[u8]) -> Option<Vec<BaseElement>> {
    if bytes.len() % 8 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(bytes.len() / 8);
    for c in bytes.chunks(8) {
        let mut b = [0u8; 8];
        b.copy_from_slice(c);
        let v = u64::from_le_bytes(b);
        if v >= BaseElement::MODULUS {
            return None;
        }
        out.push(BaseElement::new(v));
    }
    Some(out)
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
        let line = line.trim();

        // fail closed: anything malformed replies ERR, never a plausible digest
        let reply = (|| {
            let (dom, hex) = line.split_once(':')?;
            let domain: u64 = dom.parse().ok()?;
            let bytes = unhex(hex)?;
            let elements = to_elements(&bytes)?;
            let digest = h_dom(domain, &elements);
            let mut s = String::with_capacity(64);
            for b in digest.iter() {
                use std::fmt::Write as _;
                let _ = write!(s, "{b:02x}");
            }
            Some(s)
        })();

        match reply {
            Some(s) => {
                let _ = writeln!(out, "{s}");
            }
            None => {
                let _ = writeln!(out, "ERR");
            }
        }
        let _ = out.flush();
    }
}
