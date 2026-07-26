//! Step 2.2 — Merkle membership + nullifier integrity.
//!
//! Proves, in one proof:
//!   (a) a commitment sits under the published anchor (step 2.1), and
//!   (b) the revealed nullifier is nf == H_dom(4, limbs(nk) ‖ limbs(rho))
//!       for a secret nullifier key and note serial.
//!
//! Public: the anchor and nf. Private: the commitment, position, path, nk, rho.
//!
//! NOT YET BOUND. Step 2.2 proves (a) and (b) side by side, not that they refer
//! to the *same note*. Binding arrives in step 2.3, when the circuit computes
//! cm = H_dom(3, [value] ‖ limbs(pk_d) ‖ limbs(rho) ‖ limbs(rcm)) from the same
//! rho and constrains it to equal the Merkle leaf. Stated plainly because a
//! half-bound circuit that looks finished is exactly the kind of thing that
//! ships.
//!
//! GEOMETRY. Step 2.1 used all 256 rows: 32 node hashes at 8 rows each, exactly
//! full. Adding the nullifier permutation as more rows would be 264 rows, which
//! Winterfell rounds to 512. Measured cost of each option at 128-bit:
//!
//!     13 cols x 512 rows (sequential)   41,577 B
//!     26 cols x 256 rows (parallel)     35,220 B
//!     40 cols x 256 rows (parallel)     41,426 B
//!
//! So the nullifier runs as a SECOND Rescue instance in its own columns,
//! concurrently with the Merkle path. The trace stays at 256 rows. The 40-column
//! figure matters for what comes next: it costs the same as tipping to 512 rows,
//! but holds nk, pk_d, cm and nf together -- whereas 512 rows buys one more
//! permutation before needing 1024.
//!
//! The second instance idles by chaining its own digest after row 7. That keeps
//! the round constraints satisfied for the remaining 248 rows without special
//! casing, and nf is read at row 7 where its single permutation completes.

use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use serde_json::Value;
use winterfell::{
    crypto::{hashers::Blake3_256, hashers::Rp64_256, DefaultRandomCoin, MerkleTree},
    math::{fields::f64::BaseElement, FieldElement, StarkField, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment,
    DefaultConstraintEvaluator, DefaultTraceLde, EvaluationFrame, FieldExtension,
    PartitionOptions, Proof, ProofOptions, Prover, StarkDomain, TraceInfo,
    TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

const W: usize = 12; // Rescue state width
const RATE: usize = 4; // rate starts at index 4
const DIG: usize = 4; // digest length in elements
const ROUNDS: usize = 7;
const CYCLE: usize = 8;
const DEPTH: usize = 32;

const DOMAIN_NODE: u64 = 2;
const DOMAIN_NULLIFIER: u64 = 4;
const NODE_ELEMENTS: u64 = 8;
const NF_ELEMENTS: u64 = 8;

// column layout: [ merkle state 0..12 | bit 12 | nullifier state 13..25 ]
const M: usize = 0;
const BIT_COL: usize = W;
const N: usize = W + 1;
const TRACE_WIDTH: usize = 2 * W + 1; // 25
const TRACE_LEN: usize = DEPTH * CYCLE; // 256 -- unchanged from step 2.1
const ANCHOR_ROW: usize = TRACE_LEN - 1; // 255
const NF_ROW: usize = CYCLE - 1; // 7

// ---------------------------------------------------------------------------

fn mds_mul<E: FieldElement + From<BaseElement>>(v: &[E; W]) -> [E; W] {
    let mut out = [E::ZERO; W];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = E::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += E::from(Rp64_256::MDS[i][j]) * *vj;
        }
        *o = acc;
    }
    out
}

fn inv_mds_mul<E: FieldElement + From<BaseElement>>(v: &[E; W]) -> [E; W] {
    let mut out = [E::ZERO; W];
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

/// One Rescue round constraint set for a state living at `base`.
fn rescue_round<E: FieldElement + From<BaseElement>>(
    cur: &[E],
    next: &[E],
    base: usize,
    ark1: &[E],
    ark2: &[E],
    flag: E,
    out: &mut [E],
) {
    let mut sbox = [E::ZERO; W];
    for i in 0..W {
        sbox[i] = pow7(cur[base + i]);
    }
    let mut step1 = mds_mul(&sbox);
    for i in 0..W {
        step1[i] += ark1[i];
    }
    let mut back = [E::ZERO; W];
    for i in 0..W {
        back[i] = next[base + i] - ark2[i];
    }
    let inv = inv_mds_mul(&back);
    for i in 0..W {
        out[i] = flag * (step1[i] - pow7(inv[i]));
    }
}

// ---------------------------------------------------------------------------

pub struct PublicInputs {
    anchor: [BaseElement; DIG],
    nullifier: [BaseElement; DIG],
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        let mut v = self.anchor.to_vec();
        v.extend_from_slice(&self.nullifier);
        v
    }
}

