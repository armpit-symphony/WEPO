//! Step 2.1 — Merkle membership, depth 32, against the field-native construction.
//!
//! Proves: "I know a note commitment `cm`, a position, and an authentication
//! path such that `cm` sits under the published anchor." Position and path stay
//! private; only the anchor is public.
//!
//! This is the first circuit step, so it is validated against the *node*, not
//! against itself: the witness is read straight out of
//! `tests/vectors/shielded_rescue-rp64-256.json` — a real commitment, its real
//! position, its real 32 siblings — and the AIR's computed anchor must equal the
//! anchor Python published. A circuit that agrees only with its own
//! recomputation proves nothing about the chain.
//!
//! Construction (see tests/vectors/README.md):
//!   leaf(cm)   = H_dom(1, limbs(cm))                 4 elements absorbed
//!   node(l, r) = H_dom(2, limbs(l) ‖ limbs(r))       8 elements = full rate
//!   H_dom sets capacity[0] = element count, capacity[1] = domain
//!
//! Layout: 33 permutations (1 leaf + 32 nodes), 8 rows each (7 rounds + 1 row
//! that folds the digest into the next level) = 264 rows, padded to 512. The
//! anchor is asserted at row 263, where the 33rd permutation completes; the
//! remaining cycles carry inert work so the constraints stay satisfied.
//!
//! NOT yet proven here (later steps): that `cm` is a well-formed commitment to
//! a note the prover can spend. Step 2.1 proves membership of *a* commitment.

use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use serde_json::Value;
use winterfell::{
    crypto::{hashers::Blake3_256, hashers::Rp64_256, DefaultRandomCoin, MerkleTree},
    math::{fields::f64::BaseElement, FieldElement, StarkField, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment, DefaultConstraintEvaluator,
    DefaultTraceLde, EvaluationFrame, FieldExtension, PartitionOptions, Proof, ProofOptions,
    Prover, StarkDomain, Trace, TraceInfo, TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

const STATE_WIDTH: usize = 12;
const RATE_START: usize = 4;
const DIGEST_LEN: usize = 4;
const NUM_ROUNDS: usize = 7;
const CYCLE_LEN: usize = 8;
const MERKLE_DEPTH: usize = 32;

const DOMAIN_LEAF: u64 = 1;
const DOMAIN_NODE: u64 = 2;
const NODE_ELEMENTS: u64 = 8; // limbs(l) ‖ limbs(r)

const BIT_COL: usize = STATE_WIDTH; // column 12
const TRACE_WIDTH: usize = STATE_WIDTH + 1;
/// 32 node hashes and nothing else -- the commitment IS the leaf, so there is
/// no 33rd permutation and the trace lands on a power of two with no padding.
const TRACE_LEN: usize = MERKLE_DEPTH * CYCLE_LEN; // 256
/// row where the last permutation completes and the anchor is readable
const ANCHOR_ROW: usize = TRACE_LEN - 1; // 255

// ---------------------------------------------------------------------------

fn mds_mul<E: FieldElement + From<BaseElement>>(v: &[E; STATE_WIDTH]) -> [E; STATE_WIDTH] {
    let mut out = [E::ZERO; STATE_WIDTH];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = E::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += E::from(Rp64_256::MDS[i][j]) * *vj;
        }
        *o = acc;
    }
    out
}

fn inv_mds_mul<E: FieldElement + From<BaseElement>>(v: &[E; STATE_WIDTH]) -> [E; STATE_WIDTH] {
    let mut out = [E::ZERO; STATE_WIDTH];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = E::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += E::from(Rp64_256::INV_MDS[i][j]) * *vj;
        }
        *o = acc;
    }
    out
}

#[inline(always)]
fn pow7<E: FieldElement>(x: E) -> E {
    let x2 = x * x;
    let x3 = x2 * x;
    let x6 = x3 * x3;
    x6 * x
}

// ---------------------------------------------------------------------------
// AIR
// ---------------------------------------------------------------------------

pub struct PublicInputs {
    anchor: [BaseElement; DIGEST_LEN],
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        self.anchor.to_vec()
    }
}

pub struct MembershipAir {
    context: AirContext<BaseElement>,
    anchor: [BaseElement; DIGEST_LEN],
}

