//! Step 2.4 — value range, on top of the step 2.3 spend circuit.
//!
//! Adds the missing constraint that `value` lies in [0, 2^63-1]. Everything else
//! is step 2.3 verbatim, so the delta in proof size is the price of the range.
//!
//! WHY IT IS NOT ALREADY IMPLIED. Step 2.3 binds `value` into the commitment, so
//! a spender cannot restate the value of a note somebody else committed. What it
//! does not stop is committing to an out-of-range value in the FIRST place and
//! spending it later: `value` is a Goldilocks element, the field is about 2^64,
//! and the node's MAX_NOTE_VALUE check lives in Python at note construction --
//! which a prover is under no obligation to run. Without this step a note holding
//! 2^63 is a fully consistent witness: correct commitment, correct path, correct
//! nullifier. Step 2.5 would then balance inputs against outputs over a field
//! that wraps, where a value just below p behaves as a small negative number and
//! mints WEPO from nothing. The test at the bottom builds that note and confirms
//! this step is what rejects it.
//!
//! HOW. 63-bit decomposition, most significant bit first, one bit per row over
//! rows 0..62, with a running accumulator that must equal the carried value:
//!
//!     ACC[0]   = 0
//!     ACC[r+1] = 2*ACC[r] + BIT[r]        r = 0..62,  BIT[r] boolean
//!     ACC[63] == value
//!
//! 63 bits is exactly [0, 2^63-1], which is MAX_NOTE_VALUE, so there is no
//! separate upper-bound comparison to get wrong -- the width IS the bound.
//! Rows 63..255 hold the accumulator, so the rule needs no special case at the
//! end of the trace.
//!
//! ONE BIT PER ROW, NOT EIGHT. Packing 8 bits per row finishes in 8 rows but
//! costs 9 columns; one bit per row costs 2 columns and 64 rows. The Merkle path
//! already fixes the trace at 256 rows and leaves every one of them idle in these
//! columns, so rows are the resource in surplus and columns are the one rationed
//! by Winterfell's 254-column cap. That trade is why the bundle projection
//! printed at the end of this run is not hopeless.
//!
//! ---------------------------------------------------------------------------
//! Inherited from step 2.3 — spend authority and binding.
//!
//! Steps 2.1 and 2.2 proved two true statements that were never connected:
//! *some* commitment is under the anchor, and *some* (nk, rho) hash to the
//! revealed nullifier. The repository guardrail "never register a verifier for a
//! partial circuit" names the consequence exactly: commitments are public, so a
//! prover could take any commitment out of the tree, invent an nk, and drain a
//! note they do not own.
//!
//! This step closes it. One proof now shows, for a single note:
//!
//!   nk    = H_dom(5, limbs(ask))                                   (authority)
//!   pk_d  = H_dom(6, limbs(ask) ‖ encode(d))                       (authority)
//!   cm    = H_dom(3, [value] ‖ limbs(pk_d) ‖ limbs(rho) ‖ limbs(rcm))
//!   cm    is the leaf the Merkle path opens under the anchor        (binding)
//!   nf    = H_dom(4, limbs(nk) ‖ limbs(rho))                        (binding)
//!
//! The two bindings are what is new, and they are structural rather than
//! asserted: `rho` lives in ONE set of trace columns that both the commitment
//! and the nullifier read, so "the same rho" is not a constraint that could be
//! omitted -- there is no second rho to disagree with. Likewise `ask` is read at
//! row 0 by both key derivations. The one binding that IS a constraint is
//! cm -> leaf, because the commitment is produced at row 23 and consumed at row
//! 0; see "carrying values backwards" below.
//!
//! Public: anchor, nf. Private: ask, diversifier, value, rho, rcm, position, path.
//!
//! STILL NOT COMPLETE. One spend, no outputs, and nothing balances inputs
//! against outputs (step 2.5). Do not wire a verifier to this. See the guardrail.
//!
//! ---------------------------------------------------------------------------
//! CARRYING VALUES BACKWARDS
//!
//! Five hashes with a dependency chain -- ask -> pk_d -> cm -> Merkle, ask -> nk
//! -> nf -- do not fit end to end in 256 rows: the Merkle path alone fills them.
//! Laying them out sequentially needs 24 + 256 = 280 rows, which Winterfell
//! rounds to 512 with half the trace inert.
//!
//! So the instances run CONCURRENTLY in their own columns, and each dependency
//! becomes an equality between two cells. Forward dependencies (produced at row
//! r, consumed at row r+1) are ordinary fold constraints. The one dependency
//! that runs backwards -- cm is produced at row 23 but the Merkle path consumes
//! it at row 0 -- needs a value visible at both rows, so `cm` gets four columns
//! held constant across the trace (next == cur) and is pinned to the commitment
//! instance's output at row 23 and to the Merkle leaf at row 0. Same for `rho`
//! and `rcm`, which are read at rows 7 and 15 by two different instances.
//!
//!   instance A (12 cols)  rows 0-7   nk        rows 8-15  nf     then idle
//!   instance B (12 cols)  rows 0-7   pk_d      rows 8-23  cm     then idle
//!   instance E (12 cols)  rows 0-255 32 Merkle node hashes
//!   carried     (13 cols) cm(4) rho(4) rcm(4) value(1), constant
//!   bit          (1 col)  Merkle path direction
//!
//! Row-specific rules (start-of-nf at row 7, second cm block at row 15, cm ->
//! leaf at rows 23 and 0) use periodic columns of length 256 as one-hot
//! selectors. Their degree-255 contribution puts the affected constraints at a
//! composition ratio of 3, well inside the blowup of 8 the Rescue rounds already
//! require, so they are free in practice.
//!
//! GEOMETRY. 52 columns x 256 rows. 13 -> 25 -> 50 -> 52 across the four steps;
//! the range gadget costs 2 columns and no rows.

use std::fs;
use std::panic::{self, AssertUnwindSafe};
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
const RATE: usize = 4; // rate occupies indices 4..12
const DIG: usize = 4; // digest length in elements
const ROUNDS: usize = 7;
const CYCLE: usize = 8;
const DEPTH: usize = 32;

const DOMAIN_NODE: u64 = 2;
const DOMAIN_NOTE: u64 = 3;
const DOMAIN_NULLIFIER: u64 = 4;
const DOMAIN_NULLIFIER_KEY: u64 = 5;
const DOMAIN_DIVERSIFIED_KEY: u64 = 6;

const NODE_ELEMENTS: u64 = 8; // limbs(left) ‖ limbs(right)
const NF_ELEMENTS: u64 = 8; // limbs(nk) ‖ limbs(rho)
const NK_ELEMENTS: u64 = 4; // limbs(ask)
const PKD_ELEMENTS: u64 = 7; // limbs(ask) ‖ [11, d0, d1]
const CM_ELEMENTS: u64 = 13; // [value] ‖ limbs(pk_d) ‖ limbs(rho) ‖ limbs(rcm)
const DIVERSIFIER_LEN: u64 = 11;

