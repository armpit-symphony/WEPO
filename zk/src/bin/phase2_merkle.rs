//! Phase 2, part 2: in-circuit Merkle membership, depth 32, with Rescue-Prime.
//!
//! This is the operation the spend circuit actually performs: prove that a note
//! commitment sits under a published anchor, without revealing which leaf. The
//! cost is MERKLE_DEPTH hash invocations *inside the AIR*, which is the whole
//! reason the in-circuit hash choice matters.
//!
//! Layout: one Rescue permutation per tree level, 7 rounds each, laid out in an
//! 8-row cycle (7 round rows + 1 row where the digest is carried into the next
//! level and the sibling is absorbed). 32 levels * 8 rows = 256 rows.
//! Width is 13: 12 state elements + 1 path bit.
//!
//! NOTE: the leaf is deliberately unconstrained here -- in the real circuit it
//! is bound to the note commitment. This measures the *Merkle* cost, which is
//! what Phase 2 has to decide on.

use std::time::Instant;

use winterfell::{
    crypto::{hashers::Blake3_256, hashers::Rp64_256, DefaultRandomCoin, MerkleTree},
    math::{fields::f64::BaseElement, FieldElement, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment,
    DefaultConstraintEvaluator, DefaultTraceLde, EvaluationFrame, FieldExtension,
    PartitionOptions, Proof, ProofOptions, Prover, StarkDomain, Trace, TraceInfo,
    TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

const STATE_WIDTH: usize = 12;
const RATE_START: usize = 4;
const DIGEST_LEN: usize = 4;
const NUM_ROUNDS: usize = 7;
const CYCLE_LEN: usize = 8;
const MERKLE_DEPTH: usize = 32;
const TRACE_WIDTH: usize = STATE_WIDTH + 1;
const BIT_COL: usize = STATE_WIDTH;
const TRACE_LEN: usize = MERKLE_DEPTH * CYCLE_LEN;

// ---------------------------------------------------------------------------
// linear algebra over the extension field
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
    root: [BaseElement; DIGEST_LEN],
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        self.root.to_vec()
    }
}

pub struct MerkleAir {
    context: AirContext<BaseElement>,
    root: [BaseElement; DIGEST_LEN],
}

