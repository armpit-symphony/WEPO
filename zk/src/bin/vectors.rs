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
use winterfell::{
    crypto::{hashers::Rp64_256, Digest as _, ElementHasher},
    math::{fields::f64::BaseElement, FieldElement},
};

/// Which pool hash a golden file was generated under.
#[derive(Clone, Copy, PartialEq)]
enum Pool {
    Sha3,
    Rescue,
}

impl Pool {
    fn parse(name: &str) -> Pool {
        match name {
            "sha3-256" => Pool::Sha3,
            "rescue-rp64-256" => Pool::Rescue,
            other => panic!("unknown pool hash algorithm: {other}"),
        }
    }

    /// Is this file from before the tree went field-native?
    ///
    /// The SHA3 golden is a frozen historical artifact: it was generated when
    /// every derivation went through the byte-oriented `tagged_hash`. The live
    /// Rescue golden uses `H_dom` for the six derivations the circuit proves,
    /// and keeps `tagged_hash` only for the bundle statement digest, which is
    /// the public input and never enters the circuit.
    fn field_native(self) -> bool {
        self == Pool::Rescue
    }

    /// The tree's leaf value for a commitment.
    ///
    /// Field-native: there is NO leaf hash -- a commitment IS a leaf. Safe
    /// because depth is fixed at 32, a commitment is already domain-separated
    /// from a node (H_dom(3,..) vs H_dom(2,..)), the circuit opens the
    /// commitment rather than treating it as opaque, and Sapling does the same.
    /// See tests/vectors/README.md.
    ///
    /// The frozen SHA3 golden predates that and still hashes its leaves.
    fn leaf(self, cm: &[u8], t_leaf: &[u8]) -> Vec<u8> {
        if self.field_native() {
            cm.to_vec()
        } else {
            tagged_hash(self, t_leaf, &[cm])
        }
    }

    /// The empty-slot sentinel. DOMAIN_LEAF survives only for this.
    fn empty_sentinel(self, t_leaf: &[u8]) -> Vec<u8> {
        if self.field_native() {
            h_dom(DOMAIN_LEAF, &[])
        } else {
            tagged_hash(self, t_leaf, &[b""])
        }
    }

    fn node(self, l: &[u8], r: &[u8], t_node: &[u8]) -> Vec<u8> {
        if self.field_native() {
            let mut e = limbs(l);
            e.extend(limbs(r));
            h_dom(DOMAIN_NODE, &e) // 8 elements: exactly the rate, one permutation
        } else {
            tagged_hash(self, t_node, &[l, r])
        }
    }

    fn note(self, value: u64, pkd: &[u8], rho: &[u8], rcm: &[u8], t_note: &[u8]) -> Vec<u8> {
        if self.field_native() {
            let mut e = vec![value];
            e.extend(limbs(pkd));
            e.extend(limbs(rho));
            e.extend(limbs(rcm));
            h_dom(DOMAIN_NOTE, &e)
        } else {
            tagged_hash(self, t_note, &[&value.to_le_bytes(), pkd, rho, rcm])
        }
    }

    fn nullifier(self, nk: &[u8], rho: &[u8], t_nf: &[u8]) -> Vec<u8> {
        if self.field_native() {
            let mut e = limbs(nk);
            e.extend(limbs(rho));
            h_dom(DOMAIN_NULLIFIER, &e)
        } else {
            tagged_hash(self, t_nf, &[nk, rho])
        }
    }

    fn nullifier_key(self, sk: &[u8], t_nk: &[u8]) -> Vec<u8> {
        if self.field_native() {
            h_dom(DOMAIN_NULLIFIER_KEY, &limbs(sk))
        } else {
            tagged_hash(self, t_nk, &[sk])
        }
    }

    fn diversified_key(self, sk: &[u8], div: &[u8], t_pkd: &[u8]) -> Vec<u8> {
        if self.field_native() {
            // the diversifier is 11 bytes, not a whole number of limbs, and is a
            // pure witness input -- so it uses the 7-byte chunk encoding
            let mut e = limbs(sk);
            e.extend(encode_bytes_as_field_elements(div));
            h_dom(DOMAIN_DIVERSIFIED_KEY, &e)
        } else {
            tagged_hash(self, t_pkd, &[sk, div])
        }
    }

