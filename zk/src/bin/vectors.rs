//! Phase 3, step 1: prove the Rust side reproduces the Python golden vectors.
//!
//! Sequenced first deliberately. A byte-level disagreement between the two
//! runtimes is a silent chain split, and discovering it after the circuit
//! exists means rewriting the circuit. So: match the encoding, then build.
//!
//! Reads `tests/vectors/shielded_sha3-256.json` and reproduces every digest,
//! commitment, nullifier, root, sibling list and statement digest in it.
//! Partial agreement is not agreement -- any mismatch exits non-zero.
//!
//! `cargo run --release --bin vectors`

use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use sha3::{Digest, Sha3_256};

// ---------------------------------------------------------------------------
// the contract, ported
// ---------------------------------------------------------------------------

/// `field(x) = u32_le(x.len()) || x`
///
/// Without the prefix, H("01","2") == H("0","12") and one committed value can
/// be reread as another.
fn field(x: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + x.len());
    out.extend_from_slice(&(x.len() as u32).to_le_bytes());
    out.extend_from_slice(x);
    out
}

/// One-shot digest over the tag and all parts -- deliberately not a streaming
/// update per field, so nobody reinvents it as a Merkle-Damgard chain.
fn tagged_hash(tag: &[u8], parts: &[&[u8]]) -> Vec<u8> {
    let mut buf = field(tag);
    for p in parts {
        buf.extend_from_slice(&field(p));
    }
    Sha3_256::digest(&buf).to_vec()
}

const GOLDILOCKS: u128 = (1u128 << 64) - (1u128 << 32) + 1;
const FELT_BYTES: usize = 7;

/// `encode(B) = [B.len()] || [le_u64(B[0..7]), le_u64(B[7..14]), ...]`
///
/// 7 bytes per element, not 8: a full 64-bit chunk can exceed p and would need
/// reduction, and reduction is not injective. The leading length element keeps
/// the final chunk's zero padding distinguishable from real trailing zeros.
fn encode_bytes_as_field_elements(data: &[u8]) -> Vec<u64> {
    let mut out = Vec::with_capacity(1 + data.len() / FELT_BYTES + 1);
    out.push(data.len() as u64);
    for chunk in data.chunks(FELT_BYTES) {
        let mut buf = [0u8; 8];
        buf[..chunk.len()].copy_from_slice(chunk);
        let v = u64::from_le_bytes(buf);
        debug_assert!((v as u128) < GOLDILOCKS, "chunk must be canonical");
        out.push(v);
    }
    out
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("bad hex"))
        .collect()
}

fn hex(b: &[u8]) -> String {
    let mut s = String::with_capacity(b.len() * 2);
    for x in b {
        let _ = write!(s, "{x:02x}");
    }
    s
}

struct Report {
    passed: usize,
    failed: Vec<String>,
}

impl Report {
    fn new() -> Self {
        Report { passed: 0, failed: Vec::new() }
    }

    fn check(&mut self, what: &str, got: &str, want: &str) {
        if got == want {
            self.passed += 1;
        } else {
            self.failed
                .push(format!("{what}\n      got  {got}\n      want {want}"));
        }
    }

    fn section(&mut self, name: &str) {
        let before = self.failed.len();
        println!("  {name:<34} {} ok", self.passed);
        let _ = before;
    }
}

fn s(v: &Value) -> &str {
    v.as_str().expect("expected string")
}

// ---------------------------------------------------------------------------

