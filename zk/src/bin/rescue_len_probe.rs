//! Characterises an upstream panic in `winter-crypto 0.13.1`.
//!
//! `Rp64_256::hash()` decides whether it is on the final chunk by comparing `i`
//! against `num_elements - 1`, but `i` is a *rate position* that is reset to 0
//! every RATE_WIDTH (8) absorptions. Once the input needs more than 8 chunks,
//! that comparison no longer identifies the last chunk, so a short final chunk
//! reaches `buf[..7].copy_from_slice(chunk)` and panics.
//!
//! Predicted condition: len > 56 (needs >8 seven-byte chunks) AND len % 7 != 0
//! (there is a short final chunk). This probe checks that prediction against
//! reality instead of trusting it.

use std::panic::{self, AssertUnwindSafe};

use winterfell::crypto::{hashers::Rp64_256, Hasher};

fn main() {
    let prev = panic::take_hook();
    panic::set_hook(Box::new(|_| {}));

    let mut panics = Vec::new();
    let mut ok = Vec::new();

    for len in 0..=200usize {
        let input = vec![0xABu8; len];
        let r = panic::catch_unwind(AssertUnwindSafe(|| {
            let _ = Rp64_256::hash(&input);
        }));
        if r.is_err() {
            panics.push(len);
        } else {
            ok.push(len);
        }
    }

    panic::set_hook(prev);

    println!("Rp64_256::hash() panic probe, input lengths 0..=200\n");
    println!("panicking lengths ({} of 201):", panics.len());
    println!("  {panics:?}\n");

    // check the predicted rule
    let predicted: Vec<usize> = (0..=200usize)
        .filter(|&l| l > 56 && !l.is_multiple_of(7))
        .collect();
    println!("predicted by rule (len > 56 && len % 7 != 0): {} lengths", predicted.len());
    println!("rule matches observed exactly: {}", predicted == panics);

    if predicted != panics {
        let only_obs: Vec<_> = panics.iter().filter(|l| !predicted.contains(l)).collect();
        let only_pred: Vec<_> = predicted.iter().filter(|l| !panics.contains(l)).collect();
        println!("  observed but not predicted: {only_obs:?}");
        println!("  predicted but not observed: {only_pred:?}");
    }

    println!("\nsafe lengths in 0..=64: {:?}", ok.iter().filter(|&&l| l <= 64).collect::<Vec<_>>());

    // the operations the Merkle tree actually uses are unaffected -- confirm
    let d1 = Rp64_256::hash(&[1u8; 32]);
    let d2 = Rp64_256::hash(&[2u8; 32]);
    let merged = panic::catch_unwind(AssertUnwindSafe(|| Rp64_256::merge(&[d1, d2])));
    println!("\nmerge(2 digests) unaffected: {}", merged.is_ok());
}
