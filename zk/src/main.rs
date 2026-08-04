//! Phase 1 spike: prove the Winterfell pipeline end to end on the canonical
//! 2-term Fibonacci AIR, measure proof size / prove time / verify time, and
//! confirm that a corrupted proof is rejected.
//!
//! This deliberately does NOT touch WEPO's shielded pool. It answers one
//! question only: are raw STARK proofs small and fast enough to be worth
//! building a real circuit on?

use std::panic::{self, AssertUnwindSafe};
use std::time::Instant;

use winterfell::{
    crypto::{hashers::Blake3_256, DefaultRandomCoin, MerkleTree},
    math::{fields::f128::BaseElement, FieldElement, ToElements},
    matrix::ColMatrix,
    AcceptableOptions, Air, AirContext, Assertion, AuxRandElements, BatchingMethod,
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment, DefaultConstraintEvaluator,
    DefaultTraceLde, EvaluationFrame, FieldExtension, PartitionOptions, Proof, ProofOptions,
    Prover, StarkDomain, Trace, TraceInfo, TracePolyTable, TraceTable, TransitionConstraintDegree,
};

type Blake3 = Blake3_256<BaseElement>;

// ---------------------------------------------------------------------------
// AIR
// ---------------------------------------------------------------------------

pub struct PublicInputs {
    result: BaseElement,
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        vec![self.result]
    }
}

/// Two-term Fibonacci: each row advances the sequence by two steps, so a
/// trace of length n proves 2n Fibonacci steps.
pub struct FibAir {
    context: AirContext<BaseElement>,
    result: BaseElement,
}

impl Air for FibAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        assert_eq!(2, trace_info.width());
        // both transition constraints are linear in the trace columns
        let degrees = vec![TransitionConstraintDegree::new(1); 2];
        FibAir {
            context: AirContext::new(trace_info, degrees, 3, options),
            result: pub_inputs.result,
        }
    }

    fn evaluate_transition<E: FieldElement + From<Self::BaseField>>(
        &self,
        frame: &EvaluationFrame<E>,
        _periodic_values: &[E],
        result: &mut [E],
    ) {
        let current = frame.current();
        let next = frame.next();
        // s0' = s0 + s1
        result[0] = next[0] - (current[0] + current[1]);
        // s1' = s1 + s0'
        result[1] = next[1] - (current[1] + next[0]);
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let last_step = self.trace_length() - 1;
        vec![
            Assertion::single(0, 0, Self::BaseField::ONE),
            Assertion::single(1, 0, Self::BaseField::ONE),
            Assertion::single(1, last_step, self.result),
        ]
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

fn build_fib_trace(n: usize) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(2, n);
    trace.fill(
        |state| {
            state[0] = BaseElement::ONE;
            state[1] = BaseElement::ONE;
        },
        |_, state| {
            state[0] += state[1];
            state[1] += state[0];
        },
    );
    trace
}

// ---------------------------------------------------------------------------
// Prover
// ---------------------------------------------------------------------------

struct FibProver {
    options: ProofOptions,
}

impl Prover for FibProver {
    type BaseField = BaseElement;
    type Air = FibAir;
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
        let last_step = trace.length() - 1;
        PublicInputs {
            result: trace.get(1, last_step),
        }
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

fn proof_options() -> ProofOptions {
    ProofOptions::new(
        32, // queries
        8,  // blowup
        0,  // grinding
        FieldExtension::None,
        8,  // FRI folding factor
        31, // FRI max remainder degree
        BatchingMethod::Linear,
        BatchingMethod::Linear,
    )
}

fn verify_proof(proof: Proof, result: BaseElement) -> bool {
    let min_opts = AcceptableOptions::MinConjecturedSecurity(95);
    winterfell::verify::<FibAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        PublicInputs { result },
        &min_opts,
    )
    .is_ok()
}

#[derive(PartialEq)]
enum Outcome {
    Accepted,
    Rejected,
    Panicked,
}

/// Verification that survives a panicking verifier. A malformed proof can trip
/// an `assert!` inside AIR construction, which unwinds instead of returning an
/// error -- that is a crash, not a rejection, and the boundary must treat it as
/// such.
fn verify_catching(proof: Proof, result: BaseElement) -> Outcome {
    match panic::catch_unwind(AssertUnwindSafe(|| verify_proof(proof, result))) {
        Ok(true) => Outcome::Accepted,
        Ok(false) => Outcome::Rejected,
        Err(_) => Outcome::Panicked,
    }
}

