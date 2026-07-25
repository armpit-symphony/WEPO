//! Phase 3 prep: is Jive a better in-circuit 2-to-1 than the Rp64_256 sponge?
//!
//! Both compress two 4-element digests to one in a single permutation, but the
//! state widths differ:
//!
//!   Rp64_256      state 12, sponge, digest = state[4..8] after permuting
//!   RpJive64_256  state  8, Jive compression (eprint 2022/840):
//!                 out[i] = init[i] + init[4+i] + final[i] + final[4+i]
//!
//! A narrower state is directly cheaper in an AIR: 8 transition constraints per
//! round instead of 12, and an 8x8 MDS instead of 12x12.
//!
//! The Jive summation needs the *initial* state at the end of the cycle, which a
//! two-row frame cannot reach back to. Rather than carrying all 8 initial
//! elements, we fold them up front into 4: carry[i] = init[i] + init[4+i]. Then
//! out[i] = carry[i] + final[i] + final[4+i]. That keeps the trace at 13 columns
//! -- the same as the Rp64_256 version -- while the permutation gets narrower.
//!
//! Baseline to beat: Rp64_256 depth-32 membership, 35,049 B at 128-bit.
//!
//! NOTE: this measures cost. The cycle-0 carry-consistency constraint is
//! omitted (4 degree-1 constraints, no measurable effect on size); the real
//! circuit binds it via the leaf, which is a public input there.

use std::time::Instant;