fn main() {
    let path = std::env::args().nth(1).map(PathBuf::from).unwrap_or_else(|| {
        let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        p.pop();
        p.join("tests").join("vectors").join("shielded_sha3-256.json")
    });

    println!("Phase 3 step 1 -- cross-runtime vector agreement");
    println!("reading {}\n", path.display());

    let raw = fs::read_to_string(&path).expect("cannot read vector file");
    let j: Value = serde_json::from_str(&raw).expect("bad JSON");

    assert_eq!(s(&j["algorithm"]), "sha3-256", "unexpected algorithm");
    let depth = j["merkle_depth"].as_u64().unwrap() as usize;

    let tags = &j["tags"];
    let t_leaf = unhex(s(&tags["leaf"]));
    let t_node = unhex(s(&tags["node"]));
    let t_note = unhex(s(&tags["note"]));
    let t_nf = unhex(s(&tags["nullifier"]));
    let t_nk = unhex(s(&tags["nullifier_key"]));
    let t_pkd = unhex(s(&tags["diversified_key"]));
    let t_bundle = unhex(s(&tags["bundle"]));

    let mut r = Report::new();
    let mut mark = 0usize;

    // -- field encoding ------------------------------------------------------
    let fe = &j["field_encoding"];
    r.check("field_encoding.empty", &hex(&field(b"")), s(&fe["empty"]));
    r.check("field_encoding.abc", &hex(&field(b"abc")), s(&fe["abc"]));
    println!("  {:<34} {} ok", "field_encoding", r.passed - mark);
    mark = r.passed;

    // -- element encoding (hash-independent; testable before Rescue lands) ----
    for c in j["element_encoding"].as_array().unwrap() {
        let bytes = unhex(s(&c["bytes"]));
        assert_eq!(bytes.len() as u64, c["byte_len"].as_u64().unwrap());
        let got: Vec<String> = encode_bytes_as_field_elements(&bytes)
            .iter()
            .map(|e| e.to_string())
            .collect();
        let want: Vec<String> = c["elements"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| s(v).to_string())
            .collect();
        r.check(
            &format!("element_encoding[{}]", s(&c["label"])),
            &got.join(","),
            &want.join(","),
        );
    }
    println!("  {:<34} {} ok", "element_encoding", r.passed - mark);
    mark = r.passed;

    // -- raw tagged_hash cases ----------------------------------------------
    for (i, c) in j["tagged_hash"].as_array().unwrap().iter().enumerate() {
        let tag = unhex(s(&c["tag"]));
        let parts: Vec<Vec<u8>> = c["parts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| unhex(s(p)))
            .collect();
        let refs: Vec<&[u8]> = parts.iter().map(|p| p.as_slice()).collect();
        r.check(
            &format!("tagged_hash[{i}]"),
            &hex(&tagged_hash(&tag, &refs)),
            s(&c["digest"]),
        );
    }
    println!("  {:<34} {} ok", "tagged_hash", r.passed - mark);
    mark = r.passed;

    // -- key derivation ------------------------------------------------------
    for (i, c) in j["key_derivation"].as_array().unwrap().iter().enumerate() {
        let sk = unhex(s(&c["spending_key"]));
        let div = unhex(s(&c["diversifier"]));
        let nk = tagged_hash(&t_nk, &[&sk]);
        let pkd = tagged_hash(&t_pkd, &[&sk, &div]);
        r.check(&format!("key_derivation[{i}].nk"), &hex(&nk), s(&c["nullifier_key"]));
        r.check(
            &format!("key_derivation[{i}].pk_d"),
            &hex(&pkd),
            s(&c["diversified_key"]),
        );
    }
    println!("  {:<34} {} ok", "key_derivation", r.passed - mark);
    mark = r.passed;

    // -- notes: commitment and nullifier ------------------------------------
    for (i, c) in j["notes"].as_array().unwrap().iter().enumerate() {
        let value = c["value"].as_u64().unwrap();
        let pkd = unhex(s(&c["pk_d"]));
        let rho = unhex(s(&c["rho"]));
        let rcm = unhex(s(&c["rcm"]));
        let nk = unhex(s(&c["nullifier_key"]));

        let cm = tagged_hash(&t_note, &[&value.to_le_bytes(), &pkd, &rho, &rcm]);
        let nf = tagged_hash(&t_nf, &[&nk, &rho]);

        r.check(&format!("notes[{i}].commitment"), &hex(&cm), s(&c["commitment"]));
        r.check(&format!("notes[{i}].nullifier"), &hex(&nf), s(&c["nullifier"]));
    }
    println!("  {:<34} {} ok", "notes", r.passed - mark);
    mark = r.passed;

    // -- merkle --------------------------------------------------------------
    let leaf = |cm: &[u8]| tagged_hash(&t_leaf, &[cm]);
    let node = |l: &[u8], rr: &[u8]| tagged_hash(&t_node, &[l, rr]);

    let mut empty_roots: Vec<Vec<u8>> = vec![tagged_hash(&t_leaf, &[b""])];
    for i in 0..depth {
        let prev = empty_roots[i].clone();
        empty_roots.push(node(&prev, &prev));
    }

    let m = &j["merkle"];
    let want_empty = m["empty_roots"].as_array().unwrap();
    assert_eq!(want_empty.len(), depth + 1, "empty_roots length");
    for (i, w) in want_empty.iter().enumerate() {
        r.check(&format!("merkle.empty_roots[{i}]"), &hex(&empty_roots[i]), s(w));
    }
    r.check(
        "merkle.empty_root_leaf_level",
        &hex(&empty_roots[0]),
        s(&m["empty_root_leaf_level"]),
    );
    r.check(
        "merkle.empty_tree_root",
        &hex(&empty_roots[depth]),
        s(&m["empty_tree_root"]),
    );

    // rebuild the tree over the note commitments, exactly as the node does
    let commitments: Vec<Vec<u8>> = j["notes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| unhex(s(&n["commitment"])))
        .collect();
    assert_eq!(commitments.len() as u64, m["size"].as_u64().unwrap());

    r.check(
        "merkle.leaf_hash_of_first_commitment",
        &hex(&leaf(&commitments[0])),
        s(&m["leaf_hash_of_first_commitment"]),
    );
    r.check(
        "merkle.node_hash_of_first_two_leaves",
        &hex(&node(&leaf(&commitments[0]), &leaf(&commitments[1]))),
        s(&m["node_hash_of_first_two_leaves"]),
    );

    let mut layers: Vec<Vec<Vec<u8>>> = vec![commitments.iter().map(|c| leaf(c)).collect()];
    for level in 0..depth {
        let cur = &layers[level];
        let empty = &empty_roots[level];
        let mut next = Vec::new();
        let n = cur.len().max(1);
        let mut i = 0;
        while i < n {
            let l = cur.get(i).unwrap_or(empty);
            let rr = cur.get(i + 1).unwrap_or(empty);
            next.push(node(l, rr));
            i += 2;
        }
        layers.push(next);
    }
    r.check("merkle.root", &hex(&layers[depth][0]), s(&m["root"]));

    // authentication paths: sibling lists and the root each one reconstructs
    for (pi, p) in m["paths"].as_array().unwrap().iter().enumerate() {
        let position = p["position"].as_u64().unwrap() as usize;
        let cm = unhex(s(&p["commitment"]));

        let mut siblings: Vec<Vec<u8>> = Vec::with_capacity(depth);
        let mut index = position;
        for level in 0..depth {
            let layer = &layers[level];
            let sib_index = index ^ 1;
            siblings.push(
                layer
                    .get(sib_index)
                    .cloned()
                    .unwrap_or_else(|| empty_roots[level].clone()),
            );
            index >>= 1;
        }

        let want_sibs: Vec<String> = p["siblings"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| s(v).to_string())
            .collect();
        let got_sibs: Vec<String> = siblings.iter().map(|x| hex(x)).collect();
        r.check(
            &format!("merkle.paths[{pi}].siblings"),
            &got_sibs.join(","),
            &want_sibs.join(","),
        );

        // walk the path back up to the anchor
        let mut cur = leaf(&cm);
        for (level, sib) in siblings.iter().enumerate() {
            cur = if (position >> level) & 1 == 1 {
                node(sib, &cur)
            } else {
                node(&cur, sib)
            };
        }
        r.check(&format!("merkle.paths[{pi}].root"), &hex(&cur), s(&p["root"]));
    }
    println!("  {:<34} {} ok", "merkle", r.passed - mark);
    mark = r.passed;

    // -- bundle statement digests -------------------------------------------
    let statement = |anchor: &[u8],
                     nullifiers: &[Vec<u8>],
                     commitments: &[Vec<u8>],
                     value_balance: i64,
                     sighash: &[u8]| {
        // the joined lists are each ONE length-prefixed field, not one per element
        let nf_joined: Vec<u8> = nullifiers.concat();
        let cm_joined: Vec<u8> = commitments.concat();
        tagged_hash(
            &t_bundle,
            &[
                anchor,
                &(nullifiers.len() as u32).to_le_bytes(),
                &nf_joined,
                &(commitments.len() as u32).to_le_bytes(),
                &cm_joined,
                &value_balance.to_le_bytes(),
                sighash,
            ],
        )
    };

    let b = &j["bundle"];
    let nfs: Vec<Vec<u8>> = b["nullifiers"].as_array().unwrap().iter().map(|v| unhex(s(v))).collect();
    let cms: Vec<Vec<u8>> = b["commitments"].as_array().unwrap().iter().map(|v| unhex(s(v))).collect();
    r.check(
        "bundle.statement_digest",
        &hex(&statement(
            &unhex(s(&b["anchor"])),
            &nfs,
            &cms,
            b["value_balance"].as_i64().unwrap(),
            &unhex(s(&b["sighash"])),
        )),
        s(&b["statement_digest"]),
    );

    // outputs-only bundle: no anchor, so the empty-tree root stands in
    let sb = &j["shielding_bundle"];
    let sb_cms: Vec<Vec<u8>> = sb["commitments"].as_array().unwrap().iter().map(|v| unhex(s(v))).collect();
    r.check(
        "shielding_bundle.statement_digest",
        &hex(&statement(
            &empty_roots[depth],
            &[],
            &sb_cms,
            sb["value_balance"].as_i64().unwrap(),
            &unhex(s(&sb["sighash"])),
        )),
        s(&sb["statement_digest"]),
    );
    println!("  {:<34} {} ok", "bundle", r.passed - mark);

    // -----------------------------------------------------------------------
    println!("\n{}", "-".repeat(60));
    if r.failed.is_empty() {
        println!("ALL {} CHECKS AGREE -- Rust matches the Python golden vectors", r.passed);
    } else {
        println!("{} passed, {} FAILED\n", r.passed, r.failed.len());
        for f in &r.failed {
            println!("  [FAIL] {f}");
        }
        std::process::exit(1);
    }
}
