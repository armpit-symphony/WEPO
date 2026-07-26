//! Step 2.5 — balance, and the first complete bundle.
//!
//! Proves, for a bundle of S spends and O outputs, in ONE proof:
//!
//!   per spend    nk   = H_dom(5, limbs(ask))                      (2.3)
//!                pk_d = H_dom(6, limbs(ask) ‖ encode(d))          (2.3)
//!                cm   = H_dom(3, [v] ‖ pk_d ‖ rho ‖ rcm)          (2.3)
//!                cm is the leaf the path opens under the anchor   (2.1, 2.3)
//!                nf   = H_dom(4, limbs(nk) ‖ limbs(rho))          (2.2, 2.3)
//!                v in [0, 2^61-1]                                 (2.4)
//!   per output   cm_out = H_dom(3, [v] ‖ pk_d ‖ rho ‖ rcm)        new
//!                v in [0, 2^61-1]                                 (2.4, per rule 4)
//!   once         sum(spent) + max(vb,0) == sum(outputs) + max(-vb,0)   new
//!
//! That is the node's rule list in ShieldedVerifier's docstring, items 1-5,
//! complete. Item 5 has to be in-circuit precisely because WEPO's commitments
//! are hash-based and therefore NOT homomorphic: there is no summing of
//! commitments the way Zcash does it.
//!
//! ---------------------------------------------------------------------------
//! MAX_NOTE_VALUE IS TOO LARGE FOR A FIELD-NATIVE BALANCE CHECK
//!
//! This is the finding of the step, and it is a consensus parameter, not a
//! circuit detail.
//!
//! Balance is summed in the field, and Goldilocks is only p = 2^64 - 2^32 + 1.
//! MAX_NOTE_VALUE is 2^63-1, so TWO legal values already overflow it:
//!
//!     (2^63-1) + (2^63-1) = 2^64-2 = p + 4294967293
//!
//! Both outputs pass their own 63-bit range check. The side total reduces to
//! 4294967293, which also passes a 63-bit range check. The field equation is
//! satisfied exactly. And the bundle has minted p base units of WEPO out of a
//! shielding of about 4.3e9. A range check on the SIDE TOTAL cannot catch this,
//! because by the time the total exists the wrap has already happened and the
//! residue is small. This is demonstrated below by running the same bundle at
//! two widths, not argued.
//!
//! What actually prevents it is the relationship between the per-value width B
//! and the number of terms T on a side: if T * 2^B <= p then the integer sum can
//! never reach the modulus, so the field sum IS the integer sum and equality of
//! field sums is equality of integers.
//!
//!     B = 63  ->   1 term    (unusable: every side has at least two)
//!     B = 62  ->   3 terms
//!     B = 61  ->   7 terms   <- chosen
//!     B = 60  ->  15 terms
//!
//! B = 61 covers up to 6 spends plus value_balance, comfortably past the 4-spend
//! ceiling the 254-column cap imposes anyway. So the circuit enforces
//! VALUE_BITS = 61, and MAX_NOTE_VALUE has to come down from 2^63-1 to 2^61-1 to
//! match. That costs nothing real: TOTAL_SUPPLY is 69,000,003 WEPO, which is
//! about 6.9e15 base units, while 2^61 is 2.3e18 -- roughly 300x the entire
//! supply. The current 2^63-1 was chosen to fit a signed 64-bit Python
//! accumulator, not to fit a field.
//!
//! UNTIL shielded.py agrees, there is a gap: the node would accept a note the
//! circuit cannot spend. That is a consensus change and is deliberately NOT made
//! here.
//!
//! The side-total recomposition is kept, but it is bookkeeping rather than the
//! source of soundness: it pins each side to a genuine integer and caps total
//! bundle value. The no-wrap guarantee comes from T * 2^B <= p.
//!
//! This is also why range had to land before balance. A value of p-1 behaves as
//! -1: without 2.4 a note could read as OWING WEPO, and the balance equation
//! would happily settle against it.
//!
//! ---------------------------------------------------------------------------
//! LAYOUT. Everything runs concurrently in its own columns; the trace stays at
//! 256 rows, which the 32-level Merkle path fixes anyway.
//!
//!   per spend   52 = A(12) + B(12) + E(12) + bit(1) + carried(13) + range(2)
//!   per output  20 = C(12) + carried(6: rho[3], rcm, value) + range(2)
//!   balance      4 = two 61-bit recompositions, one per side
//!
//! The balance equation itself costs NO column: every value already lives in a
//! carried column held constant across the trace, so both sides are linear
//! combinations of cells in a single row.
//!
//!   S=1 O=2  ->  96    S=2 O=2  -> 148    S=4 O=2  -> 252    cap is 254
//!
//! An output is a commitment and nothing else -- no path, no nullifier, no key
//! derivation -- which is why it costs 20 against a spend's 52.
//!
//! STILL NOT WIRED. The proof is not yet bound to the bundle statement digest
//! (that is the verifier boundary, step 3), and register_verifier() remains
//! untouched. See the partial-circuit guardrail.

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

const W: usize = 12;
const RATE: usize = 4;
const DIG: usize = 4;
const ROUNDS: usize = 7;
const CYCLE: usize = 8;
const DEPTH: usize = 32;

const DOMAIN_NODE: u64 = 2;
const DOMAIN_NOTE: u64 = 3;
const DOMAIN_NULLIFIER: u64 = 4;
const DOMAIN_NULLIFIER_KEY: u64 = 5;
const DOMAIN_DIVERSIFIED_KEY: u64 = 6;

const NODE_ELEMENTS: u64 = 8;
const NF_ELEMENTS: u64 = 8;
const NK_ELEMENTS: u64 = 4;
const PKD_ELEMENTS: u64 = 7;
const CM_ELEMENTS: u64 = 13;
const DIVERSIFIER_LEN: u64 = 11;

const SPEND_COLS: usize = 52;
const OUT_COLS: usize = 20;
const BAL_COLS: usize = 4;
const WIDTH_CAP: usize = 254;

const TRACE_LEN: usize = DEPTH * CYCLE; // 256
const ANCHOR_ROW: usize = TRACE_LEN - 1; // 255
const NF_ROW: usize = 2 * CYCLE - 1; // 15
const CM_ROW: usize = 3 * CYCLE - 1; // 23
const OUT_CM_ROW: usize = 2 * CYCLE - 1; // 15
/// Per-value bit width the circuit enforces. See the header: this is bounded by
/// the number of terms a side can have, NOT by MAX_NOTE_VALUE. Parameterised so
/// the wrap can be demonstrated at 63 and refuted at 61.
const VALUE_BITS: usize = 61;
/// T * 2^VALUE_BITS <= p must hold, where T is the largest number of terms on
/// either side of the balance equation (spends + 1, or outputs + 1).
const MAX_TERMS: usize = 7;