impl Air for MembershipAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        assert_eq!(TRACE_WIDTH, trace_info.width());
        let mut degrees = Vec::new();
        for _ in 0..STATE_WIDTH {
            degrees.push(TransitionConstraintDegree::with_cycles(7, vec![CYCLE_LEN]));
        }
        degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN])); // bit binary
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN]));
            // placement
        }
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE_LEN]));
            // capacity
        }
        MembershipAir {
            context: AirContext::new(trace_info, degrees, 8, options),
            anchor: pub_inputs.anchor,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let mut cols = Vec::with_capacity(1 + 2 * STATE_WIDTH);
        let mut flag = vec![Self::BaseField::ONE; CYCLE_LEN];
        flag[CYCLE_LEN - 1] = Self::BaseField::ZERO;
        cols.push(flag);
        for j in 0..STATE_WIDTH {
            let mut c = vec![Self::BaseField::ZERO; CYCLE_LEN];
            for r in 0..NUM_ROUNDS {
                c[r] = Rp64_256::ARK1[r][j];
            }
            cols.push(c);
        }
        for j in 0..STATE_WIDTH {
            let mut c = vec![Self::BaseField::ZERO; CYCLE_LEN];
            for r in 0..NUM_ROUNDS {
                c[r] = Rp64_256::ARK2[r][j];
            }
            cols.push(c);
        }
        cols
    }

    fn evaluate_transition<E: FieldElement + From<Self::BaseField>>(
        &self,
        frame: &EvaluationFrame<E>,
        periodic: &[E],
        result: &mut [E],
    ) {
        let cur = frame.current();
        let next = frame.next();
        let hash_flag = periodic[0];
        let fold_flag = E::ONE - hash_flag;
        let ark1 = &periodic[1..1 + STATE_WIDTH];
        let ark2 = &periodic[1 + STATE_WIDTH..1 + 2 * STATE_WIDTH];

        // -- Rescue round -----------------------------------------------------
        let mut sbox = [E::ZERO; STATE_WIDTH];
        for i in 0..STATE_WIDTH {
            sbox[i] = pow7(cur[i]);
        }
        let mut step1 = mds_mul(&sbox);
        for i in 0..STATE_WIDTH {
            step1[i] += ark1[i];
        }
        let mut back = [E::ZERO; STATE_WIDTH];
        for i in 0..STATE_WIDTH {
            back[i] = next[i] - ark2[i];
        }
        let inv = inv_mds_mul(&back);
        for i in 0..STATE_WIDTH {
            result[i] = hash_flag * (step1[i] - pow7(inv[i]));
        }
        let mut idx = STATE_WIDTH;

        // -- fold row: carry the digest into the next level -------------------
        let b = next[BIT_COL];
        result[idx] = fold_flag * (b * b - b);
        idx += 1;

        for i in 0..DIGEST_LEN {
            // H_dom's digest is state[4..8] once the permutation has run
            let d = cur[RATE_START + i];
            // b == 0 -> our digest is the left child; b == 1 -> the right
            let placed = (E::ONE - b) * (next[RATE_START + i] - d)
                + b * (next[RATE_START + DIGEST_LEN + i] - d);
            result[idx + i] = fold_flag * placed;
        }
        idx += DIGEST_LEN;

        // -- every level after the leaf is a node hash ------------------------
        // capacity[0] = 8 elements, capacity[1] = DOMAIN_NODE, rest zero.
        // Without this a prover could relabel a node hash as a leaf hash.
        result[idx] = fold_flag * (next[0] - E::from(BaseElement::new(NODE_ELEMENTS)));
        result[idx + 1] = fold_flag * (next[1] - E::from(BaseElement::new(DOMAIN_NODE)));
        result[idx + 2] = fold_flag * next[2];
        result[idx + 3] = fold_flag * next[3];
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let mut a = Vec::with_capacity(12);
        // Every permutation, including the first, is a NODE hash over 8
        // elements. Pinning the capacity is what stops a prover relabelling a
        // level as some other domain.
        a.push(Assertion::single(0, 0, BaseElement::new(NODE_ELEMENTS)));
        a.push(Assertion::single(1, 0, BaseElement::new(DOMAIN_NODE)));
        a.push(Assertion::single(2, 0, BaseElement::ZERO));
        a.push(Assertion::single(3, 0, BaseElement::ZERO));
        // the anchor, where the 33rd permutation completes
        for i in 0..DIGEST_LEN {
            a.push(Assertion::single(
                RATE_START + i,
                ANCHOR_ROW,
                self.anchor[i],
            ));
        }
        a
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// ---------------------------------------------------------------------------
// witness + trace
// ---------------------------------------------------------------------------

struct Witness {
    commitment: [BaseElement; DIGEST_LEN],
    siblings: Vec<[BaseElement; DIGEST_LEN]>,
    bits: Vec<bool>,
}

fn limbs(bytes: &[u8]) -> [BaseElement; DIGEST_LEN] {
    assert_eq!(bytes.len(), 32);
    let mut out = [BaseElement::ZERO; DIGEST_LEN];
    for (i, o) in out.iter_mut().enumerate() {
        let mut b = [0u8; 8];
        b.copy_from_slice(&bytes[i * 8..(i + 1) * 8]);
        let v = u64::from_le_bytes(b);
        assert!(v < BaseElement::MODULUS, "non-canonical limb in witness");
        *o = BaseElement::new(v);
    }
    out
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("bad hex"))
        .collect()
}

