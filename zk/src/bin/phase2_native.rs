//! Phase 2, part 1: native (out-of-circuit) hash throughput.
//!
//! The node hashes constantly outside the AIR -- building the commitment tree,
//! recomputing anchors, validating blocks. That cost is independent of the
//! circuit and it is what decides the Python-side question, so measure it
//! directly rather than inferring it from in-circuit numbers.

use std::time::Instant;

use sha3::{Digest, Sha3_256};
use winterfell::{
    crypto::{hashers::Rp64_256, ElementHasher, Hasher},
    math::{fields::f64::BaseElement, FieldElement},
};

const MERKLE_DEPTH: usize = 32;

fn bench<F: FnMut()>(label: &str, iters: usize, mut f: F) -> f64 {
    // warm up so we are not measuring cold branch predictors / page faults
    for _ in 0..(iters / 10).max(1) {
        f();
    }
    let t = Instant::now();
    for _ in 0..iters {
        f();
    }
    let ns_per = t.elapsed().as_secs_f64() * 1e9 / iters as f64;
    println!(
        "{:<44} {:>12.1} ns {:>14.0} /s",
        label,
        ns_per,
        1e9 / ns_per
    );
    ns_per
}

fn main() {
    println!("Phase 2 -- native hash throughput (out of circuit)");
    println!("host: x86_64-pc-windows-gnu, release, single thread\n");
    println!(
        "{:<44} {:>15} {:>16}",
        "operation", "per call", "throughput"
    );
    println!("{}", "-".repeat(78));

    // ---- two-to-one compression: the Merkle node operation -----------------
    // Rescue merges two 4-element digests (the rate is 8 elements wide, so a
    // node hash is exactly one permutation).
    let d1 = Rp64_256::hash(&[1u8; 32]);
    let d2 = Rp64_256::hash(&[2u8; 32]);
    let rescue_node = bench("Rescue Rp64_256  merge(2 digests)  [node]", 200_000, || {
        std::hint::black_box(Rp64_256::merge(&[d1, d2]));
    });

    // SHA3 node hash: tag + two 32-byte children, matching shielded.py's
    // tagged_hash(_TAG_NODE, left, right) shape.
    let tag = b"WEPO-Shielded-MerkleNode-v1";
    let left = [1u8; 32];
    let right = [2u8; 32];
    let sha3_node = bench("SHA3-256         tagged(node,l,r)  [node]", 200_000, || {
        let mut h = Sha3_256::new();
        h.update(tag);
        h.update(left);
        h.update(right);
        std::hint::black_box(h.finalize());
    });

    // ---- element hashing ---------------------------------------------------
    let elems: Vec<BaseElement> = (0..8u64).map(BaseElement::new).collect();
    bench("Rescue Rp64_256  hash_elements(8)", 200_000, || {
        std::hint::black_box(Rp64_256::hash_elements(&elems));
    });
    bench("SHA3-256         64 bytes", 200_000, || {
        std::hint::black_box(Sha3_256::digest([7u8; 64]));
    });

    println!("\n{}", "-".repeat(78));
    println!(
        "native ratio (SHA3 node / Rescue node): {:.2}x  -- {} is faster natively",
        sha3_node / rescue_node,
        if sha3_node < rescue_node {
            "SHA3"
        } else {
            "Rescue"
        }
    );

    // ---- authentication path recomputation ---------------------------------
    // Validating one witness against an anchor costs MERKLE_DEPTH node hashes.
    // This is the operation the node performs constantly.
    println!("\n{}", "-".repeat(78));
    println!("per-spend authentication path (depth {MERKLE_DEPTH}):");
    let r_path = rescue_node * MERKLE_DEPTH as f64 / 1e6;
    let s_path = sha3_node * MERKLE_DEPTH as f64 / 1e6;
    println!(
        "  Rescue : {r_path:>8.4} ms   ({:.0} paths/sec)",
        1e3 / r_path
    );
    println!(
        "  SHA3   : {s_path:>8.4} ms   ({:.0} paths/sec)",
        1e3 / s_path
    );

    // A full tree build over N leaves costs ~2N node hashes.
    println!("\nfull tree rebuild (2N node hashes):");
    for n in [1_000usize, 100_000, 1_000_000] {
        let r = rescue_node * 2.0 * n as f64 / 1e9;
        let s = sha3_node * 2.0 * n as f64 / 1e9;
        println!("  {n:>9} notes : Rescue {r:>7.3} s   SHA3 {s:>7.3} s");
    }
}