const P_FLAG: usize = 0;
const P_ARK1: usize = 1;
const P_ARK2: usize = 1 + W;
const P_S0: usize = 1 + 2 * W;
const P_S7: usize = P_S0 + 1;
const P_S15: usize = P_S0 + 2;
const P_S23: usize = P_S0 + 3;
const P_RA: usize = P_S0 + 4;
const P_S63: usize = P_S0 + 5;

// --- layout -----------------------------------------------------------------

#[derive(Clone, Copy)]
struct SpendCols {
    a: usize,
    b: usize,
    e: usize,
    bit: usize,
    cm: usize,
    rho: usize,
    rcm: usize,
    val: usize,
    rbit: usize,
    racc: usize,
}

#[derive(Clone, Copy)]
struct OutCols {
    c: usize,
    rho3: usize,
    rcm: usize,
    val: usize,
    rbit: usize,
    racc: usize,
}

#[derive(Clone, Copy)]
struct BalCols {
    in_bit: usize,
    in_acc: usize,
    out_bit: usize,
    out_acc: usize,
}

#[derive(Clone, Copy)]
struct Layout {
    spends: usize,
    outputs: usize,
}

impl Layout {
    fn width(&self) -> usize {
        self.spends * SPEND_COLS + self.outputs * OUT_COLS + BAL_COLS
    }
    fn spend(&self, i: usize) -> SpendCols {
        let b = i * SPEND_COLS;
        SpendCols {
            a: b,
            b: b + 12,
            e: b + 24,
            bit: b + 36,
            cm: b + 37,
            rho: b + 41,
            rcm: b + 45,
            val: b + 49,
            rbit: b + 50,
            racc: b + 51,
        }
    }
    fn output(&self, j: usize) -> OutCols {
        let b = self.spends * SPEND_COLS + j * OUT_COLS;
        OutCols {
            c: b,
            rho3: b + 12,
            rcm: b + 13,
            val: b + 17,
            rbit: b + 18,
            racc: b + 19,
        }
    }
    fn bal(&self) -> BalCols {
        let b = self.spends * SPEND_COLS + self.outputs * OUT_COLS;
        BalCols { in_bit: b, in_acc: b + 1, out_bit: b + 2, out_acc: b + 3 }
    }
    fn constraints(&self) -> usize {
        self.spends * 98 + self.outputs * 34 + 7
    }
    fn assertions(&self) -> usize {
        self.spends * 27 + self.outputs * 9 + 2
    }
}

// --- Rescue algebra ---------------------------------------------------------

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

fn node(l: &[BaseElement; DIG], r: &[BaseElement; DIG]) -> [BaseElement; DIG] {
    let mut e = l.to_vec();
    e.extend_from_slice(r);
    h_dom(DOMAIN_NODE, &e)
}

// --- public inputs ----------------------------------------------------------

pub struct PublicInputs {
    spends: usize,
    outputs: usize,
    value_bits: usize,
    anchor: [BaseElement; DIG],
    nullifiers: Vec<[BaseElement; DIG]>,
    commitments: Vec<[BaseElement; DIG]>,
    vb_pos: BaseElement,
    vb_neg: BaseElement,
}

impl PublicInputs {
    fn layout(&self) -> Layout {
        Layout { spends: self.spends, outputs: self.outputs }
    }
}

impl ToElements<BaseElement> for PublicInputs {
    fn to_elements(&self) -> Vec<BaseElement> {
        let mut v = vec![
            BaseElement::new(self.spends as u64),
            BaseElement::new(self.outputs as u64),
            BaseElement::new(self.value_bits as u64),
        ];
        v.extend_from_slice(&self.anchor);
        for n in &self.nullifiers {
            v.extend_from_slice(n);
        }
        for c in &self.commitments {
            v.extend_from_slice(c);
        }
        v.push(self.vb_pos);
        v.push(self.vb_neg);
        v
    }
}

pub struct BundleAir {
    context: AirContext<BaseElement>,
    layout: Layout,
    value_bits: usize,
    anchor: [BaseElement; DIG],
    nullifiers: Vec<[BaseElement; DIG]>,
    commitments: Vec<[BaseElement; DIG]>,
    vb_pos: BaseElement,
    vb_neg: BaseElement,
}

impl Air for BundleAir {
    type BaseField = BaseElement;
    type PublicInputs = PublicInputs;

    fn new(trace_info: TraceInfo, pi: PublicInputs, options: ProofOptions) -> Self {
        let layout = pi.layout();
        assert_eq!(layout.width(), trace_info.width(), "trace width vs layout");

        let round = || TransitionConstraintDegree::with_cycles(7, vec![CYCLE]);
        let fold1 = || TransitionConstraintDegree::with_cycles(1, vec![CYCLE]);
        let fold2 = || TransitionConstraintDegree::with_cycles(2, vec![CYCLE]);
        // Degrees are derived from the algebra, not from what a satisfying trace
        // happens to measure. Winterfell's debug assertion interpolates C(x)/D(x)
        // on a trace where the constraint is zero everywhere, so it reports that
        // trace's quotient rather than the bound -- and the bound exists for the
        // INVALID traces it never sees. Over-declaring costs a larger composition
        // polynomial; under-declaring is a soundness hole.
        let one1 = || TransitionConstraintDegree::with_cycles(1, vec![TRACE_LEN]);
        let one2 = || TransitionConstraintDegree::with_cycles(2, vec![TRACE_LEN]);
        let plain = || TransitionConstraintDegree::new(1);

        let mut d = Vec::with_capacity(layout.constraints());
        for _ in 0..layout.spends {
            for _ in 0..3 * W {
                d.push(round());
            }
            d.push(fold2()); // merkle bit boolean
            for _ in 0..DIG {
                d.push(fold2()); // sibling placement
            }
            for _ in 0..DIG {
                d.push(fold1()); // merkle capacity
            }
            for _ in 0..DIG {
                d.push(one2()); // row 0: leaf == carried cm
            }
            d.push(one2()); // row 0: bit boolean
            for _ in 0..DIG {
                d.push(fold1()); // A capacity
            }
            for _ in 0..DIG {
                d.push(fold1()); // A rate low
            }
            for _ in 0..DIG {
                d.push(one1()); // A rate high
            }
            for _ in 0..DIG {
                d.push(one1()); // B capacity
            }
            for _ in 0..2 * DIG {
                d.push(one1()); // B rate
            }
            for _ in 0..3 * DIG + 1 {
                d.push(plain()); // carried
            }
            for _ in 0..DIG {
                d.push(one1()); // row 23: carried cm == B output
            }
            for _ in 0..DIG {
                d.push(one1()); // row 0: one spending key
            }
            d.push(one1()); // range: absorb then hold
            d.push(one2()); // range: bit boolean
            d.push(one1()); // range: ACC == value
        }
        for _ in 0..layout.outputs {
            for _ in 0..W {
                d.push(round());
            }
            for _ in 0..DIG {
                d.push(one1()); // capacity: carry at row 7, fresh after
            }
            for _ in 0..2 * DIG {
                d.push(one1()); // rate: absorb block 2 at row 7, chain after
            }
            for _ in 0..6 {
                d.push(plain()); // carried rho[3], rcm, value
            }
            d.push(one1()); // row 0: rate[0] == carried value
            d.push(one1()); // range: absorb then hold
            d.push(one2()); // range: bit boolean
            d.push(one1()); // range: ACC == value
        }
        for _ in 0..2 {
            d.push(one1()); // side total: absorb then hold
            d.push(one2()); // side total: bit boolean
            d.push(one1()); // side total: ACC == that side's sum
        }
        d.push(one1()); // the balance equation itself
        assert_eq!(d.len(), layout.constraints(), "degree count vs layout");

        BundleAir {
            context: AirContext::new(trace_info, d, layout.assertions(), options),
            layout,
            value_bits: pi.value_bits,
            anchor: pi.anchor,
            nullifiers: pi.nullifiers,
            commitments: pi.commitments,
            vb_pos: pi.vb_pos,
            vb_neg: pi.vb_neg,
        }
    }