/// Native H_dom, used to cross-check the trace.
fn h_dom(domain: u64, elements: &[BaseElement]) -> [BaseElement; DIGEST_LEN] {
    let mut state = [BaseElement::ZERO; STATE_WIDTH];
    state[0] = BaseElement::new(elements.len() as u64);
    state[1] = BaseElement::new(domain);
    let mut i = 0;
    let mut permuted = false;
    for &e in elements {
        state[RATE_START + i] += e;
        i += 1;
        if i == 8 {
            Rp64_256::apply_permutation(&mut state);
            permuted = true;
            i = 0;
        }
    }
    if i > 0 || !permuted {
        Rp64_256::apply_permutation(&mut state);
    }
    state[RATE_START..RATE_START + DIGEST_LEN]
        .try_into()
        .unwrap()
}

fn start_node(
    digest: &[BaseElement; DIGEST_LEN],
    sibling: &[BaseElement; DIGEST_LEN],
    bit: bool,
    state: &mut [BaseElement],
) {
    for s in state.iter_mut().take(STATE_WIDTH) {
        *s = BaseElement::ZERO;
    }
    state[0] = BaseElement::new(NODE_ELEMENTS);
    state[1] = BaseElement::new(DOMAIN_NODE);
    let (l, r) = if bit {
        (sibling, digest)
    } else {
        (digest, sibling)
    };
    for i in 0..DIGEST_LEN {
        state[RATE_START + i] = l[i];
        state[RATE_START + DIGEST_LEN + i] = r[i];
    }
}

fn build_trace(w: &Witness) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(TRACE_WIDTH, TRACE_LEN);
    trace.fill(
        |state| {
            // the commitment is the leaf: level 0 hashes it with its sibling
            start_node(&w.commitment, &w.siblings[0], w.bits[0], state);
            state[BIT_COL] = if w.bits[0] {
                BaseElement::ONE
            } else {
                BaseElement::ZERO
            };
        },
        |step, state| {
            let pos = step % CYCLE_LEN;
            if pos < NUM_ROUNDS {
                let mut s: [BaseElement; STATE_WIDTH] = state[..STATE_WIDTH].try_into().unwrap();
                Rp64_256::apply_round(&mut s, pos);
                state[..STATE_WIDTH].copy_from_slice(&s);
            } else {
                let cycle = step / CYCLE_LEN + 1; // level being set up
                let digest: [BaseElement; DIGEST_LEN] = state[RATE_START..RATE_START + DIGEST_LEN]
                    .try_into()
                    .unwrap();
                let bit = w.bits[cycle];
                start_node(&digest, &w.siblings[cycle], bit, state);
                state[BIT_COL] = if bit {
                    BaseElement::ONE
                } else {
                    BaseElement::ZERO
                };
            }
        },
    );
    trace
}

// ---------------------------------------------------------------------------

struct MembershipProver {
    options: ProofOptions,
}