    /// The one-shot digest. Rescue goes through `hash_elements` -- never
    /// `Rp64_256::hash()`, which panics on ~half of all input lengths.
    fn digest(self, data: &[u8]) -> Vec<u8> {
        match self {
            Pool::Sha3 => Sha3_256::digest(data).to_vec(),
            Pool::Rescue => {
                let elements: Vec<BaseElement> = encode_bytes_as_field_elements(data)
                    .into_iter()
                    .map(BaseElement::new)
                    .collect();
                Rp64_256::hash_elements(&elements).as_bytes().to_vec()
            }
        }
    }
}

// ---------------------------------------------------------------------------
// field-native construction (everything the circuit proves)
// ---------------------------------------------------------------------------

const DOMAIN_LEAF: u64 = 1;
const DOMAIN_NODE: u64 = 2;
const DOMAIN_NOTE: u64 = 3;
const DOMAIN_NULLIFIER: u64 = 4;
const DOMAIN_NULLIFIER_KEY: u64 = 5;
const DOMAIN_DIVERSIFIED_KEY: u64 = 6;

/// `H_dom(domain, elements)` -- stock `hash_elements` with capacity[1] = domain.
fn h_dom(domain: u64, elements: &[u64]) -> Vec<u8> {
    use winterfell::math::StarkField;
    let mut state = [BaseElement::ZERO; 12];
    state[0] = BaseElement::new(elements.len() as u64);
    state[1] = BaseElement::new(domain);

    let mut i = 0;
    let mut permuted = false;
    for &e in elements {
        state[4 + i] += BaseElement::new(e);
        i += 1;
        if i == 8 {
            Rp64_256::apply_permutation(&mut state);
            permuted = true;
            i = 0;
        }
    }
    // also permute for an empty input, or the digest would be the zero state
    if i > 0 || !permuted {
        Rp64_256::apply_permutation(&mut state);
    }

    let mut out = Vec::with_capacity(32);
    for k in 0..4 {
        out.extend_from_slice(&state[4 + k].as_int().to_le_bytes());
    }
    out
}

/// A 32-byte pool value is 4 canonical limbs, little-endian each.
fn limbs(data: &[u8]) -> Vec<u64> {
    assert_eq!(
        data.len() % 8,
        0,
        "pool value must be a whole number of limbs"
    );
    data.chunks(8)
        .map(|c| {
            let mut b = [0u8; 8];
            b.copy_from_slice(c);
            let v = u64::from_le_bytes(b);
            assert!(v < GOLDILOCKS as u64, "non-canonical limb");
            v
        })
        .collect()
}

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
fn tagged_hash(pool: Pool, tag: &[u8], parts: &[&[u8]]) -> Vec<u8> {
    let mut buf = field(tag);
    for p in parts {
        buf.extend_from_slice(&field(p));
    }
    pool.digest(&buf)
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
        Report {
            passed: 0,
            failed: Vec::new(),
        }
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

fn vectors_dir() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    p.join("tests").join("vectors")
}

