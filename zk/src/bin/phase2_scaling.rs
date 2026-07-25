//! Phase 2, part 4: how STARK cost scales with trace geometry.
//!
//! Hand-writing a Keccak-f[1600] AIR is a multi-week project, so instead we
//! measure the cost of a trace *of the shape Keccak requires* and use it as a
//! lower bound on SHA3-256 in-circuit.
//!
//! Why a lower bound: this AIR uses degree-1 transition constraints and no
//! helper columns. Keccak needs bit decomposition of a 1600-bit state, degree-2
//! chi constraints, and extra columns for theta parity -- all strictly worse.
//! If the geometry alone is already disqualifying, the real thing cannot rescue
//! it.
//!
//! Keccak sizing for one SHA3-256 node hash:
//!   - state 1600 bits -> >=1600 binary trace columns
//!   - 24 rounds per permutation -> 24 rows
//!   - 64-byte input < 1088-bit rate -> 1 permutation per node hash
//!   - Merkle depth 32 -> 32 * 24 = 768 rows, round up to 1024
//!
//! Rescue for the same job, measured: 256 rows x 13 columns.

use std::time::Instant;

use winterfell::{
    crypto::{hashers::Blake3_256, DefaultRandomCoin, MerkleTree},
    math::{fields::f64::BaseElement, FieldElement, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment,
    DefaultConstraintEvaluator, DefaultTraceLde, EvaluationFrame, FieldExtension,
    PartitionOptions, Proof, ProofOptions, Prover, StarkDomain, Trace, TraceInfo,
    TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

#[derive(Clone)]
pub struct PublicInputs {
    width: usize,
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        vec![BaseElement::new(self.width as u64)]
    }
}

pub struct WideAir {
    context: AirContext<BaseElement>,
}

impl Air for WideAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, _pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        let w = trace_info.width();
        let degrees = vec![TransitionConstraintDegree::new(1); w];
        WideAir { context: AirContext::new(trace_info, degrees, 1, options) }
    }

    fn evaluate_transition<E: FieldElement + From<Self::BaseField>>(
        &self,
        frame: &EvaluationFrame<E>,
        _periodic_values: &[E],
        result: &mut [E],
    ) {
        let cur = frame.current();
        let next = frame.next();
        for i in 0..result.len() {
            result[i] = next[i] - (cur[i] + E::ONE);
        }
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        vec![Assertion::single(0, 0, Self::BaseField::ZERO)]
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

fn build(width: usize, len: usize) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(width, len);
    trace.fill(
        |state| {
            for (i, s) in state.iter_mut().enumerate() {
                *s = BaseElement::new(i as u64);
            }
        },
        |_, state| {
            for s in state.iter_mut() {
                *s += BaseElement::ONE;
            }
        },
    );
    trace
}

struct WideProver {
    options: ProofOptions,
}

impl Prover for WideProver {
    type BaseField = BaseElement;
    type Air = WideAir;
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
        PublicInputs { width: trace.width() }
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

fn main() {
    println!("Phase 2 -- STARK cost vs trace geometry (128-bit config)");
    println!("43 queries, blowup 8, cubic extension, field f64\n");
    println!(
        "{:>7} {:>7} {:>12} {:>12} {:>12}",
        "width", "rows", "proof bytes", "prove ms", "verify ms"
    );
    println!("{}", "-".repeat(56));

    let opts = ProofOptions::new(
        43, 8, 0, FieldExtension::Cubic, 8, 31,
        BatchingMethod::Linear, BatchingMethod::Linear,
    );

    // Rescue's measured geometry first, then the geometry Keccak needs.
    // NOTE: Winterfell hard-caps trace width at 255 columns (winter-air
    // trace_info.rs:111). Keccak's 1600-bit state cannot be held in columns at
    // all -- it must be spread across rows, trading width for length. These
    // cases bound both directions.
    let cases = [
        (13usize, 256usize),   // Rescue, depth 32 -- the real measured geometry
        (13, 1024),
        (100, 1024),
        (250, 1024),           // ~widest Winterfell allows in practice
        (250, 8192),           // Keccak-shaped under the width cap (see below)
        (250, 32768),
        // --- projected ShieldedBundle geometries (Rescue) -------------------
        // per spend  : 32-level Merkle (256 rows) + nullifier + commitment +
        //              spend auth (~32 rows) + 64-bit range (~64 rows) ~= 512
        // per output : commitment (8 rows) + 64-bit range (~64 rows)   ~= 128
        // width      : 13 state + range bits + balance accumulator     ~= 32
        (32, 1024),            // 1 spend, 2 outputs  -> 768 rows, round to 1024
        (32, 2048),            // 2 spends, 2 outputs -> 1280 rows, round to 2048
        (32, 4096),            // headroom
    ];

    for (w, len) in cases {
        let trace = build(w, len);
        let prover = WideProver { options: opts.clone() };
        let t = Instant::now();
        let proof = prover.prove(trace).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let pi = PublicInputs { width: w };
        let t = Instant::now();
        let ok = winterfell::verify::<WideAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
            proof,
            pi,
            &AcceptableOptions::MinConjecturedSecurity(128),
        )
        .is_ok();
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0;
        assert!(ok, "proof rejected at 128-bit for width {w}");

        println!("{w:>7} {len:>7} {size:>12} {prove_ms:>12.1} {verify_ms:>12.3}");
    }

    println!("\nnote: these are LOWER bounds for Keccak -- degree-1 constraints,");
    println!("no helper columns, no bit-decomposition enforcement.");
}