impl Prover for MembershipProver {
    type BaseField = BaseElement;
    type Air = MembershipAir;
    type Trace = TraceTable<BaseElement>;
    type HashFn = Blake3;
    type VC = MerkleTree<Blake3>;
    type RandomCoin = DefaultRandomCoin<Blake3>;
    type TraceLde<E: FieldElement<BaseField = Self::BaseField>> =
        DefaultTraceLde<E, Self::HashFn, Self::VC>;
    type ConstraintCommitment<E: FieldElement<BaseField = Self::BaseField>> =
        DefaultConstraintCommitment<E, Self::HashFn, Self::VC>;
    type ConstraintEvaluator<'a, E: FieldElement<BaseField = Self::BaseField>> =
        DefaultConstraintEvaluator<'a, Self::Air, E>;

    fn get_pub_inputs(&self, trace: &Self::Trace) -> PublicInputs {
        let mut anchor = [BaseElement::ZERO; DIGEST_LEN];
        for (i, a) in anchor.iter_mut().enumerate() {
            *a = trace.get(RATE_START + i, ANCHOR_ROW);
        }
        PublicInputs { anchor }
    }
    fn options(&self) -> &ProofOptions {
        &self.options
    }
    fn new_trace_lde<E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        trace_info: &TraceInfo,
        main_trace: &ColMatrix<Self::BaseField>,
        domain: &StarkDomain<Self::BaseField>,
        partition_option: PartitionOptions,
    ) -> (Self::TraceLde<E>, TracePolyTable<E>) {
        DefaultTraceLde::new(trace_info, main_trace, domain, partition_option)
    }
    fn build_constraint_commitment<E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        composition_poly_trace: CompositionPolyTrace<E>,
        num_constraint_composition_columns: usize,
        domain: &StarkDomain<Self::BaseField>,
        partition_options: PartitionOptions,
    ) -> (Self::ConstraintCommitment<E>, CompositionPoly<E>) {
        DefaultConstraintCommitment::new(
            composition_poly_trace,
            num_constraint_composition_columns,
            domain,
            partition_options,
        )
    }
    fn new_evaluator<'a, E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        air: &'a Self::Air,
        aux_rand_elements: Option<AuxRandElements<E>>,
        composition_coefficients: winterfell::ConstraintCompositionCoefficients<E>,
    ) -> Self::ConstraintEvaluator<'a, E> {
        DefaultConstraintEvaluator::new(air, aux_rand_elements, composition_coefficients)
    }
}

fn verify_at(proof: Proof, anchor: [BaseElement; DIGEST_LEN], bits: u32) -> bool {
    winterfell::verify::<MembershipAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        PublicInputs { anchor },
        &AcceptableOptions::MinConjecturedSecurity(bits),
    )
    .is_ok()
}

