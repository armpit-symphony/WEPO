//! Minimal Rescue-Prime hashing CLI, built to measure the "Python shells out to
//! Rust" option honestly rather than dismissing it by assertion.
//!
//! Each stdin line is 128 hex chars = 64 bytes = two 32-byte children, matching
//! `_node_hash(left, right)` in shielded.py. Emits one hex digest per line.
//!
//! Deliberately uses the *field-element* API (`hash_elements`), not the
//! byte-oriented `Rp64_256::hash()`. The latter panics on any input longer than
//! 56 bytes whose length is not a multiple of 7 -- see `rescue_len_probe`. A
//! node hash is 64 bytes, which is exactly in that panicking range.

use std::io::{self, BufRead, Write};

use winterfell::{
    crypto::{hashers::Rp64_256, Digest, ElementHasher},
    math::fields::f64::BaseElement,
};

/// Map 8 bytes to a field element by reducing mod p. Real code must use the
/// canonical encoding agreed with the Python side; this is a benchmark.
fn to_elements(bytes: &[u8]) -> Option<[BaseElement; 8]> {
    if bytes.len() != 64 {
        return None;
    }
    let mut out = [BaseElement::new(0); 8];
    for (i, o) in out.iter_mut().enumerate() {
        let mut b = [0u8; 8];
        b.copy_from_slice(&bytes[i * 8..(i + 1) * 8]);
        *o = BaseElement::new(u64::from_le_bytes(b));
    }
    Some(out)
}

fn from_hex(s: &str) -> Option<Vec<u8>> {
    let s = s.trim();
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        // fail closed: any malformed input yields ERR, never a plausible digest
        let digest = from_hex(&line)
            .as_deref()
            .and_then(to_elements)
            .map(|e| Rp64_256::hash_elements(&e));

        match digest {
            Some(d) => {
                let mut hex = String::with_capacity(64);
                for b in d.as_bytes().iter() {
                    hex.push_str(&format!("{b:02x}"));
                }
                let _ = writeln!(out, "{hex}");
            },
            None => {
                let _ = writeln!(out, "ERR");
            },
        }
    }
    let _ = out.flush();
}