    fn get_periodic_column_values(&self) -> Vec<Vec<Self::BaseField>> {
        let zero = Self::BaseField::ZERO;
        let one = Self::BaseField::ONE;
        let mut cols = Vec::with_capacity(P_S63 + 1);
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
        for row in [0usize, 7, 15, 23] {
            let mut c = vec![zero; TRACE_LEN];
            c[row] = one;
            cols.push(c);
        }
        let mut ra = vec![zero; TRACE_LEN];
        for slot in ra.iter_mut().take(self.value_bits) {
            *slot = one;
        }
        cols.push(ra);
        let mut s_acc = vec![zero; TRACE_LEN];
        s_acc[self.value_bits] = one;
        cols.push(s_acc);
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
        let ra = periodic[P_RA];
        let s63 = periodic[P_S63];
        let two = F::from(BaseElement::new(2));
        let e = |c: u64| F::from(BaseElement::new(c));

        let mut idx = 0;
        let mut buf = [F::ZERO; W];

        // ================= spends =============================================
        for i in 0..self.layout.spends {
            let s = self.layout.spend(i);
            for base in [s.e, s.a, s.b] {
                rescue_round(cur, next, base, ark1, ark2, hash_flag, &mut buf);
                result[idx..idx + W].copy_from_slice(&buf);
                idx += W;
            }

            // Merkle fold
            let b = next[s.bit];
            result[idx] = fold * (b * b - b);
            idx += 1;
            for k in 0..DIG {
                let d = cur[s.e + RATE + k];
                let placed =
                    (F::ONE - b) * (next[s.e + RATE + k] - d) + b * (next[s.e + RATE + DIG + k] - d);
                result[idx + k] = fold * placed;
            }
            idx += DIG;
            for (k, c) in [e(NODE_ELEMENTS), e(DOMAIN_NODE), F::ZERO, F::ZERO]
                .into_iter()
                .enumerate()
            {
                result[idx + k] = fold * (next[s.e + k] - c);
            }
            idx += DIG;

            // leaf == carried cm, at row 0
            let b0 = cur[s.bit];
            for k in 0..DIG {
                let cm = cur[s.cm + k];
                let placed = (F::ONE - b0) * (cur[s.e + RATE + k] - cm)
                    + b0 * (cur[s.e + RATE + DIG + k] - cm);
                result[idx + k] = s0 * placed;
            }
            idx += DIG;
            result[idx] = s0 * (b0 * b0 - b0);
            idx += 1;

            // instance A: nk then nf then idle
            for (k, c) in [e(NF_ELEMENTS), e(DOMAIN_NULLIFIER), F::ZERO, F::ZERO]
                .into_iter()
                .enumerate()
            {
                result[idx + k] = fold * (next[s.a + k] - c);
            }
            idx += DIG;
            for k in 0..DIG {
                result[idx + k] = fold * (next[s.a + RATE + k] - cur[s.a + RATE + k]);
            }
            idx += DIG;
            for k in 0..DIG {
                let start = next[s.a + RATE + DIG + k] - cur[s.rho + k];
                let chain = next[s.a + RATE + DIG + k] - cur[s.a + RATE + k];
                result[idx + k] = s7 * start + (fold - s7) * chain;
            }
            idx += DIG;

            // instance B: pk_d then cm (two blocks) then idle
            let hdr = [e(CM_ELEMENTS), e(DOMAIN_NOTE), F::ZERO, F::ZERO];
            for k in 0..DIG {
                let fresh = next[s.b + k] - hdr[k];
                let carry = next[s.b + k] - cur[s.b + k];
                result[idx + k] = (fold - s15) * fresh + s15 * carry;
            }
            idx += DIG;
            for j in 0..2 * DIG {
                let start = match j {
                    0 => next[s.b + RATE] - cur[s.val],
                    1..=4 => next[s.b + RATE + j] - cur[s.b + RATE + j - 1],
                    _ => next[s.b + RATE + j] - cur[s.rho + j - 5],
                };
                let absorb = match j {
                    0 => next[s.b + RATE] - (cur[s.b + RATE] + cur[s.rho + 3]),
                    1..=4 => next[s.b + RATE + j] - (cur[s.b + RATE + j] + cur[s.rcm + j - 1]),
                    _ => next[s.b + RATE + j] - cur[s.b + RATE + j],
                };
                let chain = next[s.b + RATE + j] - cur[s.b + RATE + (j % DIG)];
                result[idx + j] = s7 * start + s15 * absorb + (fold - s7 - s15) * chain;
            }
            idx += 2 * DIG;

            // carried: cm, rho, rcm, value
            for k in 0..3 * DIG + 1 {
                result[idx + k] = next[s.cm + k] - cur[s.cm + k];
            }
            idx += 3 * DIG + 1;

            for k in 0..DIG {
                result[idx + k] = s23 * (cur[s.cm + k] - cur[s.b + RATE + k]);
            }
            idx += DIG;
            for k in 0..DIG {
                result[idx + k] = s0 * (cur[s.a + RATE + k] - cur[s.b + RATE + k]);
            }
            idx += DIG;

            // range on the spend's value
            let bit = cur[s.rbit];
            result[idx] = ra * (next[s.racc] - two * cur[s.racc] - bit)
                + (F::ONE - ra) * (next[s.racc] - cur[s.racc]);
            result[idx + 1] = ra * (bit * bit - bit);
            result[idx + 2] = s63 * (cur[s.racc] - cur[s.val]);
            idx += 3;
        }

        // ================= outputs ============================================
        // An output is a commitment and nothing else. Its sponge opens at row 0
        // (there is no pk_d derivation first -- the sender does not hold the
        // recipient's key), absorbs its second block at row 7, and its digest at
        // row 15 is the public output commitment.
        for j in 0..self.layout.outputs {
            let o = self.layout.output(j);
            rescue_round(cur, next, o.c, ark1, ark2, hash_flag, &mut buf);
            result[idx..idx + W].copy_from_slice(&buf);
            idx += W;

            let hdr = [e(CM_ELEMENTS), e(DOMAIN_NOTE), F::ZERO, F::ZERO];
            for k in 0..DIG {
                let carry = next[o.c + k] - cur[o.c + k];
                let fresh = next[o.c + k] - hdr[k];
                result[idx + k] = s7 * carry + (fold - s7) * fresh;
            }
            idx += DIG;
            for k in 0..2 * DIG {
                let absorb = match k {
                    0 => next[o.c + RATE] - (cur[o.c + RATE] + cur[o.rho3]),
                    1..=4 => next[o.c + RATE + k] - (cur[o.c + RATE + k] + cur[o.rcm + k - 1]),
                    _ => next[o.c + RATE + k] - cur[o.c + RATE + k],
                };
                let chain = next[o.c + RATE + k] - cur[o.c + RATE + (k % DIG)];
                result[idx + k] = s7 * absorb + (fold - s7) * chain;
            }
            idx += 2 * DIG;

            for k in 0..6 {
                result[idx + k] = next[o.rho3 + k] - cur[o.rho3 + k];
            }
            idx += 6;
            // the value absorbed into the commitment is the value that is summed
            result[idx] = s0 * (cur[o.c + RATE] - cur[o.val]);
            idx += 1;

            let bit = cur[o.rbit];
            result[idx] = ra * (next[o.racc] - two * cur[o.racc] - bit)
                + (F::ONE - ra) * (next[o.racc] - cur[o.racc]);
            result[idx + 1] = ra * (bit * bit - bit);
            result[idx + 2] = s63 * (cur[o.racc] - cur[o.val]);
            idx += 3;
        }

        // ================= balance ============================================
        let bal = self.layout.bal();
        let mut lhs = F::from(self.vb_pos);
        for i in 0..self.layout.spends {
            lhs += cur[self.layout.spend(i).val];
        }
        let mut rhs = F::from(self.vb_neg);
        for j in 0..self.layout.outputs {
            rhs += cur[self.layout.output(j).val];
        }

        for (bit_col, acc_col, total) in
            [(bal.in_bit, bal.in_acc, lhs), (bal.out_bit, bal.out_acc, rhs)]
        {
            let bit = cur[bit_col];
            result[idx] = ra * (next[acc_col] - two * cur[acc_col] - bit)
                + (F::ONE - ra) * (next[acc_col] - cur[acc_col]);
            result[idx + 1] = ra * (bit * bit - bit);
            // Pinning each SIDE TOTAL to a 63-bit recomposition is what stops the
            // field wrapping: p is only ~2^64, and one spend plus vb can already
            // exceed it.
            result[idx + 2] = s63 * (cur[acc_col] - total);
            idx += 3;
        }

        result[idx] = s0 * (lhs - rhs);
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let z = BaseElement::ZERO;
        let mut a = Vec::with_capacity(self.layout.assertions());
        for i in 0..self.layout.spends {
            let s = self.layout.spend(i);
            a.push(Assertion::single(s.a, 0, BaseElement::new(NK_ELEMENTS)));
            a.push(Assertion::single(s.a + 1, 0, BaseElement::new(DOMAIN_NULLIFIER_KEY)));
            a.push(Assertion::single(s.a + 2, 0, z));
            a.push(Assertion::single(s.a + 3, 0, z));
            for k in 0..DIG {
                a.push(Assertion::single(s.a + RATE + DIG + k, 0, z));
            }
            a.push(Assertion::single(s.b, 0, BaseElement::new(PKD_ELEMENTS)));
            a.push(Assertion::single(s.b + 1, 0, BaseElement::new(DOMAIN_DIVERSIFIED_KEY)));
            a.push(Assertion::single(s.b + 2, 0, z));
            a.push(Assertion::single(s.b + 3, 0, z));
            a.push(Assertion::single(s.b + RATE + DIG, 0, BaseElement::new(DIVERSIFIER_LEN)));
            a.push(Assertion::single(s.b + RATE + 2 * DIG - 1, 0, z));
            a.push(Assertion::single(s.e, 0, BaseElement::new(NODE_ELEMENTS)));
            a.push(Assertion::single(s.e + 1, 0, BaseElement::new(DOMAIN_NODE)));
            a.push(Assertion::single(s.e + 2, 0, z));
            a.push(Assertion::single(s.e + 3, 0, z));
            for k in 0..DIG {
                a.push(Assertion::single(s.e + RATE + k, ANCHOR_ROW, self.anchor[k]));
            }
            for k in 0..DIG {
                a.push(Assertion::single(s.a + RATE + k, NF_ROW, self.nullifiers[i][k]));
            }
            a.push(Assertion::single(s.racc, 0, z));
        }
        for j in 0..self.layout.outputs {
            let o = self.layout.output(j);
            a.push(Assertion::single(o.c, 0, BaseElement::new(CM_ELEMENTS)));
            a.push(Assertion::single(o.c + 1, 0, BaseElement::new(DOMAIN_NOTE)));
            a.push(Assertion::single(o.c + 2, 0, z));
            a.push(Assertion::single(o.c + 3, 0, z));
            for k in 0..DIG {
                a.push(Assertion::single(o.c + RATE + k, OUT_CM_ROW, self.commitments[j][k]));
            }
            a.push(Assertion::single(o.racc, 0, z));
        }
        let bal = self.layout.bal();
        a.push(Assertion::single(bal.in_acc, 0, z));
        a.push(Assertion::single(bal.out_acc, 0, z));
        a
    }