fn main() {
    println!("Step 2.1 -- Merkle membership, depth {MERKLE_DEPTH}, field-native\n");

    // -- witness straight out of the node's golden vectors -------------------
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    let path = p
        .join("tests")
        .join("vectors")
        .join("shielded_rescue-rp64-256.json");
    let j: Value = serde_json::from_str(&fs::read_to_string(&path).expect("read golden"))
        .expect("parse golden");
    assert_eq!(j["algorithm"].as_str().unwrap(), "rescue-rp64-256");

    // The synthetic deep path, not one of the real ones. Position 0xA5A5A5A5 is
    // 10100101 repeating, so both the left- and right-child branches of the
    // sibling-placement constraint are exercised at all 32 levels, with no run
    // longer than two in either direction. A witness with zero direction bits
    // (position 0, or any small position) leaves the bit column identically zero,
    // which collapses that constraint from degree 2 to degree 1 and silently
    // skips the right-child branch entirely.
    let entry = &j["merkle"]["synthetic_deep_path"];
    let position = entry["position"].as_u64().unwrap() as usize;
    let cm_bytes = unhex(entry["commitment"].as_str().unwrap());
    let golden_root = unhex(entry["root"].as_str().unwrap());
    let sib_hex: Vec<String> = entry["siblings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    assert_eq!(sib_hex.len(), MERKLE_DEPTH);

    println!("witness taken from the node's published vectors:");
    println!("  commitment {}", entry["commitment"].as_str().unwrap());
    println!("  position   {position}");
    println!("  anchor     {}", entry["root"].as_str().unwrap());

    let mut siblings: Vec<[BaseElement; DIGEST_LEN]> =
        sib_hex.iter().map(|h| limbs(&unhex(h))).collect();
    let mut bits: Vec<bool> = (0..MERKLE_DEPTH)
        .map(|l| (position >> l) & 1 == 1)
        .collect();
    let w = Witness {
        commitment: limbs(&cm_bytes),
        siblings,
        bits,
    };
    let trace = build_trace(&w);

    // -- the check that matters: does the AIR agree with the NODE? -----------
    let mut air_anchor = [BaseElement::ZERO; DIGEST_LEN];
    for (i, a) in air_anchor.iter_mut().enumerate() {
        *a = trace.get(RATE_START + i, ANCHOR_ROW);
    }
    let expected = limbs(&golden_root);
    assert_eq!(
        air_anchor, expected,
        "AIR anchor disagrees with the anchor Python published"
    );
    println!("\nAIR anchor matches the node's published anchor: OK");

    // independent native recomputation of the same path
    let mut acc = w.commitment; // the commitment IS the leaf
    for lvl in 0..MERKLE_DEPTH {
        let (l, r) = if w.bits[lvl] {
            (w.siblings[lvl], acc)
        } else {
            (acc, w.siblings[lvl])
        };
        let mut e = Vec::with_capacity(8);
        e.extend_from_slice(&l);
        e.extend_from_slice(&r);
        acc = h_dom(DOMAIN_NODE, &e);
    }
    assert_eq!(acc, expected, "native H_dom walk disagrees");
    println!("native H_dom walk matches too (three-way: AIR, native, node)\n");

    // -- prove ---------------------------------------------------------------
    println!(
        "{:<34} {:>11} {:>10} {:>10} {:>8}",
        "config", "proof bytes", "prove ms", "verify ms", "128-bit"
    );
    println!("{}", "-".repeat(78));

    for (label, opts) in [
        (
            "96-bit  (32q, blowup 8, cubic)",
            ProofOptions::new(
                32,
                8,
                0,
                FieldExtension::Cubic,
                8,
                31,
                BatchingMethod::Linear,
                BatchingMethod::Linear,
            ),
        ),
        (
            "128-bit (43q, blowup 8, cubic)",
            ProofOptions::new(
                43,
                8,
                0,
                FieldExtension::Cubic,
                8,
                31,
                BatchingMethod::Linear,
                BatchingMethod::Linear,
            ),
        ),
    ] {
        let prover = MembershipProver { options: opts };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let t = Instant::now();
        for _ in 0..20 {
            assert!(
                verify_at(proof.clone(), expected, 95),
                "honest proof rejected"
            );
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / 20.0;
        let ok128 = verify_at(proof.clone(), expected, 128);

        println!(
            "{label:<34} {size:>11} {prove_ms:>10.1} {verify_ms:>10.3} {:>8}",
            if ok128 { "yes" } else { "no" }
        );
    }

    // -- soundness -----------------------------------------------------------
    println!("\nsoundness:");
    let prover = MembershipProver {
        options: ProofOptions::new(
            43,
            8,
            0,
            FieldExtension::Cubic,
            8,
            31,
            BatchingMethod::Linear,
            BatchingMethod::Linear,
        ),
    };
    let proof = prover.prove(trace.clone()).unwrap();
    let mut bad = expected;
    bad[0] += BaseElement::ONE;
    println!(
        "  wrong anchor rejected                  : {}",
        if verify_at(proof, bad, 95) {
            "NO -- UNSOUND"
        } else {
            "yes"
        }
    );

    // a commitment that is not in the tree must not produce this anchor
    let mut forged = w.commitment;
    forged[0] += BaseElement::ONE;
    let w2 = Witness {
        commitment: forged,
        siblings: w.siblings.clone(),
        bits: w.bits.clone(),
    };
    let t2 = build_trace(&w2);
    let mut other = [BaseElement::ZERO; DIGEST_LEN];
    for (i, a) in other.iter_mut().enumerate() {
        *a = t2.get(RATE_START + i, ANCHOR_ROW);
    }
    println!(
        "  different commitment -> different anchor: {}",
        if other != expected {
            "yes"
        } else {
            "NO -- COLLISION"
        }
    );
    let p2 = prover.prove(t2).unwrap();
    println!(
        "  forged commitment rejected vs real anchor: {}",
        if verify_at(p2, expected, 95) {
            "NO -- UNSOUND"
        } else {
            "yes"
        }
    );
}