impl Air for MerkleAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        // NOTE: Air::new cannot return Result -- see Phase 1. Any validation
        // here can only panic, which is why the verifier must stay behind a
        // process boundary.
        assert_eq!(TRACE_WIDTH, trace_info.width());

        let mut degrees = Vec::new();
        // 12 Rescue round constraints, degree 7, masked by an 8-row periodic flag
        for _ in 0..STATE_WIDTH {
            degrees.push(TransitionConstraintDegree::with_cycles(7, vec![CYCLE_LEN]));
        }
        // path bit is binary
        degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN]));
        // digest carried into the correct half of the next rate (4 constraints)
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(2, vec![CYCLE_LEN]));
        }
        // capacity resets to zero at each level (4 constraints)
        for _ in 0..DIGEST_LEN {
            degrees.push(TransitionConstraintDegree::with_cycles(1, vec![CYCLE_LEN]));
        }

        MerkleAir {
            context: AirContext::new(trace_info, degrees, 8, options),
            root: pub_inputs.root,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let mut cols = Vec::with_capacity(1 + 2 * STATE_WIDTH);

        // hash flag: 1 on the 7 round rows, 0 on the carry row
        let mut flag = vec![Self::BaseField::ONE; CYCLE_LEN];
        flag[CYCLE_LEN - 1] = Self::BaseField::ZERO;
        cols.push(flag);

        // ARK1 then ARK2, one column per state element, zero-padded to the cycle
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
        periodic_values: &[E],
        result: &mut [E],
    ) {
        let cur = frame.current();
        let next = frame.next();

        let hash_flag = periodic_values[0];
        let carry_flag = E::ONE - hash_flag;
        let ark1 = &periodic_values[1..1 + STATE_WIDTH];
        let ark2 = &periodic_values[1 + STATE_WIDTH..1 + 2 * STATE_WIDTH];

        // -- Rescue round -----------------------------------------------------
        // forward half:  step1 = MDS * cur^7 + ARK1
        // backward half: step1 = (INV_MDS * (next - ARK2))^7
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

        // -- level carry ------------------------------------------------------
        // On the carry row the digest (cur[4..8]) moves into either the low or
        // the high half of the next rate, selected by the next level's path bit.
        let b = next[BIT_COL];
        let mut idx = STATE_WIDTH;

        result[idx] = carry_flag * (b * b - b);
        idx += 1;

        for i in 0..DIGEST_LEN {
            let d = cur[RATE_START + i];
            // b == 0 -> digest is the left child; b == 1 -> digest is the right
            let placed = (E::ONE - b) * (next[RATE_START + i] - d)
                + b * (next[RATE_START + DIGEST_LEN + i] - d);
            result[idx + i] = carry_flag * placed;
        }
        idx += DIGEST_LEN;

        for i in 0..DIGEST_LEN {
            result[idx + i] = carry_flag * next[i];
        }
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let last = self.trace_length() - 1;
        let mut a = Vec::with_capacity(8);
        // capacity starts zeroed
        for i in 0..DIGEST_LEN {
            a.push(Assertion::single(i, 0, Self::BaseField::ZERO));
        }
        // the final digest is the published anchor
        for i in 0..DIGEST_LEN {
            a.push(Assertion::single(RATE_START + i, last, self.root[i]));
        }
        a
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// ---------------------------------------------------------------------------
// trace
// ---------------------------------------------------------------------------

struct Witness {
    leaf: [BaseElement; DIGEST_LEN],
    siblings: Vec<[BaseElement; DIGEST_LEN]>,
    bits: Vec<bool>,
}

fn sample_witness() -> Witness {
    // deterministic, non-random: we are measuring cost, not secrecy
    let leaf = [
        BaseElement::new(11),
        BaseElement::new(22),
        BaseElement::new(33),
        BaseElement::new(44),
    ];
    let siblings = (0..MERKLE_DEPTH)
        .map(|i| {
            let b = (i as u64 + 1) * 1000;
            [
                BaseElement::new(b),
                BaseElement::new(b + 1),
                BaseElement::new(b + 2),
                BaseElement::new(b + 3),
            ]
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
    for s in state.iter_mut().take(RATE_START) {
        *s = BaseElement::ZERO;
    }
    let (l, r) = if bit { (sibling, digest) } else { (digest, sibling) };
    for i in 0..DIGEST_LEN {
        state[RATE_START + i] = l[i];
        state[RATE_START + DIGEST_LEN + i] = r[i];
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
                let mut s: [BaseElement; STATE_WIDTH] =
                    state[..STATE_WIDTH].try_into().unwrap();
                Rp64_256::apply_round(&mut s, pos);
                state[..STATE_WIDTH].copy_from_slice(&s);
            } else {
                // carry row: fold the digest into the next level
                let level = step / CYCLE_LEN + 1;
                let digest: [BaseElement; DIGEST_LEN] = state
                    [RATE_START..RATE_START + DIGEST_LEN]
                    .try_into()
                    .unwrap();
                let bit = w.bits[level];
                arrange(&digest, &w.siblings[level], bit, state);
                state[BIT_COL] = if bit { BaseElement::ONE } else { BaseElement::ZERO };
            }
        },
    );
    trace
}

// ---------------------------------------------------------------------------
// prover
// ---------------------------------------------------------------------------

struct MerkleProver {
    options: ProofOptions,
}

impl Prover for MerkleProver {
    type BaseField = BaseElement;
    type Air = MerkleAir;
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
            *r = trace.get(RATE_START + i, last);
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

// ---------------------------------------------------------------------------

fn verify_at(proof: Proof, root: [BaseElement; DIGEST_LEN], bits: u32) -> bool {
    let opts = AcceptableOptions::MinConjecturedSecurity(bits);
    winterfell::verify::<MerkleAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        PublicInputs { root },
        &opts,
    )
    .is_ok()
}

struct Config {
    label: &'static str,
    opts: ProofOptions,
}

fn main() {
    println!("Phase 2 -- in-circuit Merkle membership, Rescue-Prime Rp64_256");
    println!("field f64 (Goldilocks), depth {MERKLE_DEPTH}, {NUM_ROUNDS} rounds/level");
    println!("trace: {TRACE_LEN} rows x {TRACE_WIDTH} cols\n");

    let w = sample_witness();
    let trace = build_trace(&w);

    // sanity: the AIR-computed root must equal the natively-computed root
    let last = trace.length() - 1;
    let mut root = [BaseElement::ZERO; DIGEST_LEN];
    for (i, r) in root.iter_mut().enumerate() {
        *r = trace.get(RATE_START + i, last);
    }
    let mut expect = w.leaf;
    for lvl in 0..MERKLE_DEPTH {
        let mut st = [BaseElement::ZERO; STATE_WIDTH];
        arrange(&expect, &w.siblings[lvl], w.bits[lvl], &mut st);
        Rp64_256::apply_permutation(&mut st);
        expect.copy_from_slice(&st[RATE_START..RATE_START + DIGEST_LEN]);
    }
    assert_eq!(root, expect, "AIR trace disagrees with native Rescue");
    println!("trace root matches native Rescue recomputation: OK\n");

    let configs = vec![
        Config {
            label: "96-bit  (32q, blowup 8, cubic)",
            opts: ProofOptions::new(
                32, 8, 0, FieldExtension::Cubic, 8, 31,
                BatchingMethod::Linear, BatchingMethod::Linear,
            ),
        },
        Config {
            label: "128-bit (43q, blowup 8, cubic)",
            opts: ProofOptions::new(
                43, 8, 0, FieldExtension::Cubic, 8, 31,
                BatchingMethod::Linear, BatchingMethod::Linear,
            ),
        },
        Config {
            label: "128-bit (32q, blowup 16, cubic)",
            opts: ProofOptions::new(
                32, 16, 0, FieldExtension::Cubic, 8, 31,
                BatchingMethod::Linear, BatchingMethod::Linear,
            ),
        },
        Config {
            label: "128-bit (28q, blowup 8, grind 16)",
            opts: ProofOptions::new(
                28, 8, 16, FieldExtension::Cubic, 8, 31,
                BatchingMethod::Linear, BatchingMethod::Linear,
            ),
        },
    ];

    println!(
        "{:<36} {:>11} {:>10} {:>10} {:>7} {:>7}",
        "config", "proof bytes", "prove ms", "verify ms", "96-bit", "128-bit"
    );
    println!("{}", "-".repeat(88));

    for c in configs {
        let prover = MerkleProver { options: c.opts };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("proving failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let iters = 20;
        let t = Instant::now();
        for _ in 0..iters {
            assert!(verify_at(proof.clone(), root, 95), "honest proof rejected");
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / iters as f64;

        let ok96 = verify_at(proof.clone(), root, 95);
        let ok128 = verify_at(proof.clone(), root, 128);

        println!(
            "{:<36} {:>11} {:>10.1} {:>10.3} {:>7} {:>7}",
            c.label,
            size,
            prove_ms,
            verify_ms,
            if ok96 { "yes" } else { "no" },
            if ok128 { "yes" } else { "no" }
        );
    }

    // soundness spot-check: wrong root must be rejected
    let prover = MerkleProver {
        options: ProofOptions::new(
            32, 8, 0, FieldExtension::Cubic, 8, 31,
            BatchingMethod::Linear, BatchingMethod::Linear,
        ),
    };
    let proof = prover.prove(trace.clone()).unwrap();
    let mut bad = root;
    bad[0] += BaseElement::ONE;
    println!(
        "\nwrong anchor rejected: {}",
        if verify_at(proof, bad, 95) { "NO -- UNSOUND" } else { "yes" }
    );
}