    fn context(&self) -> &AirContext<Self::BaseField> {
        &self.context
    }
}

// --- witness ----------------------------------------------------------------

#[derive(Clone)]
struct SpendW {
    ask: [BaseElement; DIG],
    div: [BaseElement; 3],
    value: BaseElement,
    rho: [BaseElement; DIG],
    rcm: [BaseElement; DIG],
    leaf: [BaseElement; DIG],
    siblings: Vec<[BaseElement; DIG]>,
    bits: Vec<bool>,
}

#[derive(Clone)]
struct OutW {
    value: BaseElement,
    pkd: [BaseElement; DIG],
    rho: [BaseElement; DIG],
    rcm: [BaseElement; DIG],
}

impl OutW {
    fn commitment(&self) -> [BaseElement; DIG] {
        let mut e = vec![self.value];
        e.extend_from_slice(&self.pkd);
        e.extend_from_slice(&self.rho);
        e.extend_from_slice(&self.rcm);
        h_dom(DOMAIN_NOTE, &e)
    }
}

#[derive(Clone)]
struct BundleW {
    spends: Vec<SpendW>,
    outputs: Vec<OutW>,
    vb_pos: BaseElement,
    vb_neg: BaseElement,
    value_bits: usize,
}

impl BundleW {
    fn layout(&self) -> Layout {
        Layout { spends: self.spends.len(), outputs: self.outputs.len() }
    }
}

fn value_bit(v: BaseElement, i: usize) -> BaseElement {
    BaseElement::new((v.as_int() >> i) & 1)
}