// --- column layout ----------------------------------------------------------
const A: usize = 0; // nk then nf
const B: usize = A + W; // pk_d then cm
const E: usize = B + W; // Merkle path
const BIT_COL: usize = E + W;
const CM_COL: usize = BIT_COL + 1; // carried, 4
const RHO_COL: usize = CM_COL + DIG; // carried, 4
const RCM_COL: usize = RHO_COL + DIG; // carried, 4
const VAL_COL: usize = RCM_COL + DIG; // carried, 1
const BIT2_COL: usize = VAL_COL + 1; // range: one value bit per row, MSB first
const ACC_COL: usize = BIT2_COL + 1; // range: running recomposition
const TRACE_WIDTH: usize = ACC_COL + 1; // 52

/// MAX_NOTE_VALUE is 2^63-1, so 63 bits IS the bound. Widening this by one bit
/// silently admits values the node would refuse to build a note for.
const VALUE_BITS: usize = 63;
const ACC_ROW: usize = VALUE_BITS; // 63 -- where the recomposition must match

const TRACE_LEN: usize = DEPTH * CYCLE; // 256
const ANCHOR_ROW: usize = TRACE_LEN - 1; // 255
const NF_ROW: usize = 2 * CYCLE - 1; // 15
const CM_ROW: usize = 3 * CYCLE - 1; // 23

// --- periodic column indices ------------------------------------------------
const P_FLAG: usize = 0;
const P_ARK1: usize = 1;
const P_ARK2: usize = 1 + W;
const P_S0: usize = 1 + 2 * W;
const P_S7: usize = P_S0 + 1;
const P_S15: usize = P_S0 + 2;
const P_S23: usize = P_S0 + 3;
const P_RA: usize = P_S0 + 4; // 1 on rows 0..62 -- while bits are absorbed
const P_S63: usize = P_S0 + 5; // 1 on row 63 -- where ACC must equal value

// ---------------------------------------------------------------------------

fn mds_mul<F: FieldElement + From<BaseElement>>(v: &[F; W]) -> [F; W] {
    let mut out = [F::ZERO; W];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = F::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += F::from(Rp64_256::MDS[i][j]) * *vj;
        }
        *o = acc;
    }
    out
}

fn inv_mds_mul<F: FieldElement + From<BaseElement>>(v: &[F; W]) -> [F; W] {
    let mut out = [F::ZERO; W];
    for (i, o) in out.iter_mut().enumerate() {
        let mut acc = F::ZERO;
        for (j, vj) in v.iter().enumerate() {
            acc += F::from(Rp64_256::INV_MDS[i][j]) * *vj;
        }
        *o = acc;
    }
    out
}

#[inline(always)]
fn pow7<F: FieldElement>(x: F) -> F {
    let x2 = x * x;
    let x3 = x2 * x;
    let x6 = x3 * x3;
    x6 * x
}

/// One Rescue round constraint set for the state based at `base`.
fn rescue_round<F: FieldElement + From<BaseElement>>(
    cur: &[F],
    next: &[F],
    base: usize,
    ark1: &[F],
    ark2: &[F],
    flag: F,
    out: &mut [F],
) {
    let mut sbox = [F::ZERO; W];
    for i in 0..W {
        sbox[i] = pow7(cur[base + i]);
    }
    let mut step1 = mds_mul(&sbox);
    for i in 0..W {
        step1[i] += ark1[i];
    }
    let mut back = [F::ZERO; W];
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

const NUM_ASSERTIONS: usize = 27;

impl Air for SpendAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pub_inputs: PublicInputs, options: ProofOptions) -> Self {
        assert_eq!(TRACE_WIDTH, trace_info.width());
        let round = || TransitionConstraintDegree::with_cycles(7, vec![CYCLE]);
        let fold1 = || TransitionConstraintDegree::with_cycles(1, vec![CYCLE]);
        let fold2 = || TransitionConstraintDegree::with_cycles(2, vec![CYCLE]);
        // A constraint written as `s7*start + (fold - s7)*chain` mentions both a
        // period-8 and a period-256 column, but no single TERM does: the degree
        // is max(255+255, 224+255), not 255+224+255. Declaring the sum of both
        // cycles over-states it by 224, which release builds accept without
        // complaint -- only the debug-only degree assertion in
        // winter-prover/constraints/evaluation_table.rs catches it, and the cost
        // is a larger composition polynomial in every proof.
        let one1 = || TransitionConstraintDegree::with_cycles(1, vec![TRACE_LEN]);
        let one2 = || TransitionConstraintDegree::with_cycles(2, vec![TRACE_LEN]);

        let mut d = Vec::new();
        for _ in 0..3 * W {
            d.push(round()); // E, A, B round constraints
        }
        d.push(fold2()); // merkle bit boolean
        for _ in 0..DIG {
            d.push(fold2()); // merkle sibling placement
        }
        for _ in 0..DIG {
            d.push(fold1()); // merkle capacity reset
        }
        for _ in 0..DIG {
            d.push(one2()); // row 0: leaf == carried cm
        }
        d.push(one2()); // row 0: bit boolean
        for _ in 0..DIG {
            d.push(fold1()); // A capacity
        }
        for _ in 0..DIG {
            d.push(fold1()); // A rate low half
        }
        for _ in 0..DIG {
            d.push(one1()); // A rate high half (rho at row 7, digest after)
        }
        for _ in 0..DIG {
            d.push(one1()); // B capacity (fresh vs carried)
        }
        for _ in 0..2 * DIG {
            d.push(one1()); // B rate
        }
        for _ in 0..3 * DIG + 1 {
            d.push(TransitionConstraintDegree::new(1)); // carried columns
        }
        for _ in 0..DIG {
            d.push(one1()); // row 23: carried cm == commitment instance output
        }
        for _ in 0..DIG {
            d.push(one1()); // row 0: A and B absorb the same spending key
        }
        // Declared at the degree Winterfell MEASURES, not the degree the
        // expressions could reach in isolation (510 / 765). Winterfell asserts
        // declared == actual in debug builds, and the quotient C(x)/D(x) for all
        // three of these comes out constant on any satisfying trace. Declaring
        // the loose bound is sound but trips that assertion, which costs the
        // check that caught two real bugs here. The value sweep in main() is the
        // evidence: if any legal value ever produced a higher-degree quotient,
        // that value would become unprovable and the sweep would show it as a
        // legal value being rejected.
        d.push(one1()); // range: absorb a bit, then hold
        d.push(one2()); // range: that bit is boolean
        d.push(one1()); // range: recomposition equals the carried value