// ---------------------------------------------------------------------------

fn main() {
    println!("Winterfell 0.13.1 | field f128 | Blake3_256 | 32 queries, blowup 8, no grinding");
    println!("host: x86_64-pc-windows-gnu, release build\n");

    println!(
        "{:>10} {:>12} {:>14} {:>14} {:>14}",
        "trace", "fib steps", "proof bytes", "prove ms", "verify ms"
    );
    println!("{}", "-".repeat(68));

    let sizes = [1024usize, 4096, 16384, 65536, 262144];
    let mut baseline: Option<(Proof, BaseElement)> = None;

    for &n in sizes.iter() {
        let trace = build_fib_trace(n);
        let last_step = trace.length() - 1;
        let result = trace.get(1, last_step);

        let prover = FibProver {
            options: proof_options(),
        };

        let t0 = Instant::now();
        let proof = prover.prove(trace).expect("proving failed");
        let prove_ms = t0.elapsed().as_secs_f64() * 1000.0;

        let bytes = proof.to_bytes();

        // verify a few times and take the mean; a single run is dominated by noise
        let iters = 20;
        let t1 = Instant::now();
        for _ in 0..iters {
            assert!(verify_proof(proof.clone(), result), "honest proof rejected");
        }
        let verify_ms = t1.elapsed().as_secs_f64() * 1000.0 / iters as f64;

        println!(
            "{:>10} {:>12} {:>14} {:>14.1} {:>14.3}",
            n,
            n * 2,
            bytes.len(),
            prove_ms,
            verify_ms
        );

        if n == 4096 {
            baseline = Some((proof, result));
        }
    }

    // -----------------------------------------------------------------------
    // Corruption test: a proof that has been tampered with must never verify.
    // -----------------------------------------------------------------------
    println!("\ncorruption test (trace 4096)");
    println!("{}", "-".repeat(68));

    let (proof, result) = baseline.expect("baseline proof missing");
    let clean = proof.to_bytes();

    // sanity: the untouched round trip must still verify
    let reparsed = Proof::from_bytes(&clean).expect("clean proof failed to parse");
    assert!(verify_proof(reparsed, result), "clean round trip rejected");
    println!("  clean round trip                       : ACCEPTED (expected)");

    let mut rejected_at_parse = 0;
    let mut rejected_at_verify = 0;
    let mut panicked = 0;
    let mut wrongly_accepted = 0;

    // the verifier is expected to panic on some inputs; keep the output readable
    let prev_hook = panic::take_hook();
    panic::set_hook(Box::new(|_| {}));

    // flip one bit in each of 256 positions spread across the whole proof
    let samples = 256usize;
    let positions: Vec<usize> = (0..samples).map(|i| i * clean.len() / samples).collect();
    for &pos in positions.iter() {
        let mut tampered = clean.clone();
        tampered[pos] ^= 0x01;
        if tampered == clean {
            continue;
        }
        match Proof::from_bytes(&tampered) {
            Err(_) => rejected_at_parse += 1,
            Ok(p) => match verify_catching(p, result) {
                Outcome::Accepted => {
                    wrongly_accepted += 1;
                    println!("  !! byte {pos} accepted after tampering");
                }
                Outcome::Rejected => rejected_at_verify += 1,
                Outcome::Panicked => panicked += 1,
            },
        }
    }

    panic::set_hook(prev_hook);

    println!("  tampered proofs rejected at parse      : {rejected_at_parse}");
    println!("  tampered proofs rejected at verify     : {rejected_at_verify}");
    println!("  tampered proofs that PANICKED verifier : {panicked}");
    println!("  tampered proofs WRONGLY ACCEPTED       : {wrongly_accepted}");

    // also confirm a correct proof against a wrong public input is rejected
    let wrong = verify_proof(
        Proof::from_bytes(&clean).unwrap(),
        result + BaseElement::ONE,
    );
    println!(
        "  honest proof vs wrong public input     : {}",
        if wrong {
            "!! ACCEPTED"
        } else {
            "REJECTED (expected)"
        }
    );

    if wrongly_accepted == 0 && !wrong {
        println!("\nRESULT: pipeline sound on this machine.");
    } else {
        println!("\nRESULT: *** UNSOUND -- investigate before proceeding ***");
        std::process::exit(1);
    }
}