/// The no-wrap condition, checked rather than trusted: with T terms of at most
/// 2^B - 1 each, the integer sum stays below p, so the field sum is the integer
/// sum. If this ever fails, balance is checkable only modulo p and a bundle can
/// mint exactly p.
fn assert_no_wrap(value_bits: usize, terms: usize) {
    let p = BaseElement::MODULUS as u128;
    let bound = (terms as u128) << value_bits;
    assert!(
        bound <= p,
        "{terms} terms of {value_bits} bits can reach {bound} >= p ({p}): \
         the balance sum can wrap and the bundle could mint p"
    );
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

fn hex(d: &[BaseElement; DIG]) -> String {
    to_bytes(d).iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("hex"))
        .collect()
}

fn encode_bytes(data: &[u8]) -> Vec<BaseElement> {
    let mut out = vec![BaseElement::new(data.len() as u64)];
    for chunk in data.chunks(7) {
        let mut b = [0u8; 8];
        b[..chunk.len()].copy_from_slice(chunk);
        out.push(BaseElement::new(u64::from_le_bytes(b)));
    }
    out
}

fn native_root(
    leaf: &[BaseElement; DIG],
    siblings: &[[BaseElement; DIG]],
    bits: &[bool],
) -> [BaseElement; DIG] {
    let mut cur = *leaf;
    for (sib, &bit) in siblings.iter().zip(bits) {
        cur = if bit { node(sib, &cur) } else { node(&cur, sib) };
    }
    cur
}

/// Paths for `leaves.len()` adjacent leaves sharing ONE anchor.
///
/// A bundle's spends must all open under the same anchor, so reusing one
/// synthetic path for every spend would be a fiction: two different leaves
/// cannot sit at the same position. Instead the leaves occupy an aligned run at
/// `base`, their subtree is built for real, and the empty ladder carries it the
/// rest of the way to depth 32.
fn adjacent_paths(
    base: usize,
    leaves: &[[BaseElement; DIG]],
    empty: &[[BaseElement; DIG]],
) -> ([BaseElement; DIG], Vec<(Vec<[BaseElement; DIG]>, Vec<bool>)>) {
    let n = leaves.len();
    assert!(n.is_power_of_two(), "leaf run must be a power of two");
    assert_eq!(base % n, 0, "leaf run must be aligned");
    let k = n.trailing_zeros() as usize;

    // build the k lowest levels for real
    let mut levels: Vec<Vec<[BaseElement; DIG]>> = vec![leaves.to_vec()];
    for _ in 0..k {
        let prev = levels.last().unwrap();
        let mut up = Vec::with_capacity(prev.len() / 2);
        for pair in prev.chunks(2) {
            up.push(node(&pair[0], &pair[1]));
        }
        levels.push(up);
    }

    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let pos = base + i;
        let bits: Vec<bool> = (0..DEPTH).map(|l| (pos >> l) & 1 == 1).collect();
        let mut sibs = Vec::with_capacity(DEPTH);
        for (l, item) in levels.iter().enumerate().take(k) {
            sibs.push(item[(i >> l) ^ 1]);
        }
        for l in k..DEPTH {
            sibs.push(empty[l]);
        }
        out.push((sibs, bits));
    }
    let root = native_root(&leaves[0], &out[0].0, &out[0].1);
    (root, out)
}

// --- trace ------------------------------------------------------------------