        SpendAir {
            context: AirContext::new(trace_info, d, NUM_ASSERTIONS, options),
            anchor: pub_inputs.anchor,
            nullifier: pub_inputs.nullifier,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let zero = Self::BaseField::ZERO;
        let one = Self::BaseField::ONE;
        let mut cols = Vec::with_capacity(P_S23 + 1);

        let mut flag = vec![one; CYCLE];
        flag[CYCLE - 1] = zero;
        cols.push(flag);
        for j in 0..W {
            let mut c = vec![zero; CYCLE];
            for r in 0..ROUNDS {
                c[r] = Rp64_256::ARK1[r][j];
            }
            cols.push(c);
        }
        for j in 0..W {
            let mut c = vec![zero; CYCLE];
            for r in 0..ROUNDS {
                c[r] = Rp64_256::ARK2[r][j];
            }
            cols.push(c);
        }
        // one-hot row selectors; length == trace length so they are true indicators
        for row in [0usize, 7, 15, 23] {
            let mut c = vec![zero; TRACE_LEN];
            c[row] = one;
            cols.push(c);
        }
        // range: active while bits are absorbed, then the single check row
        let mut ra = vec![zero; TRACE_LEN];
        for slot in ra.iter_mut().take(VALUE_BITS) {
            *slot = one;
        }
        cols.push(ra);
        let mut s63 = vec![zero; TRACE_LEN];
        s63[ACC_ROW] = one;
        cols.push(s63);
        cols
    }