pub struct SpendAir {
    context: AirContext<BaseElement>,
    anchor: [BaseElement; DIG],
    nullifier: [BaseElement; DIG],
}

impl Air for SpendAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        assert_eq!(TRACE_WIDTH, trace_info.width());
        let mut d = Vec::new();
        // merkle instance
        for _ in 0..W {
            d.push(TransitionConstraintDegree::with_cycles(7, vec![CYCLE]));
        }
        d.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE])); // bit
        for _ in 0..DIG {
            d.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE])); // placement
        }
        for _ in 0..DIG {
            d.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE])); // capacity
        }
        // nullifier instance
        for _ in 0..W {
            d.push(TransitionConstraintDegree::with_cycles(7, vec![CYCLE]));
        }
        for _ in 0..DIG {
            d.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE])); // chain
        }
        for _ in 0..DIG {
            d.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE])); // capacity
        }
        SpendAir {
            context: AirContext::new(trace_info, d, 16, options),
            anchor: pub_inputs.anchor,
            nullifier: pub_inputs.nullifier,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let mut cols = Vec::with_capacity(1 + 2 * W);
        let mut flag = vec![Self::BaseField::ONE; CYCLE];
        flag[CYCLE - 1] = Self::BaseField::ZERO;
        cols.push(flag);
        for j in 0..W {
            let mut c = vec![Self::BaseField::ZERO; CYCLE];
            for r in 0..ROUNDS {
                c[r] = Rp64_256::ARK1[r][j];
            }
            cols.push(c);
        }
        for j in 0..W {
            let mut c = vec![Self::BaseField::ZERO; CYCLE];
            for r in 0..ROUNDS {
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
        let ark1 = &periodic[1..1 + W];
        let ark2 = &periodic[1 + W..1 + 2 * W];

        // ---- merkle instance -------------------------------------------------
        let mut buf = [E::ZERO; W];
        rescue_round(cur, next, M, ark1, ark2, hash_flag, &mut buf);
        result[..W].copy_from_slice(&buf);
        let mut idx = W;

        let b = next[BIT_COL];
        result[idx] = fold_flag * (b * b - b);
        idx += 1;

        for i in 0..DIG {
            let d = cur[M + RATE + i];
            let placed =
                (E::ONE - b) * (next[M + RATE + i] - d) + b * (next[M + RATE + DIG + i] - d);
            result[idx + i] = fold_flag * placed;
        }
        idx += DIG;

        result[idx] = fold_flag * (next[M] - E::from(BaseElement::new(NODE_ELEMENTS)));
        result[idx + 1] = fold_flag * (next[M + 1] - E::from(BaseElement::new(DOMAIN_NODE)));
        result[idx + 2] = fold_flag * next[M + 2];
        result[idx + 3] = fold_flag * next[M + 3];
        idx += DIG;

        // ---- nullifier instance ---------------------------------------------
        // Same permutation, its own columns, running concurrently. After its one
        // real permutation it chains its own digest so the round constraints
        // stay satisfied for the rest of the trace without a special case.
        rescue_round(cur, next, N, ark1, ark2, hash_flag, &mut buf);
        result[idx..idx + W].copy_from_slice(&buf);
        idx += W;

        for i in 0..DIG {
            let d = cur[N + RATE + i];
            // chain: both halves of the next rate are the digest just produced
            result[idx + i] = fold_flag * (next[N + RATE + i] - d);
        }
        idx += DIG;

        result[idx] = fold_flag * (next[N] - E::from(BaseElement::new(NF_ELEMENTS)));
        result[idx + 1] = fold_flag * (next[N + 1] - E::from(BaseElement::new(DOMAIN_NULLIFIER)));
        result[idx + 2] = fold_flag * next[N + 2];
        result[idx + 3] = fold_flag * next[N + 3];
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let mut a = Vec::with_capacity(12);
        // merkle: first permutation is a node hash over 8 elements
        a.push(Assertion::single(M, 0, BaseElement::new(NODE_ELEMENTS)));
        a.push(Assertion::single(M + 1, 0, BaseElement::new(DOMAIN_NODE)));
        a.push(Assertion::single(M + 2, 0, BaseElement::ZERO));
        a.push(Assertion::single(M + 3, 0, BaseElement::ZERO));
        // nullifier: H_dom(DOMAIN_NULLIFIER, 8 elements)
        a.push(Assertion::single(N, 0, BaseElement::new(NF_ELEMENTS)));
        a.push(Assertion::single(N + 1, 0, BaseElement::new(DOMAIN_NULLIFIER)));
        a.push(Assertion::single(N + 2, 0, BaseElement::ZERO));
        a.push(Assertion::single(N + 3, 0, BaseElement::ZERO));
        // the anchor and the revealed nullifier
        for i in 0..DIG {
            a.push(Assertion::single(M + RATE + i, ANCHOR_ROW, self.anchor[i]));
        }
        for i in 0..DIG {
            a.push(Assertion::single(N + RATE + i, NF_ROW, self.nullifier[i]));
        }
        a
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// ---------------------------------------------------------------------------

struct Witness {
    commitment: [BaseElement; DIG],
    siblings: Vec<[BaseElement; DIG]>,
    bits: Vec<bool>,
    nk: [BaseElement; DIG],
    rho: [BaseElement; DIG],
}

fn limbs(bytes: &[u8]) -> [BaseElement; DIG] {
    assert_eq!(bytes.len(), 32);
    let mut out = [BaseElement::ZERO; DIG];
    for (i, o) in out.iter_mut().enumerate() {
        let mut b = [0u8; 8];
        b.copy_from_slice(&bytes[i * 8..(i + 1) * 8]);
        let v = u64::from_le_bytes(b);
        assert!(v < BaseElement::MODULUS, "non-canonical limb");
        *o = BaseElement::new(v);
    }
    out
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("hex"))
        .collect()
}

fn h_dom(domain: u64, elements: &[BaseElement]) -> [BaseElement; DIG] {
    let mut st = [BaseElement::ZERO; W];
    st[0] = BaseElement::new(elements.len() as u64);
    st[1] = BaseElement::new(domain);
    let mut i = 0;
    let mut permuted = false;
    for &e in elements {
        st[RATE + i] += e;
        i += 1;
        if i == 8 {
            Rp64_256::apply_permutation(&mut st);
            permuted = true;
            i = 0;
        }
    }
    if i > 0 || !permuted {
        Rp64_256::apply_permutation(&mut st);
    }
    st[RATE..RATE + DIG].try_into().unwrap()
}

fn start_node(
    digest: &[BaseElement; DIG],
    sibling: &[BaseElement; DIG],
    bit: bool,
    state: &mut [BaseElement],
    base: usize,
) {
    for k in 0..W {
        state[base + k] = BaseElement::ZERO;
    }
    state[base] = BaseElement::new(NODE_ELEMENTS);
    state[base + 1] = BaseElement::new(DOMAIN_NODE);
    let (l, r) = if bit { (sibling, digest) } else { (digest, sibling) };
    for i in 0..DIG {
        state[base + RATE + i] = l[i];
        state[base + RATE + DIG + i] = r[i];
    }
}

fn build_trace(w: &Witness) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(TRACE_WIDTH, TRACE_LEN);
    trace.fill(
        |state| {
            start_node(&w.commitment, &w.siblings[0], w.bits[0], state, M);
            state[BIT_COL] = if w.bits[0] { BaseElement::ONE } else { BaseElement::ZERO };
            // nullifier instance: H_dom(4, limbs(nk) ‖ limbs(rho))
            for k in 0..W {
                state[N + k] = BaseElement::ZERO;
            }
            state[N] = BaseElement::new(NF_ELEMENTS);
            state[N + 1] = BaseElement::new(DOMAIN_NULLIFIER);
            for i in 0..DIG {
                state[N + RATE + i] = w.nk[i];
                state[N + RATE + DIG + i] = w.rho[i];
            }
        },
        |step, state| {
            let pos = step % CYCLE;
            if pos < ROUNDS {
                for base in [M, N] {
                    let mut s: [BaseElement; W] =
                        state[base..base + W].try_into().unwrap();
                    Rp64_256::apply_round(&mut s, pos);
                    state[base..base + W].copy_from_slice(&s);
                }
            } else {
                let level = step / CYCLE + 1;
                let digest: [BaseElement; DIG] =
                    state[M + RATE..M + RATE + DIG].try_into().unwrap();
                let bit = w.bits[level];
                start_node(&digest, &w.siblings[level], bit, state, M);
                state[BIT_COL] = if bit { BaseElement::ONE } else { BaseElement::ZERO };

                // nullifier instance idles by chaining its own digest
                let nd: [BaseElement; DIG] =
                    state[N + RATE..N + RATE + DIG].try_into().unwrap();
                for k in 0..W {
                    state[N + k] = BaseElement::ZERO;
                }
                state[N] = BaseElement::new(NF_ELEMENTS);
                state[N + 1] = BaseElement::new(DOMAIN_NULLIFIER);
                for i in 0..DIG {
                    state[N + RATE + i] = nd[i];
                    state[N + RATE + DIG + i] = nd[i];
                }
            }
        },
    );
    trace
}

// ---------------------------------------------------------------------------

struct SpendProver {
    options: ProofOptions,
}

impl Prover for SpendProver {
    type BaseField = BaseElement;
    type Air = SpendAir;
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
        let mut anchor = [BaseElement::ZERO; DIG];
        let mut nullifier = [BaseElement::ZERO; DIG];
        for i in 0..DIG {
            anchor[i] = trace.get(M + RATE + i, ANCHOR_ROW);
            nullifier[i] = trace.get(N + RATE + i, NF_ROW);
        }
        PublicInputs { anchor, nullifier }
    }
    fn options(&self) -> &ProofOptions {
        &self.options
    }
    fn new_trace_lde<E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        ti: &TraceInfo,
        mt: &ColMatrix<Self::BaseField>,
        d: &StarkDomain<Self::BaseField>,
        po: PartitionOptions,
    ) -> (Self::TraceLde<E>, TracePolyTable<E>) {
        DefaultTraceLde::new(ti, mt, d, po)
    }
    fn build_constraint_commitment<E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        cpt: CompositionPolyTrace<E>,
        n: usize,
        d: &StarkDomain<Self::BaseField>,
        po: PartitionOptions,
    ) -> (Self::ConstraintCommitment<E>, CompositionPoly<E>) {
        DefaultConstraintCommitment::new(cpt, n, d, po)
    }
    fn new_evaluator<'a, E: FieldElement<BaseField = Self::BaseField>>(
        &self,
        air: &'a Self::Air,
        aux: Option<AuxRandElements<E>>,
        cc: winterfell::ConstraintCompositionCoefficients<E>,
    ) -> Self::ConstraintEvaluator<'a, E> {
        DefaultConstraintEvaluator::new(air, aux, cc)
    }
}