fn start_node(
    e: usize,
    digest: &[BaseElement; DIG],
    sibling: &[BaseElement; DIG],
    bit: bool,
    state: &mut [BaseElement],
) {
    for k in 0..W {
        state[e + k] = BaseElement::ZERO;
    }
    state[e] = BaseElement::new(NODE_ELEMENTS);
    state[e + 1] = BaseElement::new(DOMAIN_NODE);
    let (l, r) = if bit { (sibling, digest) } else { (digest, sibling) };
    for i in 0..DIG {
        state[e + RATE + i] = l[i];
        state[e + RATE + DIG + i] = r[i];
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

fn step_range(
    state: &mut [BaseElement],
    bit_col: usize,
    acc_col: usize,
    v: BaseElement,
    step: usize,
    value_bits: usize,
) {
    if step < value_bits {
        state[acc_col] = state[acc_col] + state[acc_col] + state[bit_col];
        state[bit_col] = if step + 1 < value_bits {
            value_bit(v, value_bits - 2 - step)
        } else {
            BaseElement::ZERO
        };
    } else {
        state[bit_col] = BaseElement::ZERO;
    }
}

fn build_trace(w: &BundleW) -> TraceTable<BaseElement> {
    let lay = w.layout();
    let mut lhs = w.vb_pos;
    for s in &w.spends {
        lhs += s.value;
    }
    let mut rhs = w.vb_neg;
    for o in &w.outputs {
        rhs += o.value;
    }

    let mut trace = TraceTable::new(lay.width(), TRACE_LEN);
    trace.fill(
        |state| {
            for (i, sw) in w.spends.iter().enumerate() {
                let s = lay.spend(i);
                state[s.a] = BaseElement::new(NK_ELEMENTS);
                state[s.a + 1] = BaseElement::new(DOMAIN_NULLIFIER_KEY);
                for k in 0..DIG {
                    state[s.a + RATE + k] = sw.ask[k];
                }
                state[s.b] = BaseElement::new(PKD_ELEMENTS);
                state[s.b + 1] = BaseElement::new(DOMAIN_DIVERSIFIED_KEY);
                for k in 0..DIG {
                    state[s.b + RATE + k] = sw.ask[k];
                }
                for k in 0..3 {
                    state[s.b + RATE + DIG + k] = sw.div[k];
                }
                start_node(s.e, &sw.leaf, &sw.siblings[0], sw.bits[0], state);
                state[s.bit] = if sw.bits[0] { BaseElement::ONE } else { BaseElement::ZERO };
                for k in 0..DIG {
                    state[s.cm + k] = sw.leaf[k];
                    state[s.rho + k] = sw.rho[k];
                    state[s.rcm + k] = sw.rcm[k];
                }
                state[s.val] = sw.value;
                state[s.racc] = BaseElement::ZERO;
                state[s.rbit] = value_bit(sw.value, w.value_bits - 1);
            }
            for (j, ow) in w.outputs.iter().enumerate() {
                let o = lay.output(j);
                state[o.c] = BaseElement::new(CM_ELEMENTS);
                state[o.c + 1] = BaseElement::new(DOMAIN_NOTE);
                state[o.c + RATE] = ow.value;
                for k in 0..DIG {
                    state[o.c + RATE + 1 + k] = ow.pkd[k];
                }
                for k in 0..3 {
                    state[o.c + RATE + 5 + k] = ow.rho[k];
                }
                state[o.rho3] = ow.rho[3];
                for k in 0..DIG {
                    state[o.rcm + k] = ow.rcm[k];
                }
                state[o.val] = ow.value;
                state[o.racc] = BaseElement::ZERO;
                state[o.rbit] = value_bit(ow.value, w.value_bits - 1);
            }
            let bal = lay.bal();
            state[bal.in_acc] = BaseElement::ZERO;
            state[bal.in_bit] = value_bit(lhs, w.value_bits - 1);
            state[bal.out_acc] = BaseElement::ZERO;
            state[bal.out_bit] = value_bit(rhs, w.value_bits - 1);
        },
        |step, state| {
            // range gadgets run on their own clock, independent of the cycle
            for (i, sw) in w.spends.iter().enumerate() {
                let s = lay.spend(i);
                step_range(state, s.rbit, s.racc, sw.value, step, w.value_bits);
            }
            for (j, ow) in w.outputs.iter().enumerate() {
                let o = lay.output(j);
                step_range(state, o.rbit, o.racc, ow.value, step, w.value_bits);
            }
            let bal = lay.bal();
            step_range(state, bal.in_bit, bal.in_acc, lhs, step, w.value_bits);
            step_range(state, bal.out_bit, bal.out_acc, rhs, step, w.value_bits);

            let pos = step % CYCLE;
            if pos < ROUNDS {
                for i in 0..lay.spends {
                    let s = lay.spend(i);
                    for base in [s.a, s.b, s.e] {
                        let mut st: [BaseElement; W] = state[base..base + W].try_into().unwrap();
                        Rp64_256::apply_round(&mut st, pos);
                        state[base..base + W].copy_from_slice(&st);
                    }
                }
                for j in 0..lay.outputs {
                    let o = lay.output(j);
                    let mut st: [BaseElement; W] = state[o.c..o.c + W].try_into().unwrap();
                    Rp64_256::apply_round(&mut st, pos);
                    state[o.c..o.c + W].copy_from_slice(&st);
                }
                return;
            }

            let level = step / CYCLE + 1;
            for (i, sw) in w.spends.iter().enumerate() {
                let s = lay.spend(i);
                let digest: [BaseElement; DIG] =
                    state[s.e + RATE..s.e + RATE + DIG].try_into().unwrap();
                let bit = sw.bits[level];
                start_node(s.e, &digest, &sw.siblings[level], bit, state);
                state[s.bit] = if bit { BaseElement::ONE } else { BaseElement::ZERO };

                if step == CYCLE - 1 {
                    let nk: [BaseElement; DIG] =
                        state[s.a + RATE..s.a + RATE + DIG].try_into().unwrap();
                    for k in 0..W {
                        state[s.a + k] = BaseElement::ZERO;
                    }
                    state[s.a] = BaseElement::new(NF_ELEMENTS);
                    state[s.a + 1] = BaseElement::new(DOMAIN_NULLIFIER);
                    for k in 0..DIG {
                        state[s.a + RATE + k] = nk[k];
                        state[s.a + RATE + DIG + k] = sw.rho[k];
                    }
                    let pkd: [BaseElement; DIG] =
                        state[s.b + RATE..s.b + RATE + DIG].try_into().unwrap();
                    for k in 0..W {
                        state[s.b + k] = BaseElement::ZERO;
                    }
                    state[s.b] = BaseElement::new(CM_ELEMENTS);
                    state[s.b + 1] = BaseElement::new(DOMAIN_NOTE);
                    state[s.b + RATE] = sw.value;
                    for k in 0..DIG {
                        state[s.b + RATE + 1 + k] = pkd[k];
                    }
                    for k in 0..3 {
                        state[s.b + RATE + 5 + k] = sw.rho[k];
                    }
                } else {
                    fresh_chain(state, s.a, NF_ELEMENTS, DOMAIN_NULLIFIER);
                    if step == 2 * CYCLE - 1 {
                        state[s.b + RATE] += sw.rho[3];
                        for k in 0..DIG {
                            state[s.b + RATE + 1 + k] += sw.rcm[k];
                        }
                    } else {
                        fresh_chain(state, s.b, CM_ELEMENTS, DOMAIN_NOTE);
                    }
                }
            }

            for (j, ow) in w.outputs.iter().enumerate() {
                let o = lay.output(j);
                if step == CYCLE - 1 {
                    state[o.c + RATE] += ow.rho[3];
                    for k in 0..DIG {
                        state[o.c + RATE + 1 + k] += ow.rcm[k];
                    }
                } else {
                    fresh_chain(state, o.c, CM_ELEMENTS, DOMAIN_NOTE);
                }
            }
        },
    );
    trace
}

// --- prover -----------------------------------------------------------------

struct BundleProver {
    options: ProofOptions,
    pi: PublicInputsTemplate,
}

#[derive(Clone)]
struct PublicInputsTemplate {
    spends: usize,
    outputs: usize,
    value_bits: usize,
    anchor: [BaseElement; DIG],
    nullifiers: Vec<[BaseElement; DIG]>,
    commitments: Vec<[BaseElement; DIG]>,
    vb_pos: BaseElement,
    vb_neg: BaseElement,
}

impl PublicInputsTemplate {
    fn build(&self) -> PublicInputs {
        PublicInputs {
            spends: self.spends,
            outputs: self.outputs,
            value_bits: self.value_bits,
            anchor: self.anchor,
            nullifiers: self.nullifiers.clone(),
            commitments: self.commitments.clone(),
            vb_pos: self.vb_pos,
            vb_neg: self.vb_neg,
        }
    }
}

impl Prover for BundleProver {
    type BaseField = BaseElement;
    type Air = BundleAir;
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

    fn get_pub_inputs(&self, _trace: &Self::Trace) -> PublicInputs {
        self.pi.build()
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
    winterfell::verify::<BundleAir, Blake3, DefaultRandomCoin<Blake3>, MerkleTree<Blake3>>(
        proof, pi, &AcceptableOptions::MinConjecturedSecurity(bits),
    )
    .is_ok()
}

fn accepts(w: &BundleW, t: &PublicInputsTemplate) -> bool {
    let built = panic::catch_unwind(AssertUnwindSafe(|| {
        let prover = BundleProver { options: opts(43), pi: t.clone() };
        prover.prove(build_trace(w))
    }));
    match built {
        Err(_) | Ok(Err(_)) => false,
        Ok(Ok(proof)) => verify_at(proof, t.build(), 95),
    }
}

fn expect(w: &BundleW, t: &PublicInputsTemplate, want: bool) -> String {
    let got = accepts(w, t);
    let v = if got { "accepted" } else { "rejected" };
    if got == want {
        format!("{v:<8}  as expected")
    } else {
        format!("{v:<8}  *** WRONG ***")
    }
}

// --- main -------------------------------------------------------------------

fn main() {
    println!("Step 2.5 -- balance, and the first complete bundle\n");

    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    let path = p.join("tests").join("vectors").join("shielded_rescue-rp64-256.json");
    let j: Value =
        serde_json::from_str(&fs::read_to_string(&path).expect("read golden")).expect("json");

    let empty: Vec<[BaseElement; DIG]> = j["merkle"]["empty_roots"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| limbs(&unhex(v.as_str().unwrap())))
        .collect();

    // Spend witnesses drawn from the node's notes, so every derivation in the
    // circuit has something published to disagree with.
    let notes = j["notes"].as_array().unwrap();
    let kds = j["key_derivation"].as_array().unwrap();
    let mk_spend = |n: usize| -> (SpendW, [BaseElement; DIG], [BaseElement; DIG]) {
        let note = &notes[n];
        let kd = kds
            .iter()
            .find(|k| k["nullifier_key"] == note["nullifier_key"])
            .expect("key for note");
        let dv = encode_bytes(&unhex(kd["diversifier"].as_str().unwrap()));
        (
            SpendW {
                ask: limbs(&unhex(kd["spending_key"].as_str().unwrap())),
                div: dv.try_into().unwrap(),
                value: BaseElement::new(note["value"].as_u64().unwrap()),
                rho: limbs(&unhex(note["rho"].as_str().unwrap())),
                rcm: limbs(&unhex(note["rcm"].as_str().unwrap())),
                leaf: limbs(&unhex(note["commitment"].as_str().unwrap())),
                siblings: Vec::new(),
                bits: Vec::new(),
            },
            limbs(&unhex(note["commitment"].as_str().unwrap())),
            limbs(&unhex(note["nullifier"].as_str().unwrap())),
        )
    };

    // Outputs are ours to choose; pick values that are not degenerate for a range
    // gadget and do not accidentally balance by symmetry.
    let mk_out = |v: u64, seed: u64| OutW {
        value: BaseElement::new(v),
        pkd: h_dom(DOMAIN_DIVERSIFIED_KEY, &[BaseElement::new(seed)]),
        rho: h_dom(DOMAIN_NULLIFIER, &[BaseElement::new(seed + 1)]),
        rcm: h_dom(DOMAIN_NOTE, &[BaseElement::new(seed + 2)]),
    };

    // note indices with distinct values, so a mixed-up ordering shows up
    let spend_notes = [5usize, 2, 4, 1];

    println!(
        "{:<26} {:>4} {:>5} {:>11} {:>9} {:>9} {:>8}",
        "bundle", "cols", "rows", "proof bytes", "prove ms", "verify ms", "tx/MB"
    );
    println!("{}", "-".repeat(80));

    let mut built: Vec<(usize, usize, BundleW, PublicInputsTemplate)> = Vec::new();

    for (s, o) in [(1usize, 2usize), (2, 2), (4, 2)] {
        let lay = Layout { spends: s, outputs: o };
        assert!(lay.width() <= WIDTH_CAP, "layout exceeds the 254 cap");

        // one aligned run of adjacent leaves, so all spends share one anchor
        let mut sws: Vec<SpendW> = Vec::new();
        let mut nfs: Vec<[BaseElement; DIG]> = Vec::new();
        let mut leaves: Vec<[BaseElement; DIG]> = Vec::new();
        for i in 0..s {
            let (sw, cm, nf) = mk_spend(spend_notes[i]);
            leaves.push(cm);
            nfs.push(nf);
            sws.push(sw);
        }
        let run = s.next_power_of_two();
        while leaves.len() < run {
            leaves.push(empty[0]); // pad the run with empty slots
        }
        let base = 0x9E37_79B9usize & !(run - 1);
        let (anchor, paths) = adjacent_paths(base, &leaves, &empty);
        for (i, sw) in sws.iter_mut().enumerate() {
            sw.siblings = paths[i].0.clone();
            sw.bits = paths[i].1.clone();
            assert_eq!(
                native_root(&sw.leaf, &sw.siblings, &sw.bits),
                anchor,
                "spend {i} does not open under the shared anchor"
            );
        }

        // balance: shield some value in, split across the outputs
        let spent: u64 = sws.iter().map(|x| x.value.as_int()).sum();
        let vb_pos: u64 = 900_000_000_000_003; // shielding: value enters the pool
        let total = spent + vb_pos;
        let mut outs: Vec<OutW> = Vec::new();
        let mut left = total;
        for k in 0..o {
            let v = if k + 1 == o { left } else { total / 3 + 7 * (k as u64 + 1) };
            left -= v;
            outs.push(mk_out(v, 1_000 + k as u64));
        }
        let cms: Vec<[BaseElement; DIG]> = outs.iter().map(|x| x.commitment()).collect();

        assert_no_wrap(VALUE_BITS, (s + 1).max(o + 1));
        let w = BundleW {
            spends: sws,
            outputs: outs,
            vb_pos: BaseElement::new(vb_pos),
            vb_neg: BaseElement::ZERO,
            value_bits: VALUE_BITS,
        };
        let t = PublicInputsTemplate {
            spends: s,
            outputs: o,
            value_bits: VALUE_BITS,
            anchor,
            nullifiers: nfs,
            commitments: cms,
            vb_pos: BaseElement::new(vb_pos),
            vb_neg: BaseElement::ZERO,
        };

        // every derivation checked against the node before anything is proved
        let trace = build_trace(&w);
        for i in 0..s {
            let c = lay.spend(i);
            let at = |col: usize, row: usize| -> [BaseElement; DIG] {
                let mut d = [BaseElement::ZERO; DIG];
                for k in 0..DIG {
                    d[k] = trace.get(col + k, row);
                }
                d
            };
            assert_eq!(at(c.b + RATE, CM_ROW), w.spends[i].leaf, "spend {i} cm");
            assert_eq!(at(c.a + RATE, NF_ROW), t.nullifiers[i], "spend {i} nf");
            assert_eq!(at(c.e + RATE, ANCHOR_ROW), anchor, "spend {i} anchor");
            assert_eq!(trace.get(c.racc, VALUE_BITS), w.spends[i].value, "spend {i} range");
        }
        for k in 0..o {
            let c = lay.output(k);
            let mut d = [BaseElement::ZERO; DIG];
            for q in 0..DIG {
                d[q] = trace.get(c.c + RATE + q, OUT_CM_ROW);
            }
            assert_eq!(d, t.commitments[k], "output {k} commitment");
            assert_eq!(trace.get(c.racc, VALUE_BITS), w.outputs[k].value, "output {k} range");
        }
        let bal = lay.bal();
        assert_eq!(
            trace.get(bal.in_acc, VALUE_BITS),
            trace.get(bal.out_acc, VALUE_BITS),
            "balance sides disagree"
        );

        let prover = BundleProver { options: opts(43), pi: t.clone() };
        let t0 = Instant::now();
        let proof = prover.prove(trace).expect("prove failed");
        let prove_ms = t0.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();
        let t0 = Instant::now();
        for _ in 0..10 {
            assert!(verify_at(proof.clone(), t.build(), 128), "honest bundle rejected");
        }
        let verify_ms = t0.elapsed().as_secs_f64() * 1000.0 / 10.0;

        println!(
            "{:<26} {:>4} {:>5} {:>11} {:>9.1} {:>9.3} {:>8.1}",
            format!("{s} spend(s) + {o} outputs"),
            lay.width(),
            TRACE_LEN,
            size,
            prove_ms,
            verify_ms,
            1048576.0 / size as f64
        );
        built.push((s, o, w, t));
    }

    // ---- soundness on the 2-spend bundle -----------------------------------
    let (_, _, w2, t2) = built
        .iter()
        .find(|(s, o, _, _)| *s == 2 && *o == 2)
        .expect("2x2 bundle");

    println!("\nbalance (2 spends + 2 outputs):");
    println!("  honest bundle                            : {}", expect(w2, t2, true));

    // inflate one output: the sum no longer settles
    let mut w = w2.clone();
    w.outputs[0].value += BaseElement::ONE;
    let mut t = t2.clone();
    t.commitments[0] = w.outputs[0].commitment();
    println!("  one output inflated by 1                 : {}", expect(&w, &t, false));

    // move value between outputs: total unchanged, so this MUST still verify --
    // the circuit constrains the sum, not the split
    let mut w = w2.clone();
    w.outputs[0].value += BaseElement::new(1_000);
    w.outputs[1].value -= BaseElement::new(1_000);
    let mut t = t2.clone();
    t.commitments[0] = w.outputs[0].commitment();
    t.commitments[1] = w.outputs[1].commitment();
    println!("  value moved between outputs (sum same)   : {}", expect(&w, &t, true));

    // claim a larger shielding than the outputs account for
    let mut t = t2.clone();
    t.vb_pos += BaseElement::ONE;
    let mut w = w2.clone();
    w.vb_pos += BaseElement::ONE;
    println!("  value_balance inflated by 1              : {}", expect(&w, &t, false));

    // NOT a wrap: adding p-1 to one output and 1 to the other is subtracting 1
    // and adding 1 in the field. It moves a unit between outputs, which is the
    // case above, and it MUST be accepted. Recording it because it looks like a
    // wraparound test and is not one.
    let mut w = w2.clone();
    w.outputs[0].value += BaseElement::ZERO - BaseElement::ONE;
    w.outputs[1].value += BaseElement::ONE;
    let mut t = t2.clone();
    t.commitments[0] = w.outputs[0].commitment();
    t.commitments[1] = w.outputs[1].commitment();
    println!("  +(p-1) and +1 -- a unit moved, not a wrap: {}", expect(&w, &t, true));

    // a spend whose value is out of range (2.4 still holding inside the bundle)
    let mut w = w2.clone();
    w.spends[0].value = BaseElement::new(1u64 << 63);
    let mut e = vec![w.spends[0].value];
    e.extend_from_slice(&h_dom(
        DOMAIN_DIVERSIFIED_KEY,
        &{
            let mut v = w.spends[0].ask.to_vec();
            v.extend_from_slice(&w.spends[0].div);
            v
        },
    ));
    e.extend_from_slice(&w.spends[0].rho);
    e.extend_from_slice(&w.spends[0].rcm);
    w.spends[0].leaf = h_dom(DOMAIN_NOTE, &e);
    println!("  spend value 2^63 (self-consistent note)  : {}", expect(&w, t2, false));

    // ---- THE WRAP ----------------------------------------------------------
    // Two outputs at the OLD MAX_NOTE_VALUE. Each passes a 63-bit range check on
    // its own; their integer sum is p + 4294967293, so the field sum is tiny and
    // the balance equation settles against a shielding of about 4.3e9. The same
    // bundle is run at both widths: 63 accepts it and mints p, 61 refuses to
    // decompose the values at all.
    println!("\nwraparound (2 spends + 2 outputs, minting bundle):");
    let old_max = (1u64 << 63) - 1;
    let pmod = BaseElement::MODULUS as u128;
    let residue = ((2u128 * old_max as u128) % pmod) as u64;
    println!(
        "  two outputs of 2^63-1: integer sum {} = p + {}",
        2u128 * old_max as u128,
        residue
    );

    let mut mint_leaves: Vec<[BaseElement; DIG]> = Vec::new();
    let mut mint_nfs: Vec<[BaseElement; DIG]> = Vec::new();
    let mut mint_spends: Vec<SpendW> = Vec::new();
    for n in [1usize, 4] {
        let (sw, cm, nf) = mk_spend(n);
        mint_leaves.push(cm);
        mint_nfs.push(nf);
        mint_spends.push(sw);
    }
    let spent_small: u64 = mint_spends.iter().map(|x| x.value.as_int()).sum();
    let base = 0x9E37_79B9usize & !1usize;
    let (mint_anchor, mint_paths) = adjacent_paths(base, &mint_leaves, &empty);
    for (i, sw) in mint_spends.iter_mut().enumerate() {
        sw.siblings = mint_paths[i].0.clone();
        sw.bits = mint_paths[i].1.clone();
    }
    // vb chosen so the FIELD equation is exact against the wrapped output sum
    let mint_vb = residue - spent_small;
    let mint_outs = vec![
        OutW { value: BaseElement::new(old_max), ..mk_out(0, 2_000) },
        OutW { value: BaseElement::new(old_max), ..mk_out(0, 3_000) },
    ];
    let mint_cms: Vec<[BaseElement; DIG]> = mint_outs.iter().map(|x| x.commitment()).collect();
    println!(
        "  spends {spent_small} + vb {mint_vb} = {residue}, which is what the field sees"
    );

    for bits in [63usize, 61] {
        let w = BundleW {
            spends: mint_spends.clone(),
            outputs: mint_outs.clone(),
            vb_pos: BaseElement::new(mint_vb),
            vb_neg: BaseElement::ZERO,
            value_bits: bits,
        };
        let t = PublicInputsTemplate {
            spends: 2,
            outputs: 2,
            value_bits: bits,
            anchor: mint_anchor,
            nullifiers: mint_nfs.clone(),
            commitments: mint_cms.clone(),
            vb_pos: BaseElement::new(mint_vb),
            vb_neg: BaseElement::ZERO,
        };
        let ok = accepts(&w, &t);
        let terms = 3usize;
        let safe = (terms as u128) << bits <= pmod;
        println!(
            "  VALUE_BITS = {bits}  ({terms} terms x 2^{bits} {} p)  : {}",
            if safe { "<=" } else { " >" },
            match (ok, safe) {
                (true, false) => "ACCEPTED -- mints p, as predicted".to_string(),
                (false, true) => "rejected  as expected".to_string(),
                (true, true) => "ACCEPTED -- *** WRONG ***".to_string(),
                (false, false) => "rejected  (unexpected, but safe)".to_string(),
            }
        );
    }
    assert!(
        (MAX_TERMS as u128) << VALUE_BITS <= pmod,
        "MAX_TERMS and VALUE_BITS are inconsistent with the modulus"
    );

    // ---- the ceiling -------------------------------------------------------
    println!("\ncolumn budget (256 rows, cap {WIDTH_CAP}):");
    println!("  per spend  {SPEND_COLS:>4}   per output {OUT_COLS:>4}   balance {BAL_COLS:>4}");
    for s in 1..=6usize {
        let lay = Layout { spends: s, outputs: 2 };
        println!(
            "  {s} spend(s) + 2 outputs = {:>4} columns   {}",
            lay.width(),
            if lay.width() <= WIDTH_CAP { "fits" } else { "OVER" }
        );
    }
}
