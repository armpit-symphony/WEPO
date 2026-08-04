//! Emits the published Rp64_256 round constants as JSON so the Python oracle
//! can use them without ~300 hand-transcribed numbers.
//!
//! These are *parameters of the instantiation*, not an implementation: both
//! runtimes must use identical constants by definition, since different
//! constants are a different hash. The independence that matters is in the
//! permutation logic, and that is checked against the upstream Sage reference
//! vector, not against these numbers.
//!
//! `cargo run --release --bin dump_rescue_constants > ../tests/vectors/rescue_rp64_256_constants.json`

use winterfell::{
    crypto::hashers::Rp64_256,
    math::{fields::f64::BaseElement, StarkField},
};

fn row(v: &[BaseElement]) -> String {
    let cells: Vec<String> = v.iter().map(|e| format!("\"{}\"", e.as_int())).collect();
    format!("[{}]", cells.join(", "))
}

fn matrix(rows: &[[BaseElement; 12]]) -> String {
    let rs: Vec<String> = rows.iter().map(|r| format!("    {}", row(r))).collect();
    format!("[\n{}\n  ]", rs.join(",\n"))
}

fn main() {
    println!("{{");
    println!("  \"_comment\": \"Published Rescue-Prime Rp64_256 parameters, emitted from winter-crypto 0.13.1. Decimal strings because the values exceed JSON integer limits. Regenerate with: cargo run --release --bin dump_rescue_constants\",");
    println!("  \"modulus\": \"{}\",", BaseElement::MODULUS);
    println!("  \"state_width\": 12,");
    println!("  \"rate_range\": [4, 12],");
    println!("  \"capacity_range\": [0, 4],");
    println!("  \"digest_range\": [4, 8],");
    println!("  \"num_rounds\": 7,");
    println!("  \"alpha\": 7,");
    println!("  \"mds\": {},", matrix(&Rp64_256::MDS));
    println!("  \"ark1\": {},", matrix(&Rp64_256::ARK1));
    println!("  \"ark2\": {}", matrix(&Rp64_256::ARK2));
    println!("}}");
}