use winterfell::{
    crypto::{hashers::Blake3_256, hashers::Rp64_256, hashers::RpJive64_256, DefaultRandomCoin,
             Digest as _, Hasher, MerkleTree},
    math::{fields::f64::BaseElement, FieldElement, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment,
    DefaultConstraintEvaluator, DefaultTraceLde, EvaluationFrame, FieldExtension,
    PartitionOptions, Proof, ProofOptions, Prover, StarkDomain, Trace, TraceInfo,
    TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

const W: usize = 8; // Jive state width
const DIGEST_LEN: usize = 4;
const NUM_ROUNDS: usize = 7;
const CYCLE_LEN: usize = 8;
const MERKLE_DEPTH: usize = 32;
const CARRY_START: usize = W; // columns 8..12 hold the folded initial state
// Columns 12..16 hold the running Jive summation, carry[i] + s[i] + s[4+i].
// It is redundant during the rounds, but the final level has no carry row to
// compute it on, so without it the anchor is never materialised in the trace.
const OUT_START: usize = W + DIGEST_LEN;
const BIT_COL: usize = W + 2 * DIGEST_LEN; // column 16
const TRACE_WIDTH: usize = W + 2 * DIGEST_LEN + 1; // 17
const TRACE_LEN: usize = MERKLE_DEPTH * CYCLE_LEN;

fn mds_mul<E: FieldElement + From<BaseElement>>(v: &[E; W]) -> [E; W] {
    let mut out = [E::ZERO; W];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = E::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += E::from(RpJive64_256::MDS[i][j]) * *vj;
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
            acc += E::from(RpJive64_256::INV_MDS[i][j]) * *vj;
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

pub struct PublicInputs {
    root: [BaseElement; DIGEST_LEN],
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        self.root.to_vec()
    }
}

pub struct JiveMerkleAir {
    context: AirContext<BaseElement>,
    root: [BaseElement; DIGEST_LEN],
}

impl Air for JiveMerkleAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        assert_eq!(TRACE_WIDTH, trace_info.width());
        let mut degrees = Vec::new();
        for _ in 0..W {
            degrees.push(TransitionConstraintDegree::with_cycles(7, vec![CYCLE_LEN]));
        }
        for _ in 0..DIGEST_LEN {
            // carry stays constant through the rounds
            degrees.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE_LEN]));
        }
        degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN])); // bit
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN])); // placement
        }
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE_LEN])); // new carry
        }
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::new(1)); // running Jive summation
        }
        JiveMerkleAir {
            context: AirContext::new(trace_info, degrees, 4, options),
            root: pub_inputs.root,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let mut cols = Vec::with_capacity(1 + 2 * W);
        let mut flag = vec![Self::BaseField::ONE; CYCLE_LEN];
        flag[CYCLE_LEN - 1] = Self::BaseField::ZERO;
        cols.push(flag);
        for j in 0..W {
            let mut c = vec![Self::BaseField::ZERO; CYCLE_LEN];
            for r in 0..NUM_ROUNDS {
                c[r] = RpJive64_256::ARK1[r][j];
            }
            cols.push(c);
        }
        for j in 0..W {
            let mut c = vec![Self::BaseField::ZERO; CYCLE_LEN];
            for r in 0..NUM_ROUNDS {
                c[r] = RpJive64_256::ARK2[r][j];
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
        let carry_flag = E::ONE - hash_flag;
        let ark1 = &periodic[1..1 + W];
        let ark2 = &periodic[1 + W..1 + 2 * W];

        // -- Rescue round over the 8-wide Jive state --------------------------
        let mut sbox = [E::ZERO; W];
        for i in 0..W {
            sbox[i] = pow7(cur[i]);
        }
        let mut step1 = mds_mul(&sbox);
        for i in 0..W {
            step1[i] += ark1[i];
        }
        let mut back = [E::ZERO; W];
        for i in 0..W {
            back[i] = next[i] - ark2[i];
        }
        let inv = inv_mds_mul(&back);
        for i in 0..W {
            result[i] = hash_flag * (step1[i] - pow7(inv[i]));
        }
        let mut idx = W;

        // -- carry holds the folded initial state for the whole cycle ---------
        for i in 0..DIGEST_LEN {
            result[idx + i] = hash_flag * (next[CARRY_START + i] - cur[CARRY_START + i]);
        }
        idx += DIGEST_LEN;

        // -- carry row: Jive summation, then place the digest -----------------
        let b = next[BIT_COL];
        result[idx] = carry_flag * (b * b - b);
        idx += 1;

        for i in 0..DIGEST_LEN {
            // the Jive summation of this cycle is already sitting in `out`
            let d = cur[OUT_START + i];
            let placed = (E::ONE - b) * (next[i] - d) + b * (next[DIGEST_LEN + i] - d);
            result[idx + i] = carry_flag * placed;
        }
        idx += DIGEST_LEN;

        for i in 0..DIGEST_LEN {
            // the next cycle's carry folds its own initial state
            result[idx + i] =
                carry_flag * (next[CARRY_START + i] - (next[i] + next[DIGEST_LEN + i]));
        }
        idx += DIGEST_LEN;

        // -- running Jive summation, every row ---------------------------------
        // out[i] = carry[i] + s[i] + s[4+i]. Holds unconditionally, which is what
        // makes the final level's anchor readable at the last row.
        for i in 0..DIGEST_LEN {
            result[idx + i] =
                next[OUT_START + i] - (next[CARRY_START + i] + next[i] + next[DIGEST_LEN + i]);
        }
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let last = self.trace_length() - 1;
        // the anchor is the Jive summation of the final cycle
        (0..DIGEST_LEN)
            .map(|i| Assertion::single(OUT_START + i, last, self.root[i]))
            .collect()
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// ---------------------------------------------------------------------------

struct Witness {
    leaf: [BaseElement; DIGEST_LEN],
    siblings: Vec<[BaseElement; DIGEST_LEN]>,
    bits: Vec<bool>,
}

fn sample_witness() -> Witness {
    let leaf = [11u64, 22, 33, 44].map(BaseElement::new);
    let siblings = (0..MERKLE_DEPTH)
        .map(|i| {
            let b = (i as u64 + 1) * 1000;
            [b, b + 1, b + 2, b + 3].map(BaseElement::new)
        })
        .collect();
    let bits = (0..MERKLE_DEPTH).map(|i| i % 3 == 0).collect();
    Witness { leaf, siblings, bits }
}

fn arrange(
    digest: &[BaseElement; DIGEST_LEN],
    sibling: &[BaseElement; DIGEST_LEN],
    bit: bool,
    state: &mut [BaseElement],
) {
    let (l, r) = if bit { (sibling, digest) } else { (digest, sibling) };
    for i in 0..DIGEST_LEN {
        state[i] = l[i];
        state[DIGEST_LEN + i] = r[i];
    }
    // fold the initial state for the Jive summation at the end of the cycle
    for i in 0..DIGEST_LEN {
        state[CARRY_START + i] = state[i] + state[DIGEST_LEN + i];
    }
    refresh_out(state);
}

/// out[i] = carry[i] + s[i] + s[4+i], recomputed whenever the state moves.
fn refresh_out(state: &mut [BaseElement]) {
    for i in 0..DIGEST_LEN {
        state[OUT_START + i] = state[CARRY_START + i] + state[i] + state[DIGEST_LEN + i];
    }
}

fn build_trace(w: &Witness) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(TRACE_WIDTH, TRACE_LEN);
    trace.fill(
        |state| {
            arrange(&w.leaf, &w.siblings[0], w.bits[0], state);
            state[BIT_COL] = if w.bits[0] { BaseElement::ONE } else { BaseElement::ZERO };
        },
        |step, state| {
            let pos = step % CYCLE_LEN;
            if pos < NUM_ROUNDS {
                let mut s: [BaseElement; W] = state[..W].try_into().unwrap();
                RpJive64_256::apply_round(&mut s, pos);
                state[..W].copy_from_slice(&s);
                refresh_out(state);
            } else {
                let level = step / CYCLE_LEN + 1;
                let mut digest = [BaseElement::ZERO; DIGEST_LEN];
                for i in 0..DIGEST_LEN {
                    digest[i] = state[OUT_START + i];
                }
                let bit = w.bits[level];
                arrange(&digest, &w.siblings[level], bit, state);
                state[BIT_COL] = if bit { BaseElement::ONE } else { BaseElement::ZERO };
            }
        },
    );
    trace
}

struct JiveProver {
    options: ProofOptions,
}

impl Prover for JiveProver {
    type BaseField = BaseElement;
    type Air = JiveMerkleAir;
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
        let last = trace.length() - 1;
        let mut root = [BaseElement::ZERO; DIGEST_LEN];
        for (i, r) in root.iter_mut().enumerate() {
            *r = trace.get(OUT_START + i, last);
        }
        PublicInputs { root }
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

fn verify_at(proof: Proof, root: [BaseElement; DIGEST_LEN], bits: u32) -> bool {
    winterfell::verify::<JiveMerkleAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        PublicInputs { root },
        &AcceptableOptions::MinConjecturedSecurity(bits),
    )
    .is_ok()
}

fn bench_native<F: FnMut()>(label: &str, iters: usize, mut f: F) -> f64 {
    for _ in 0..iters / 10 {
        f();
    }
    let t = Instant::now();
    for _ in 0..iters {
        f();
    }
    let ns = t.elapsed().as_secs_f64() * 1e9 / iters as f64;
    println!("  {label:<38} {ns:>10.1} ns {:>12.0} /s", 1e9 / ns);
    ns
}

fn main() {
    println!("Jive vs Rp64_256 as the in-circuit 2-to-1 compression\n");

    // -- native ------------------------------------------------------------
    println!("native 2-to-1 (out of circuit):");
    let a = Rp64_256::hash(&[1u8; 32]);
    let b = Rp64_256::hash(&[2u8; 32]);
    let sponge = bench_native("Rp64_256::merge      (state 12)", 200_000, || {
        std::hint::black_box(Rp64_256::merge(&[a, b]));
    });
    let ja = RpJive64_256::hash(&[1u8; 32]);
    let jb = RpJive64_256::hash(&[2u8; 32]);
    let jive = bench_native("RpJive64_256::merge  (state  8)", 200_000, || {
        std::hint::black_box(RpJive64_256::merge(&[ja, jb]));
    });
    println!("  -> Jive is {:.2}x the speed of the sponge natively\n", sponge / jive);

    // -- in circuit --------------------------------------------------------
    let w = sample_witness();
    let trace = build_trace(&w);

    // cross-check the trace against the library's own merge
    let last = trace.length() - 1;
    let mut root = [BaseElement::ZERO; DIGEST_LEN];
    for (i, r) in root.iter_mut().enumerate() {
        *r = trace.get(OUT_START + i, last);
    }
    let mut expect = w.leaf;
    for lvl in 0..MERKLE_DEPTH {
        let (l, r) = if w.bits[lvl] { (w.siblings[lvl], expect) } else { (expect, w.siblings[lvl]) };
        let mut init = [BaseElement::ZERO; W];
        init[..DIGEST_LEN].copy_from_slice(&l);
        init[DIGEST_LEN..].copy_from_slice(&r);
        let mut st = init;
        RpJive64_256::apply_permutation(&mut st);
        for i in 0..DIGEST_LEN {
            expect[i] = init[i] + init[DIGEST_LEN + i] + st[i] + st[DIGEST_LEN + i];
        }
    }
    assert_eq!(root, expect, "AIR trace disagrees with native Jive");
    println!("trace root matches native Jive recomputation: OK\n");

    println!("in-circuit depth-32 Merkle membership:");
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
        let prover = JiveProver { options: opts };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let t = Instant::now();
        for _ in 0..20 {
            assert!(verify_at(proof.clone(), root, 95), "honest proof rejected");
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / 20.0;
        let ok128 = verify_at(proof.clone(), root, 128);

        println!(
            "{label:<34} {size:>11} {prove_ms:>10.1} {verify_ms:>10.3} {:>8}",
            if ok128 { "yes" } else { "no" }
        );
    }

    // soundness spot check
    let prover = JiveProver {
        options: ProofOptions::new(43, 8, 0, FieldExtension::Cubic, 8, 31,
                                   BatchingMethod::Linear, BatchingMethod::Linear),
    };
    let proof = prover.prove(trace.clone()).unwrap();
    let mut bad = root;
    bad[0] += BaseElement::ONE;
    println!("\nwrong anchor rejected: {}", if verify_at(proof, bad, 95) { "NO -- UNSOUND" } else { "yes" });
    println!("\nbaseline to beat: Rp64_256 sponge = 35,049 B / 5.7 ms at 128-bit");
}
