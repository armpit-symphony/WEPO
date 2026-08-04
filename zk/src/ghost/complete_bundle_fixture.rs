//! Deterministic honest proof fixture for the complete five-condition AIR.
//!
//! This is intentionally a child of `step2_bundle`: it reuses the exact prover,
//! trace, and vector-derived witness that the verifier accepts. It is a test and
//! audit artifact, never a wallet prover API.

use super::*;

pub struct HonestFixture {
    pub anchor: [u8; 32],
    pub nullifiers: Vec<[u8; 32]>,
    pub commitments: Vec<[u8; 32]>,
    pub value_balance: i64,
    pub sighash: [u8; 32],
    pub raw_proof: Vec<u8>,
}

fn bytes32(value: &[BaseElement; DIG]) -> [u8; 32] {
    to_bytes(value).try_into().expect("digest is 32 bytes")
}

pub fn build() -> HonestFixture {
    let mut sighash = [0u8; 32];
    for (index, byte) in sighash.iter_mut().enumerate() {
        *byte = index as u8;
    }
    build_with_sighash(sighash)
}

pub fn build_with_sighash(sighash: [u8; 32]) -> HonestFixture {
    let mut root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    root.pop();
    let vector_path = root
        .join("tests")
        .join("vectors")
        .join("shielded_rescue-rp64-256.json");
    let vectors: Value =
        serde_json::from_str(&fs::read_to_string(&vector_path).expect("read shielded vectors"))
            .expect("parse shielded vectors");

    let empty: Vec<[BaseElement; DIG]> = vectors["merkle"]["empty_roots"]
        .as_array()
        .expect("empty roots")
        .iter()
        .map(|value| limbs(&unhex(value.as_str().expect("empty root hex"))))
        .collect();
    let notes = vectors["notes"].as_array().expect("notes");
    let derivations = vectors["key_derivation"]
        .as_array()
        .expect("key derivations");

    // Use a non-degenerate published note. Its path position contains both
    // directions and has no period dividing the 32 Merkle levels.
    let note = &notes[5];
    let derivation = derivations
        .iter()
        .find(|candidate| candidate["nullifier_key"] == note["nullifier_key"])
        .expect("matching key derivation");
    let diversifier = encode_bytes(&unhex(
        derivation["diversifier"].as_str().expect("diversifier"),
    ));
    let leaf = limbs(&unhex(
        note["commitment"].as_str().expect("note commitment"),
    ));
    let nullifier = limbs(&unhex(note["nullifier"].as_str().expect("note nullifier")));
    let mut spend = SpendW {
        ask: limbs(&unhex(
            derivation["spending_key"].as_str().expect("spending key"),
        )),
        div: diversifier.try_into().expect("three diversifier elements"),
        value: BaseElement::new(note["value"].as_u64().expect("note value")),
        rho: limbs(&unhex(note["rho"].as_str().expect("rho"))),
        rcm: limbs(&unhex(note["rcm"].as_str().expect("rcm"))),
        leaf,
        siblings: Vec::new(),
        bits: Vec::new(),
    };
    let base = 0x9E37_79B9usize;
    let (anchor, paths) = adjacent_paths(base, &[leaf], &empty);
    spend.siblings = paths[0].0.clone();
    spend.bits = paths[0].1.clone();
    assert_eq!(
        native_root(&spend.leaf, &spend.siblings, &spend.bits),
        anchor
    );

    let mk_output = |value: u64, seed: u64| OutW {
        value: BaseElement::new(value),
        pkd: h_dom(DOMAIN_DIVERSIFIED_KEY, &[BaseElement::new(seed)]),
        rho: h_dom(DOMAIN_NULLIFIER, &[BaseElement::new(seed + 1)]),
        rcm: h_dom(DOMAIN_NOTE, &[BaseElement::new(seed + 2)]),
    };
    let value_balance = 900_000_000_000_003u64;
    let total = spend.value.as_int() + value_balance;
    let first_value = total / 3 + 7;
    let outputs = vec![
        mk_output(first_value, 1_000),
        mk_output(total - first_value, 1_001),
    ];
    let commitments: Vec<[BaseElement; DIG]> = outputs.iter().map(OutW::commitment).collect();

    assert_no_wrap(VALUE_BITS, 3);
    let witness = BundleW {
        spends: vec![spend],
        outputs,
        vb_pos: BaseElement::new(value_balance),
        vb_neg: BaseElement::ZERO,
        value_bits: VALUE_BITS,
    };
    let public_inputs = PublicInputsTemplate {
        spends: 1,
        outputs: 2,
        value_bits: VALUE_BITS,
        anchor,
        nullifiers: vec![nullifier],
        commitments: commitments.clone(),
        vb_pos: BaseElement::new(value_balance),
        vb_neg: BaseElement::ZERO,
        statement_binding: statement_binding(&sighash),
    };
    let prover = BundleProver {
        options: opts(43),
        pi: public_inputs.clone(),
    };
    let proof = prover
        .prove(build_trace(&witness))
        .expect("complete bundle proof");
    assert!(
        verify_at(proof.clone(), public_inputs.build(), 128),
        "fixture proof must verify before serialization"
    );

    HonestFixture {
        anchor: bytes32(&anchor),
        nullifiers: vec![bytes32(&nullifier)],
        commitments: commitments.iter().map(bytes32).collect(),
        value_balance: value_balance as i64,
        sighash,
        raw_proof: proof.to_bytes(),
    }
}