    fn evaluate_transition<F: FieldElement + From<Self::BaseField>>(
        &self,
        frame: &EvaluationFrame<F>,
        periodic: &[F],
        result: &mut [F],
    ) {
        let cur = frame.current();
        let next = frame.next();
        let hash_flag = periodic[P_FLAG];
        let fold = F::ONE - hash_flag;
        let ark1 = &periodic[P_ARK1..P_ARK1 + W];
        let ark2 = &periodic[P_ARK2..P_ARK2 + W];
        let s0 = periodic[P_S0];
        let s7 = periodic[P_S7];
        let s15 = periodic[P_S15];
        let s23 = periodic[P_S23];

        let e = |c: u64| F::from(BaseElement::new(c));

        // ---- rounds ---------------------------------------------------------
        let mut buf = [F::ZERO; W];
        let mut idx = 0;
        for base in [E, A, B] {
            rescue_round(cur, next, base, ark1, ark2, hash_flag, &mut buf);
            result[idx..idx + W].copy_from_slice(&buf);
            idx += W;
        }

        // ---- Merkle fold (step 2.1, unchanged) ------------------------------
        let b = next[BIT_COL];
        result[idx] = fold * (b * b - b);
        idx += 1;
        for i in 0..DIG {
            let d = cur[E + RATE + i];
            let placed =
                (F::ONE - b) * (next[E + RATE + i] - d) + b * (next[E + RATE + DIG + i] - d);
            result[idx + i] = fold * placed;
        }
        idx += DIG;
        for (i, c) in [e(NODE_ELEMENTS), e(DOMAIN_NODE), F::ZERO, F::ZERO]
            .into_iter()
            .enumerate()
        {
            result[idx + i] = fold * (next[E + i] - c);
        }
        idx += DIG;

        // ---- BINDING 1: the Merkle leaf is the commitment we computed --------
        // Read at row 0 from the carried columns, which row 23 pins to instance
        // B's output. Without this the circuit proves membership of a commitment
        // it never opened -- exactly the hole the guardrail describes.
        let b0 = cur[BIT_COL];
        for i in 0..DIG {
            let cm = cur[CM_COL + i];
            let placed =
                (F::ONE - b0) * (cur[E + RATE + i] - cm) + b0 * (cur[E + RATE + DIG + i] - cm);
            result[idx + i] = s0 * placed;
        }
        idx += DIG;
        // row 0's direction bit is only constrained boolean by the fold rule from
        // row 8 onwards; a non-boolean b0 would let the placement above be
        // satisfied by something other than cm.
        result[idx] = s0 * (b0 * b0 - b0);
        idx += 1;

        // ---- instance A: nk (rows 0-7) then nf (rows 8-15) then idle --------
        // Both sponges have the same capacity header, so one rule covers every
        // fold row: the nf sponge and the idle chain are both fresh sponges.
        for (i, c) in [e(NF_ELEMENTS), e(DOMAIN_NULLIFIER), F::ZERO, F::ZERO]
            .into_iter()
            .enumerate()
        {
            result[idx + i] = fold * (next[A + i] - c);
        }
        idx += DIG;
        for i in 0..DIG {
            // low half of the rate always takes the digest just produced
            result[idx + i] = fold * (next[A + RATE + i] - cur[A + RATE + i]);
        }
        idx += DIG;
        for i in 0..DIG {
            // high half: rho at row 7 (that is the nullifier), digest afterwards
            let start = next[A + RATE + DIG + i] - cur[RHO_COL + i];
            let chain = next[A + RATE + DIG + i] - cur[A + RATE + i];
            result[idx + i] = s7 * start + (fold - s7) * chain;
        }
        idx += DIG;

        // ---- instance B: pk_d (rows 0-7) then cm (rows 8-23) then idle ------
        // cm is 13 elements, so its sponge spans two permutations: the second
        // block is ABSORBED onto the running state (capacity carried, rate
        // added to), which is why row 15 needs its own rule.
        let cm_hdr = [e(CM_ELEMENTS), e(DOMAIN_NOTE), F::ZERO, F::ZERO];
        for i in 0..DIG {
            let fresh = next[B + i] - cm_hdr[i];
            let carry = next[B + i] - cur[B + i];
            result[idx + i] = (fold - s15) * fresh + s15 * carry;
        }
        idx += DIG;
        for j in 0..2 * DIG {
            // start of the cm sponge: [value, pk_d(4), rho[0..3]]
            let start = match j {
                0 => next[B + RATE] - cur[VAL_COL],
                1..=4 => next[B + RATE + j] - cur[B + RATE + j - 1],
                _ => next[B + RATE + j] - cur[RHO_COL + j - 5],
            };
            // second block: [rho[3], rcm(4)] added onto the permuted rate
            let absorb = match j {
                0 => next[B + RATE] - (cur[B + RATE] + cur[RHO_COL + 3]),
                1..=4 => next[B + RATE + j] - (cur[B + RATE + j] + cur[RCM_COL + j - 1]),
                _ => next[B + RATE + j] - cur[B + RATE + j],
            };
            let chain = next[B + RATE + j] - cur[B + RATE + (j % DIG)];
            result[idx + j] = s7 * start + s15 * absorb + (fold - s7 - s15) * chain;
        }
        idx += 2 * DIG;

        // ---- carried columns ------------------------------------------------
        // rho is read by BOTH the commitment and the nullifier out of these four
        // columns. There is no second rho for an attacker to disagree with, so
        // that half of the binding is structural rather than constrained.
        for i in 0..3 * DIG + 1 {
            result[idx + i] = next[CM_COL + i] - cur[CM_COL + i];
        }
        idx += 3 * DIG + 1;

        // ---- BINDING 2: the carried cm is instance B's output ----------------
        for i in 0..DIG {
            result[idx + i] = s23 * (cur[CM_COL + i] - cur[B + RATE + i]);
        }
        idx += DIG;

        // ---- spend authority: one spending key feeds both derivations --------
        for i in 0..DIG {
            result[idx + i] = s0 * (cur[A + RATE + i] - cur[B + RATE + i]);
        }
        idx += DIG;

        // ---- RANGE: value in [0, 2^63-1] ------------------------------------
        let ra = periodic[P_RA];
        let s63 = periodic[P_S63];
        let bit = cur[BIT2_COL];
        let two = F::from(BaseElement::new(2));
        // absorb one bit per row, then hold, so the tail of the trace needs no
        // special case and ACC is still readable at row 63
        result[idx] = ra * (next[ACC_COL] - two * cur[ACC_COL] - bit)
            + (F::ONE - ra) * (next[ACC_COL] - cur[ACC_COL]);
        result[idx + 1] = ra * (bit * bit - bit);
        // 63 boolean bits can only recompose to something in [0, 2^63-1], so
        // pinning ACC to the carried value IS the range check.
        result[idx + 2] = s63 * (cur[ACC_COL] - cur[VAL_COL]);
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let z = BaseElement::ZERO;
        let mut a = Vec::with_capacity(NUM_ASSERTIONS);

        // instance A row 0: H_dom(DOMAIN_NULLIFIER_KEY, limbs(ask)) -- 4 elements,
        // so the upper half of the rate must be genuine zero padding.
        a.push(Assertion::single(A, 0, BaseElement::new(NK_ELEMENTS)));
        a.push(Assertion::single(A + 1, 0, BaseElement::new(DOMAIN_NULLIFIER_KEY)));
        a.push(Assertion::single(A + 2, 0, z));
        a.push(Assertion::single(A + 3, 0, z));
        for i in 0..DIG {
            a.push(Assertion::single(A + RATE + DIG + i, 0, z));
        }

        // instance B row 0: H_dom(DOMAIN_DIVERSIFIED_KEY, limbs(ask) ‖ [11, d0, d1]).
        a.push(Assertion::single(B, 0, BaseElement::new(PKD_ELEMENTS)));
        a.push(Assertion::single(B + 1, 0, BaseElement::new(DOMAIN_DIVERSIFIED_KEY)));
        a.push(Assertion::single(B + 2, 0, z));
        a.push(Assertion::single(B + 3, 0, z));
        // the diversifier's length element is fixed at 11 by the node's encoding
        a.push(Assertion::single(B + RATE + DIG, 0, BaseElement::new(DIVERSIFIER_LEN)));
        // 7 elements absorbed, so the eighth rate slot is padding
        a.push(Assertion::single(B + RATE + 2 * DIG - 1, 0, z));

        // instance E row 0: the first node hash
        a.push(Assertion::single(E, 0, BaseElement::new(NODE_ELEMENTS)));
        a.push(Assertion::single(E + 1, 0, BaseElement::new(DOMAIN_NODE)));
        a.push(Assertion::single(E + 2, 0, z));
        a.push(Assertion::single(E + 3, 0, z));

        // the public inputs
        for i in 0..DIG {
            a.push(Assertion::single(E + RATE + i, ANCHOR_ROW, self.anchor[i]));
        }
        for i in 0..DIG {
            a.push(Assertion::single(A + RATE + i, NF_ROW, self.nullifier[i]));
        }
        // the recomposition starts from nothing
        a.push(Assertion::single(ACC_COL, 0, z));
        a
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// ---------------------------------------------------------------------------

#[derive(Clone)]
struct Witness {
    ask: [BaseElement; DIG],
    div: [BaseElement; 3], // encode(diversifier) = [11, d0, d1]
    value: BaseElement,
    rho: [BaseElement; DIG],
    rcm: [BaseElement; DIG],
    /// The leaf the path opens. Equals the derived commitment for an honest
    /// spend; a forgery is exactly the case where it does not.
    leaf: [BaseElement; DIG],
    siblings: Vec<[BaseElement; DIG]>,
    bits: Vec<bool>,
}

/// Bit `i` of a value, as a field element. Reads the canonical integer, so a
/// value at or above 2^63 simply has no 63-bit decomposition and the gadget
/// cannot be satisfied -- which is the point.
fn value_bit(v: BaseElement, i: usize) -> BaseElement {
    BaseElement::new((v.as_int() >> i) & 1)
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

fn to_bytes(d: &[BaseElement; DIG]) -> Vec<u8> {
    d.iter().flat_map(|e| e.as_int().to_le_bytes()).collect()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("hex"))
        .collect()
}

/// encode_bytes_as_field_elements: [len] then little-endian 7-byte chunks.
fn encode_bytes(data: &[u8]) -> Vec<BaseElement> {
    let mut out = vec![BaseElement::new(data.len() as u64)];
    for chunk in data.chunks(7) {
        let mut b = [0u8; 8];
        b[..chunk.len()].copy_from_slice(chunk);
        out.push(BaseElement::new(u64::from_le_bytes(b)));
    }
    out
}

fn h_dom(domain: u64, elements: &[BaseElement]) -> [BaseElement; DIG] {
    let mut st = [BaseElement::ZERO; W];
    st[0] = BaseElement::new(elements.len() as u64);
    st[1] = BaseElement::new(domain);
    let mut i = 0;
    let mut permuted = false;
    for &el in elements {
        st[RATE + i] += el;
        i += 1;
        if i == 2 * DIG {
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

/// Fold a leaf to a root with the node's rule: node(l, r) = H_dom(2, l ‖ r),
/// no leaf hash. Independent of the AIR, so it is a real cross-check.
fn native_root(
    leaf: &[BaseElement; DIG],
    siblings: &[[BaseElement; DIG]],
    bits: &[bool],
) -> [BaseElement; DIG] {
    let mut cur = *leaf;
    for (sib, &bit) in siblings.iter().zip(bits) {
        let (l, r) = if bit { (sib, &cur) } else { (&cur, sib) };
        let mut e = l.to_vec();
        e.extend_from_slice(r);
        cur = h_dom(DOMAIN_NODE, &e);
    }
    cur
}

fn start_node(
    digest: &[BaseElement; DIG],
    sibling: &[BaseElement; DIG],
    bit: bool,
    state: &mut [BaseElement],
) {
    for k in 0..W {
        state[E + k] = BaseElement::ZERO;
    }
    state[E] = BaseElement::new(NODE_ELEMENTS);
    state[E + 1] = BaseElement::new(DOMAIN_NODE);
    let (l, r) = if bit { (sibling, digest) } else { (digest, sibling) };
    for i in 0..DIG {
        state[E + RATE + i] = l[i];
        state[E + RATE + DIG + i] = r[i];
    }
}

fn fresh_chain(state: &mut [BaseElement], base: usize, count: u64, domain: u64) {
    let d: [BaseElement; DIG] = state[base + RATE..base + RATE + DIG].try_into().unwrap();
    for k in 0..W {
        state[base + k] = BaseElement::ZERO;
    }
    state[base] = BaseElement::new(count);
    state[base + 1] = BaseElement::new(domain);
    for i in 0..DIG {
        state[base + RATE + i] = d[i];
        state[base + RATE + DIG + i] = d[i];
    }
}

fn build_trace(w: &Witness) -> TraceTable<BaseElement> {
    let mut trace = TraceTable::new(TRACE_WIDTH, TRACE_LEN);
    trace.fill(
        |state| {
            // A: nk sponge over limbs(ask)
            state[A] = BaseElement::new(NK_ELEMENTS);
            state[A + 1] = BaseElement::new(DOMAIN_NULLIFIER_KEY);
            for i in 0..DIG {
                state[A + RATE + i] = w.ask[i];
            }
            // B: pk_d sponge over limbs(ask) ‖ encode(diversifier)
            state[B] = BaseElement::new(PKD_ELEMENTS);
            state[B + 1] = BaseElement::new(DOMAIN_DIVERSIFIED_KEY);
            for i in 0..DIG {
                state[B + RATE + i] = w.ask[i];
            }
            for i in 0..3 {
                state[B + RATE + DIG + i] = w.div[i];
            }
            // E: first Merkle node
            start_node(&w.leaf, &w.siblings[0], w.bits[0], state);
            state[BIT_COL] = if w.bits[0] { BaseElement::ONE } else { BaseElement::ZERO };
            // carried witness
            for i in 0..DIG {
                state[CM_COL + i] = w.leaf[i];
                state[RHO_COL + i] = w.rho[i];
                state[RCM_COL + i] = w.rcm[i];
            }
            state[VAL_COL] = w.value;
            // range: MSB first, so row r holds bit (VALUE_BITS - 1 - r)
            state[ACC_COL] = BaseElement::ZERO;
            state[BIT2_COL] = value_bit(w.value, VALUE_BITS - 1);
        },
        |step, state| {
            // ---- range gadget, independent of the Rescue cycle ------------
            if step < VALUE_BITS {
                state[ACC_COL] = state[ACC_COL] + state[ACC_COL] + state[BIT2_COL];
                state[BIT2_COL] = if step + 1 < VALUE_BITS {
                    value_bit(w.value, VALUE_BITS - 2 - step)
                } else {
                    BaseElement::ZERO
                };
            } else {
                state[BIT2_COL] = BaseElement::ZERO;
            }

            let pos = step % CYCLE;
            if pos < ROUNDS {
                for base in [A, B, E] {
                    let mut s: [BaseElement; W] = state[base..base + W].try_into().unwrap();
                    Rp64_256::apply_round(&mut s, pos);
                    state[base..base + W].copy_from_slice(&s);
                }
                return;
            }

            // ---- Merkle: advance one level -------------------------------
            let level = step / CYCLE + 1;
            let digest: [BaseElement; DIG] =
                state[E + RATE..E + RATE + DIG].try_into().unwrap();
            let bit = w.bits[level];
            start_node(&digest, &w.siblings[level], bit, state);
            state[BIT_COL] = if bit { BaseElement::ONE } else { BaseElement::ZERO };

            // ---- instance A ----------------------------------------------
            if step == CYCLE - 1 {
                // nk is done; open the nullifier sponge over limbs(nk) ‖ limbs(rho)
                let nk: [BaseElement; DIG] =
                    state[A + RATE..A + RATE + DIG].try_into().unwrap();
                for k in 0..W {
                    state[A + k] = BaseElement::ZERO;
                }
                state[A] = BaseElement::new(NF_ELEMENTS);
                state[A + 1] = BaseElement::new(DOMAIN_NULLIFIER);
                for i in 0..DIG {
                    state[A + RATE + i] = nk[i];
                    state[A + RATE + DIG + i] = w.rho[i];
                }
            } else {
                fresh_chain(state, A, NF_ELEMENTS, DOMAIN_NULLIFIER);
            }

            // ---- instance B ----------------------------------------------
            if step == CYCLE - 1 {
                // pk_d is done; open the commitment sponge, first block
                let pkd: [BaseElement; DIG] =
                    state[B + RATE..B + RATE + DIG].try_into().unwrap();
                for k in 0..W {
                    state[B + k] = BaseElement::ZERO;
                }
                state[B] = BaseElement::new(CM_ELEMENTS);
                state[B + 1] = BaseElement::new(DOMAIN_NOTE);
                state[B + RATE] = w.value;
                for i in 0..DIG {
                    state[B + RATE + 1 + i] = pkd[i];
                }
                for i in 0..3 {
                    state[B + RATE + 5 + i] = w.rho[i];
                }
            } else if step == 2 * CYCLE - 1 {
                // second block absorbed onto the running sponge
                state[B + RATE] += w.rho[3];
                for i in 0..DIG {
                    state[B + RATE + 1 + i] += w.rcm[i];
                }
            } else {
                fresh_chain(state, B, CM_ELEMENTS, DOMAIN_NOTE);
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
    type TraceLde<F: FieldElement<BaseField = Self::BaseField>> =
        DefaultTraceLde<F, Self::HashFn, Self::VC>;
    type ConstraintCommitment<F: FieldElement<BaseField = Self::BaseField>> =
        DefaultConstraintCommitment<F, Self::HashFn, Self::VC>;
    type ConstraintEvaluator<'a, F: FieldElement<BaseField = Self::BaseField>> =
        DefaultConstraintEvaluator<'a, Self::Air, F>;

    fn get_pub_inputs(&self, trace: &Self::Trace) -> PublicInputs {
        let mut anchor = [BaseElement::ZERO; DIG];
        let mut nullifier = [BaseElement::ZERO; DIG];
        for i in 0..DIG {
            anchor[i] = trace.get(E + RATE + i, ANCHOR_ROW);
            nullifier[i] = trace.get(A + RATE + i, NF_ROW);
        }
        PublicInputs { anchor, nullifier }
    }
    fn options(&self) -> &ProofOptions {
        &self.options
    }
    fn new_trace_lde<F: FieldElement<BaseField = Self::BaseField>>(
        &self,
        ti: &TraceInfo,
        mt: &ColMatrix<Self::BaseField>,
        d: &StarkDomain<Self::BaseField>,
        po: PartitionOptions,
    ) -> (Self::TraceLde<F>, TracePolyTable<F>) {
        DefaultTraceLde::new(ti, mt, d, po)
    }
    fn build_constraint_commitment<F: FieldElement<BaseField = Self::BaseField>>(
        &self,
        cpt: CompositionPolyTrace<F>,
        n: usize,
        d: &StarkDomain<Self::BaseField>,
        po: PartitionOptions,
    ) -> (Self::ConstraintCommitment<F>, CompositionPoly<F>) {
        DefaultConstraintCommitment::new(cpt, n, d, po)
    }
    fn new_evaluator<'a, F: FieldElement<BaseField = Self::BaseField>>(
        &self,
        air: &'a Self::Air,
        aux: Option<AuxRandElements<F>>,
        cc: winterfell::ConstraintCompositionCoefficients<F>,
    ) -> Self::ConstraintEvaluator<'a, F> {
        DefaultConstraintEvaluator::new(air, aux, cc)
    }
}

fn opts(queries: usize) -> ProofOptions {
    ProofOptions::new(
        queries, 8, 0, FieldExtension::Cubic, 8, 31,
        BatchingMethod::Linear, BatchingMethod::Linear,
    )
}

fn verify_at(proof: Proof, pi: PublicInputs, bits: u32) -> bool {
    winterfell::verify::<SpendAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof,
        pi,
        &AcceptableOptions::MinConjecturedSecurity(bits),
    )
    .is_ok()
}

/// Prove and verify, reporting whether the statement survived. A rejected
/// witness may fail either by the prover refusing to build a proof (debug
/// builds validate the trace) or by the proof failing verification; both are
/// "rejected", and conflating them would hide the difference, so they are
/// reported separately.
fn accepts(w: &Witness, pi: PublicInputs) -> bool {
    let built = panic::catch_unwind(AssertUnwindSafe(|| {
        let prover = SpendProver { options: opts(43) };
        prover.prove(build_trace(w))
    }));
    match built {
        Err(_) | Ok(Err(_)) => false,
        Ok(Ok(proof)) => verify_at(proof, pi, 95),
    }
}

/// Report against an expectation, so an accepted-and-should-be case does not get
/// stamped UNSOUND and a rejected-and-should-be case does not read as a pass.
fn expect(w: &Witness, pi: PublicInputs, want_accept: bool) -> String {
    let got = accepts(w, pi);
    let verdict = if got { "accepted" } else { "rejected" };
    if got == want_accept {
        format!("{verdict:<8}  as expected")
    } else {
        format!("{verdict:<8}  *** WRONG ***")
    }
}

fn attempt(w: &Witness, pi: PublicInputs) -> &'static str {
    let built = panic::catch_unwind(AssertUnwindSafe(|| {
        let prover = SpendProver { options: opts(43) };
        prover.prove(build_trace(w))
    }));
    match built {
        Err(_) => "rejected (prover refused the trace)",
        Ok(Err(_)) => "rejected (prover errored)",
        Ok(Ok(proof)) => {
            if verify_at(proof, pi, 95) {
                "ACCEPTED -- UNSOUND"
            } else {
                "rejected (proof failed verification)"
            }
        }
    }
}

fn main() {
    println!("Step 2.4 -- value range on the spend circuit\n");

    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    let path = p.join("tests").join("vectors").join("shielded_rescue-rp64-256.json");
    let j: Value =
        serde_json::from_str(&fs::read_to_string(&path).expect("read golden")).expect("json");

    // Traversal comes from the synthetic deep path (position 0xA5A5A5A5), so both
    // branches of the sibling placement are exercised at all 32 levels. Its own
    // leaf is note 0, whose value is zero -- fine for 2.1 and 2.2, but zero is
    // the degenerate witness for the range gadget 2.4 bolts onto this circuit,
    // and carrying two different traversals across 2.3 and 2.4 would make their
    // proof sizes incomparable. So the proved witness is note 5 (realistic value,
    // non-zero diversifier) at the deep position, and the golden root is pinned
    // separately below by recomputing it natively from the path's own leaf.
    const NOTE: usize = 5;
    let note = &j["notes"][NOTE];
    let entry = &j["merkle"]["synthetic_deep_path"];

    // find the key the note was issued to, by its nullifier key
    let kd = j["key_derivation"]
        .as_array()
        .unwrap()
        .iter()
        .find(|k| k["nullifier_key"] == note["nullifier_key"])
        .expect("no key derivation entry for this note");

    let ask = limbs(&unhex(kd["spending_key"].as_str().unwrap()));
    let div_bytes = unhex(kd["diversifier"].as_str().unwrap());
    let div_v = encode_bytes(&div_bytes);
    assert_eq!(div_v.len(), 3, "diversifier encoding changed shape");
    let div: [BaseElement; 3] = div_v.try_into().unwrap();

    let value = BaseElement::new(note["value"].as_u64().unwrap());
    let rho = limbs(&unhex(note["rho"].as_str().unwrap()));
    let rcm = limbs(&unhex(note["rcm"].as_str().unwrap()));
    let cm = limbs(&unhex(note["commitment"].as_str().unwrap()));
    // the deep path's golden root, for its OWN leaf -- not the proved witness
    let deep_leaf = limbs(&unhex(entry["commitment"].as_str().unwrap()));
    let deep_root = limbs(&unhex(entry["root"].as_str().unwrap()));
    let golden_nf = limbs(&unhex(note["nullifier"].as_str().unwrap()));
    let golden_nk = limbs(&unhex(note["nullifier_key"].as_str().unwrap()));
    let golden_pkd = limbs(&unhex(note["pk_d"].as_str().unwrap()));

    let siblings: Vec<[BaseElement; DIG]> = entry["siblings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| limbs(&unhex(v.as_str().unwrap())))
        .collect();

    // The golden deep path's own position, used only to reproduce its root.
    let golden_pos = entry["position"].as_u64().unwrap() as usize;
    let golden_bits: Vec<bool> = (0..DEPTH).map(|l| (golden_pos >> l) & 1 == 1).collect();

    // The golden position is now aperiodic, so the proved witness shares it.
    // Asserted rather than assumed: a position whose direction bits repeat with
    // any period dividing 32 makes the bit column a polynomial in x^(32/period)
    // of degree below 255, which drops every constraint that multiplies by it
    // below its declared degree and disables Winterfell's debug degree check.
    for period in [1usize, 2, 4, 8, 16] {
        assert!(
            !(0..DEPTH).all(|l| golden_bits[l] == golden_bits[l % period]),
            "deep path position has period {period}, which divides 32"
        );
    }
    let position = golden_pos;
    let bits: Vec<bool> = (0..DEPTH).map(|l| (position >> l) & 1 == 1).collect();

    // Pin the traversal against the node: the deep path's own leaf must fold to
    // the published root under these 32 siblings and direction bits. This is the
    // cross-runtime check; the proved witness below reuses the same geometry.
    assert_eq!(
        native_root(&deep_leaf, &siblings, &golden_bits),
        deep_root,
        "deep path does not reproduce the node's published root"
    );
    println!(
        "deep path (position {golden_pos:#x}) reproduces the node's root : OK\n\
         proved witness at position {position:#x} (aperiodic direction bits)"
    );

    println!("
witness from the node's published vectors (note {NOTE}):");
    println!("  spending key {}", kd["spending_key"].as_str().unwrap());
    println!("  value        {}", note["value"]);
    println!("  commitment   {}", note["commitment"].as_str().unwrap());
    // NOT entry["root"]: that is the deep path's root for ITS leaf (note 0).
    // A different leaf under the same siblings gives a different anchor, and
    // printing the golden one here would look like agreement that never happened.
    println!("  anchor       {}", hex(&native_root(&cm, &siblings, &bits)));
    println!("  nullifier    {}", note["nullifier"].as_str().unwrap());

    // A range gadget is exactly the thing that a lazy witness hides. Zero makes
    // every bit zero (the bit column becomes the zero polynomial and booleanity
    // stops meaning anything), 2^63-1 makes every bit one, and a power of two
    // exercises a single bit. Refuse to measure against any of them.
    let vi = value.as_int();
    assert!(vi != 0, "value 0: every range bit would be zero");
    assert!(vi != (1u64 << 63) - 1, "value 2^63-1: every range bit would be one");
    assert!(vi & (vi - 1) != 0, "value is a power of two: one bit set");
    println!("  value is non-degenerate for a range gadget ({} bits set)", vi.count_ones());

    let w = Witness {
        ask, div, value, rho, rcm,
        leaf: cm,
        siblings: siblings.clone(),
        bits: bits.clone(),
    };
    let trace = build_trace(&w);

    // ---- every intermediate must agree with the node -----------------------
    let at = |col: usize, row: usize| -> [BaseElement; DIG] {
        let mut d = [BaseElement::ZERO; DIG];
        for i in 0..DIG {
            d[i] = trace.get(col + i, row);
        }
        d
    };
    let nk = at(A + RATE, CYCLE - 1);
    let pkd = at(B + RATE, CYCLE - 1);
    let nf = at(A + RATE, NF_ROW);
    let cm_air = at(B + RATE, CM_ROW);
    let anchor = at(E + RATE, ANCHOR_ROW);

    println!();
    for (label, got, want) in [
        ("nk         = H_dom(5, limbs(ask))", nk, golden_nk),
        ("pk_d       = H_dom(6, ask ‖ enc(d))", pkd, golden_pkd),
        ("cm         = H_dom(3, 13 elements)", cm_air, cm),
        ("nf         = H_dom(4, nk ‖ rho)", nf, golden_nf),
        ("anchor     = 32 node hashes", anchor, native_root(&cm, &siblings, &bits)),
        // ^ against the native fold, not a published root: this leaf is not the
        //   deep path's own. The published root is pinned separately, above.
    ] {
        assert_eq!(got, want, "{label} disagrees with the node\n  got {}", hex(&got));
        println!("  in-trace {label:<36} matches the node : OK");
    }
    // and independently, outside the trace
    let mut cm_elems = vec![value];
    cm_elems.extend_from_slice(&pkd);
    cm_elems.extend_from_slice(&rho);
    cm_elems.extend_from_slice(&rcm);
    assert_eq!(h_dom(DOMAIN_NOTE, &cm_elems), cm, "native H_dom disagrees on cm");
    let mut pkd_elems = ask.to_vec();
    pkd_elems.extend_from_slice(&div);
    assert_eq!(h_dom(DOMAIN_DIVERSIFIED_KEY, &pkd_elems), golden_pkd, "native pk_d");
    println!("  native H_dom agrees on cm and pk_d                       : OK");
    println!("\ntrace rows: {TRACE_LEN}  columns: {TRACE_WIDTH}\n");

    // ---- cost --------------------------------------------------------------
    println!(
        "{:<34} {:>11} {:>10} {:>10} {:>8}",
        "config", "proof bytes", "prove ms", "verify ms", "128-bit"
    );
    println!("{}", "-".repeat(78));
    let mut measured_128 = 0usize;
    for (label, queries) in [
        ("96-bit  (32q, blowup 8, cubic)", 32usize),
        ("128-bit (43q, blowup 8, cubic)", 43),
    ] {
        let prover = SpendProver { options: opts(queries) };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();
        if queries == 43 {
            measured_128 = size;
        }

        let t = Instant::now();
        for _ in 0..20 {
            assert!(
                verify_at(proof.clone(), PublicInputs { anchor, nullifier: nf }, 95),
                "honest proof rejected"
            );
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / 20.0;
        let ok128 = verify_at(proof, PublicInputs { anchor, nullifier: nf }, 128);
        println!(
            "{label:<34} {size:>11} {prove_ms:>10.1} {verify_ms:>10.3} {:>8}",
            if ok128 { "yes" } else { "no" }
        );
    }

    // ---- soundness ---------------------------------------------------------
    println!("\npublic-input soundness:");
    let prover = SpendProver { options: opts(43) };
    let proof = prover.prove(trace.clone()).unwrap();
    let mut bad_anchor = anchor;
    bad_anchor[0] += BaseElement::ONE;
    println!(
        "  wrong anchor                             : {}",
        if verify_at(proof.clone(), PublicInputs { anchor: bad_anchor, nullifier: nf }, 95) {
            "ACCEPTED -- UNSOUND"
        } else {
            "rejected"
        }
    );
    let mut bad_nf = nf;
    bad_nf[0] += BaseElement::ONE;
    println!(
        "  wrong nullifier                          : {}",
        if verify_at(proof, PublicInputs { anchor, nullifier: bad_nf }, 95) {
            "ACCEPTED -- UNSOUND"
        } else {
            "rejected"
        }
    );

    // ---- the attack the guardrail names ------------------------------------
    println!("\nbinding (the step 2.2 hole):");

    // (1) someone else's note, an invented spending key. This is precisely the
    //     guardrail's scenario: commitments are public, so the path is public too.
    let mut forged_ask = ask;
    forged_ask[0] += BaseElement::ONE;
    let thief = Witness { ask: forged_ask, ..w.clone() };
    let thief_nf = {
        // the thief reveals the nullifier their own key produces
        let nk2 = h_dom(DOMAIN_NULLIFIER_KEY, &forged_ask);
        let mut e = nk2.to_vec();
        e.extend_from_slice(&rho);
        h_dom(DOMAIN_NULLIFIER, &e)
    };
    println!(
        "  invented key over a public commitment    : {}",
        attempt(&thief, PublicInputs { anchor, nullifier: thief_nf })
    );

    // (2) the note is real and the key is real, but the value is inflated. The
    //     commitment moves, so the leaf no longer matches.
    let inflated = Witness { value: value + BaseElement::ONE, ..w.clone() };
    println!(
        "  same note, inflated value                : {}",
        attempt(&inflated, PublicInputs { anchor, nullifier: nf })
    );

    // (3) a different rho, hoping to spend the same note under a fresh
    //     nullifier and double-spend it.
    let mut rho2 = rho;
    rho2[0] += BaseElement::ONE;
    let replay = Witness { rho: rho2, ..w.clone() };
    let replay_nf = {
        let mut e = golden_nk.to_vec();
        e.extend_from_slice(&rho2);
        h_dom(DOMAIN_NULLIFIER, &e)
    };
    println!(
        "  fresh rho to re-spend the same leaf      : {}",
        attempt(&replay, PublicInputs { anchor, nullifier: replay_nf })
    );

    // (4) a note the prover genuinely owns, but which is not in the tree.
    let mut rcm2 = rcm;
    rcm2[0] += BaseElement::ONE;
    let uncommitted = Witness { rcm: rcm2, ..w.clone() };
    println!(
        "  own note, never appended to the tree     : {}",
        attempt(&uncommitted, PublicInputs { anchor, nullifier: nf })
    );

    println!(
        "\n  rho is one set of columns read by both the commitment and the\n  \
         nullifier, so \"the same rho\" is structural: there is no second rho\n  \
         to disagree with, and no constraint that could be left out."
    );

    // ---- range ------------------------------------------------------------
    // Every witness below is INTERNALLY CONSISTENT: the commitment really does
    // open to the stated value, the path really does fold to the stated anchor,
    // the nullifier really is derived from the stated key. Step 2.3 accepts all
    // of them. Only the range gadget separates them.
    println!("\nrange (each witness is self-consistent -- 2.3 accepts them all):");
    let consistent = |v: BaseElement| -> (Witness, PublicInputs) {
        let mut e = vec![v];
        e.extend_from_slice(&pkd);
        e.extend_from_slice(&rho);
        e.extend_from_slice(&rcm);
        let leaf = h_dom(DOMAIN_NOTE, &e);
        let w = Witness {
            ask, div, value: v, rho, rcm, leaf,
            siblings: siblings.clone(),
            bits: bits.clone(),
        };
        let pi = PublicInputs {
            anchor: native_root(&leaf, &siblings, &bits),
            nullifier: nf,
        };
        (w, pi)
    };

    let max_legal = BaseElement::new((1u64 << 63) - 1);
    // Doubles as the degree sweep. Under debug assertions Winterfell asserts that
    // each constraint's measured degree equals the declared one, and a mismatch
    // panics inside prove(), which surfaces here as a LEGAL value being rejected.
    // So a clean run of this table in a debug build is the evidence for the
    // degree declarations above -- across all-zero bits, all-one bits, single
    // bits, alternating bits and dense mixed bits.
    let cases: [(&str, BaseElement, bool); 10] = [
        ("value = 0            all bits zero  legal", BaseElement::ZERO, true),
        ("value = 1            one bit        legal", BaseElement::ONE, true),
        ("value = 2^62         top bit only   legal", BaseElement::new(1u64 << 62), true),
        ("value = 2^63-1       all bits one   legal", max_legal, true),
        ("value = 2^63-2       all but LSB    legal", BaseElement::new((1u64 << 63) - 2), true),
        ("value = 0x5555...    alternating    legal", BaseElement::new(0x5555_5555_5555_5555), true),
        ("value = 0xDEADBEEFCAFE              legal", BaseElement::new(0xDEAD_BEEF_CAFE), true),
        ("value = 2100000000000000            legal", value, true),
        ("value = 2^63         one over       ILLEGAL", BaseElement::new(1u64 << 63), false),
        // p-1 is the dangerous one: as a field element it behaves as -1, so the
        // balance equation in step 2.5 would read this note as owing WEPO rather
        // than holding it. Nothing outside the range check catches it.
        ("value = p-1          acts as -1     ILLEGAL", -BaseElement::ONE, false),
    ];
    let mut wrong = 0;
    for (label, v, want) in cases {
        let (wc, pi) = consistent(v);
        let r = expect(&wc, pi, want);
        if r.contains("WRONG") {
            wrong += 1;
        }
        println!("  {label:<43} : {r}");
    }
    assert_eq!(wrong, 0, "range gadget disagreed with expectation on {wrong} value(s)");

    // ---- bundle column projection -----------------------------------------
    // Measured per-piece costs from this circuit, not estimates.
    const SPEND: usize = TRACE_WIDTH; // 52: A + B + E + bit + carried + range
    const OUTPUT: usize = 20; // 12 Rescue + 5 carried (rho[3], rcm) + value + 2 range
    const BALANCE: usize = 4; // step 2.5 accumulator, not yet built
    const CAP: usize = 254; // Winterfell's trace width ceiling
    println!("\nbundle column projection (256 rows, everything concurrent):");
    println!("  per spend  {SPEND:>4}   (this circuit, measured)");
    println!("  per output {OUTPUT:>4}   (commitment only: no path, no nullifier)");
    println!("  balance    {BALANCE:>4}   (step 2.5, not yet built)");
    for (sp, out) in [(1usize, 2usize), (2, 2), (2, 4), (4, 2)] {
        let total = sp * SPEND + out * OUTPUT + BALANCE;
        println!(
            "  {sp} spend(s) + {out} outputs = {total:>4} columns  {}",
            if total <= CAP { "fits" } else { "OVER THE 254 CAP" }
        );
    }
    let max_spends = (CAP - 2 * OUTPUT - BALANCE) / SPEND;
    println!(
        "  ceiling: {max_spends} spends with 2 outputs before 254 is hit ({} columns)",
        max_spends * SPEND + 2 * OUTPUT + BALANCE
    );
    println!(
        "  beyond that, spends must go sequential: 2 paths in one column set is\n  \
         512 rows, which is the trade step 2.5 has to make."
    );
    // Size projection. phase2_scaling measures the same geometries with degree-1
    // constraints and no helper columns, so it under-reads. This circuit gives the
    // correction at the EXACT shape rather than a rule of thumb: the harness reads
    // 45,435 B at 52 x 256, and whatever this run just measured is the truth for
    // the same geometry. Computed here rather than pinned, because a hard-coded
    // factor goes stale the moment the witness or the constraint set moves -- it
    // already did once, when the traversal position changed.
    //
    // PROVISIONAL, and a calibration rather than a constant: it measures how far
    // the real constraint set (98 constraints, degree up to 7) sits above the
    // harness's degree-1 stand-in, and it will drift again at step 2.5.
    const HARNESS_AT_52X256: f64 = 45_435.0;
    let k = measured_128 as f64 / HARNESS_AT_52X256;
    println!(
        "
size projection (harness x{k:.3}, calibrated on this run: {measured_128} B at 52 x 256):"
    );
    for (label, cols, rows, harness) in [
        ("1 spend  + 2 outputs", 96usize, 256usize, 64413.0f64),
        ("2 spends + 2 outputs", 148, 256, 81660.0),
        ("4 spends + 2 outputs (at the cap)", 252, 256, 125244.0),
        ("2 spends + 2 outputs, sequential", 148, 512, 93724.0),
    ] {
        let bytes = harness * k;
        println!(
            "  {label:<34} {cols:>3} x {rows:<4} {bytes:>9.0} B   {:>4.1} tx/MB",
            1048576.0 / bytes
        );
    }
}

fn hex(d: &[BaseElement; DIG]) -> String {
    to_bytes(d).iter().map(|b| format!("{b:02x}")).collect()
}