fn run(path: &PathBuf) -> bool {
    let raw = fs::read_to_string(path).expect("cannot read vector file");
    let j: Value = serde_json::from_str(&raw).expect("bad JSON");

    let algorithm = s(&j["algorithm"]).to_string();
    let pool = Pool::parse(&algorithm);
    println!(
        "{} ({})",
        path.file_name().unwrap().to_string_lossy(),
        algorithm
    );

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
            &hex(&tagged_hash(pool, &tag, &refs)),
            s(&c["digest"]),
        );
    }
    println!("  {:<34} {} ok", "tagged_hash", r.passed - mark);
    mark = r.passed;

    // -- key derivation ------------------------------------------------------
    for (i, c) in j["key_derivation"].as_array().unwrap().iter().enumerate() {
        let sk = unhex(s(&c["spending_key"]));
        let div = unhex(s(&c["diversifier"]));
        let nk = pool.nullifier_key(&sk, &t_nk);
        let pkd = pool.diversified_key(&sk, &div, &t_pkd);
        r.check(
            &format!("key_derivation[{i}].nk"),
            &hex(&nk),
            s(&c["nullifier_key"]),
        );
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

        let cm = pool.note(value, &pkd, &rho, &rcm, &t_note);
        let nf = pool.nullifier(&nk, &rho, &t_nf);

        r.check(
            &format!("notes[{i}].commitment"),
            &hex(&cm),
            s(&c["commitment"]),
        );
        r.check(
            &format!("notes[{i}].nullifier"),
            &hex(&nf),
            s(&c["nullifier"]),
        );
    }
    println!("  {:<34} {} ok", "notes", r.passed - mark);
    mark = r.passed;

    // -- merkle --------------------------------------------------------------
    let leaf = |cm: &[u8]| pool.leaf(cm, &t_leaf);
    let node = |l: &[u8], rr: &[u8]| pool.node(l, rr, &t_node);

    let mut empty_roots: Vec<Vec<u8>> = vec![pool.empty_sentinel(&t_leaf)];
    for i in 0..depth {
        let prev = empty_roots[i].clone();
        empty_roots.push(node(&prev, &prev));
    }

    let m = &j["merkle"];
    let want_empty = m["empty_roots"].as_array().unwrap();
    assert_eq!(want_empty.len(), depth + 1, "empty_roots length");
    for (i, w) in want_empty.iter().enumerate() {
        r.check(
            &format!("merkle.empty_roots[{i}]"),
            &hex(&empty_roots[i]),
            s(w),
        );
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

    // Field-native files publish the empty-slot sentinel instead of a leaf hash,
    // because there is no leaf hash. The frozen SHA3 file still has the old key.
    if let Some(v) = m.get("empty_leaf_sentinel") {
        r.check(
            "merkle.empty_leaf_sentinel",
            &hex(&pool.empty_sentinel(&t_leaf)),
            s(v),
        );
        // the sentinel must never coincide with a real commitment
        r.check(
            "merkle.sentinel is not any published commitment",
            &commitments
                .iter()
                .any(|c| c == &pool.empty_sentinel(&t_leaf))
                .to_string(),
            "false",
        );
    }
    if let Some(v) = m.get("leaf_hash_of_first_commitment") {
        r.check(
            "merkle.leaf_hash_of_first_commitment",
            &hex(&leaf(&commitments[0])),
            s(v),
        );
    }
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
        r.check(
            &format!("merkle.paths[{pi}].root"),
            &hex(&cur),
            s(&p["root"]),
        );
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
            pool,
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
    let nfs: Vec<Vec<u8>> = b["nullifiers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| unhex(s(v)))
        .collect();
    let cms: Vec<Vec<u8>> = b["commitments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| unhex(s(v)))
        .collect();
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
    let sb_cms: Vec<Vec<u8>> = sb["commitments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| unhex(s(v)))
        .collect();
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
    if r.failed.is_empty() {
        println!("  -> all {} checks agree\n", r.passed);
        true
    } else {
        println!("  -> {} passed, {} FAILED", r.passed, r.failed.len());
        for f in &r.failed {
            println!("     [FAIL] {f}");
        }
        println!();
        false
    }
}

fn main() {
    println!("Cross-runtime vector agreement (Rust side)\n");

    // Check every golden file present, not just the consensus one. The retired
    // SHA3 file stays as the reference the Rescue file is diffed against, and
    // Rust has to reproduce both -- a port that only satisfies the live hash
    // would hide an encoding regression in the one we still compare against.
    let paths: Vec<PathBuf> = match std::env::args().nth(1) {
        Some(p) => vec![PathBuf::from(p)],
        None => {
            let dir = vectors_dir();
            let mut v: Vec<PathBuf> = fs::read_dir(&dir)
                .expect("cannot read vectors dir")
                .filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| {
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|n| n.starts_with("shielded_") && n.ends_with(".json"))
                        .unwrap_or(false)
                })
                .collect();
            v.sort();
            v
        }
    };

    assert!(!paths.is_empty(), "no golden vector files found");

    let mut all_ok = true;
    for p in &paths {
        all_ok &= run(p);
    }

    println!("{}", "-".repeat(60));
    if all_ok {
        println!(
            "ALL {} GOLDEN FILE(S) AGREE -- Rust matches Python",
            paths.len()
        );
    } else {
        println!("MISMATCH -- Rust and Python disagree");
        std::process::exit(1);
    }
}