fn verify_at(proof: Proof, pi: PublicInputs, bits: u32) -> bool {
    winterfell::verify::<SpendAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        pi,
        &AcceptableOptions::MinConjecturedSecurity(bits),
    )
    .is_ok()
}

fn main() {
    println!("Step 2.2 -- Merkle membership + nullifier integrity\n");

    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    let path = p.join("tests").join("vectors").join("shielded_rescue-rp64-256.json");
    let j: Value =
        serde_json::from_str(&fs::read_to_string(&path).expect("read golden")).expect("json");

    // the same note supplies both halves, so the witness is coherent even though
    // the AIR does not yet enforce that it is the same note (step 2.3 does)
    // The synthetic deep path, not one of the real ones. Position 0xA5A5A5A5 is
    // 10100101 repeating, so both the left- and right-child branches of the
    // sibling-placement constraint are exercised at all 32 levels, with no run
    // longer than two in either direction. A witness with zero direction bits
    // (position 0, or any small position) leaves the bit column identically zero,
    // which collapses that constraint from degree 2 to degree 1 and silently
    // skips the right-child branch entirely.
    // The deep path's leaf is notes[0]'s commitment, so that note supplies the
    // nullifier half. Step 2.2 does not bind the two halves anyway -- 2.3 does.
    let entry = &j["merkle"]["synthetic_deep_path"];
    let note = &j["notes"][0];
    let position = entry["position"].as_u64().unwrap() as usize;
    let cm = unhex(entry["commitment"].as_str().unwrap());
    assert_eq!(cm, unhex(note["commitment"].as_str().unwrap()), "note/path mismatch");
    let golden_anchor = unhex(entry["root"].as_str().unwrap());
    let golden_nf = unhex(note["nullifier"].as_str().unwrap());
    let nk = unhex(note["nullifier_key"].as_str().unwrap());
    let rho = unhex(note["rho"].as_str().unwrap());

    println!("witness from the node's published vectors:");
    println!("  commitment {}", entry["commitment"].as_str().unwrap());
    println!("  anchor     {}", entry["root"].as_str().unwrap());
    println!("  nullifier  {}", note["nullifier"].as_str().unwrap());

    let siblings: Vec<[BaseElement; DIG]> = entry["siblings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| limbs(&unhex(v.as_str().unwrap())))
        .collect();
    let bits: Vec<bool> = (0..DEPTH).map(|l| (position >> l) & 1 == 1).collect();

    let w = Witness {
        commitment: limbs(&cm),
        siblings,
        bits,
        nk: limbs(&nk),
        rho: limbs(&rho),
    };
    let trace = build_trace(&w);

    // ---- both halves must agree with the node ------------------------------
    let mut anchor = [BaseElement::ZERO; DIG];
    let mut nf = [BaseElement::ZERO; DIG];
    for i in 0..DIG {
        anchor[i] = trace.get(M + RATE + i, ANCHOR_ROW);
        nf[i] = trace.get(N + RATE + i, NF_ROW);
    }
    assert_eq!(anchor, limbs(&golden_anchor), "AIR anchor disagrees with the node");
    println!("\nAIR anchor matches the node                : OK");
    assert_eq!(nf, limbs(&golden_nf), "AIR nullifier disagrees with the node");
    println!("AIR nullifier matches the node             : OK");

    let mut e = w.nk.to_vec();
    e.extend_from_slice(&w.rho);
    assert_eq!(h_dom(DOMAIN_NULLIFIER, &e), nf, "native H_dom disagrees");
    println!("native H_dom(4, nk||rho) matches too       : OK");
    println!("trace rows: {TRACE_LEN}  columns: {TRACE_WIDTH}\n");

    // ---- prove -------------------------------------------------------------
    println!(
        "{:<34} {:>11} {:>10} {:>10} {:>8}",
        "config", "proof bytes", "prove ms", "verify ms", "128-bit"
    );
    println!("{}", "-".repeat(78));

    for (label, opts) in [
        (
            "96-bit  (32q, blowup 8, cubic)",
            ProofOptions::new(32, 8, 0, FieldExtension::Cubic, 8, 31,
                              BatchingMethod::Linear, BatchingMethod::Linear),
        ),
        (
            "128-bit (43q, blowup 8, cubic)",
            ProofOptions::new(43, 8, 0, FieldExtension::Cubic, 8, 31,
                              BatchingMethod::Linear, BatchingMethod::Linear),
        ),
    ] {
        let prover = SpendProver { options: opts };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let t = Instant::now();
        for _ in 0..20 {
            assert!(
                verify_at(proof.clone(), PublicInputs { anchor, nullifier: nf }, 95),
                "honest proof rejected"
            );
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / 20.0;
        let ok128 = verify_at(proof.clone(), PublicInputs { anchor, nullifier: nf }, 128);

        println!(
            "{label:<34} {size:>11} {prove_ms:>10.1} {verify_ms:>10.3} {:>8}",
            if ok128 { "yes" } else { "no" }
        );
    }

    // ---- soundness ---------------------------------------------------------
    println!("\nsoundness:");
    let prover = SpendProver {
        options: ProofOptions::new(43, 8, 0, FieldExtension::Cubic, 8, 31,
                                   BatchingMethod::Linear, BatchingMethod::Linear),
    };
    let proof = prover.prove(trace.clone()).unwrap();
    let mut bad_anchor = anchor;
    bad_anchor[0] += BaseElement::ONE;
    println!(
        "  wrong anchor rejected                    : {}",
        if verify_at(proof.clone(), PublicInputs { anchor: bad_anchor, nullifier: nf }, 95) {
            "NO -- UNSOUND"
        } else {
            "yes"
        }
    );
    let mut bad_nf = nf;
    bad_nf[0] += BaseElement::ONE;
    println!(
        "  wrong nullifier rejected                 : {}",
        if verify_at(proof, PublicInputs { anchor, nullifier: bad_nf }, 95) {
            "NO -- UNSOUND"
        } else {
            "yes"
        }
    );

    // a different rho must move the nullifier
    let mut w2_rho = w.rho;
    w2_rho[0] += BaseElement::ONE;
    let w2 = Witness { rho: w2_rho, ..Witness {
        commitment: w.commitment,
        siblings: w.siblings.clone(),
        bits: w.bits.clone(),
        nk: w.nk,
        rho: w2_rho,
    } };
    let t2 = build_trace(&w2);
    let mut nf2 = [BaseElement::ZERO; DIG];
    for i in 0..DIG {
        nf2[i] = t2.get(N + RATE + i, NF_ROW);
    }
    println!(
        "  different rho -> different nullifier     : {}",
        if nf2 != nf { "yes" } else { "NO -- COLLISION" }
    );
    let p2 = prover.prove(t2).unwrap();
    println!(
        "  proof with altered rho rejected vs real nf: {}",
        if verify_at(p2, PublicInputs { anchor, nullifier: nf }, 95) {
            "NO -- UNSOUND"
        } else {
            "yes"
        }
    );
}
