//! Step 2.3 — spend authority, and the binding that makes 2.1 and 2.2 mean
//! something together.
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
//! STILL NOT COMPLETE. `value` is unconstrained here beyond fitting an element:
//! nothing yet forces it into [0, 2^63-1] (step 2.4) and nothing balances inputs
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
//! GEOMETRY. 50 columns x 256 rows. Still 256 -- the whole point of the
//! concurrent layout. Step 2.2 was 25 x 256.

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
    CompositionPoly, CompositionPolyTrace, DefaultConstraintCommitment, DefaultConstraintEvaluator,
    DefaultTraceLde, EvaluationFrame, FieldExtension, PartitionOptions, Proof, ProofOptions,
    Prover, StarkDomain, TraceInfo, TracePolyTable, TraceTable, TransitionConstraintDegree,
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
const TRACE_WIDTH: usize = VAL_COL + 1; // 50

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

const NUM_ASSERTIONS: usize = 26;

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
    }

    fn get_assertions(&self) -> Vec<Assertion<Self::BaseField>> {
        let z = BaseElement::ZERO;
        let mut a = Vec::with_capacity(NUM_ASSERTIONS);

        // instance A row 0: H_dom(DOMAIN_NULLIFIER_KEY, limbs(ask)) -- 4 elements,
        // so the upper half of the rate must be genuine zero padding.
        a.push(Assertion::single(A, 0, BaseElement::new(NK_ELEMENTS)));
        a.push(Assertion::single(
            A + 1,
            0,
            BaseElement::new(DOMAIN_NULLIFIER_KEY),
        ));
        a.push(Assertion::single(A + 2, 0, z));
        a.push(Assertion::single(A + 3, 0, z));
        for i in 0..DIG {
            a.push(Assertion::single(A + RATE + DIG + i, 0, z));
        }

        // instance B row 0: H_dom(DOMAIN_DIVERSIFIED_KEY, limbs(ask) ‖ [11, d0, d1]).
        a.push(Assertion::single(B, 0, BaseElement::new(PKD_ELEMENTS)));
        a.push(Assertion::single(
            B + 1,
            0,
            BaseElement::new(DOMAIN_DIVERSIFIED_KEY),
        ));
        a.push(Assertion::single(B + 2, 0, z));
        a.push(Assertion::single(B + 3, 0, z));
        // the diversifier's length element is fixed at 11 by the node's encoding
        a.push(Assertion::single(
            B + RATE + DIG,
            0,
            BaseElement::new(DIVERSIFIER_LEN),
        ));
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
    let (l, r) = if bit {
        (sibling, digest)
    } else {
        (digest, sibling)
    };
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
            state[BIT_COL] = if w.bits[0] {
                BaseElement::ONE
            } else {
                BaseElement::ZERO
            };
            // carried witness
            for i in 0..DIG {
                state[CM_COL + i] = w.leaf[i];
                state[RHO_COL + i] = w.rho[i];
                state[RCM_COL + i] = w.rcm[i];
            }
            state[VAL_COL] = w.value;
        },
        |step, state| {
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
            let digest: [BaseElement; DIG] = state[E + RATE..E + RATE + DIG].try_into().unwrap();
            let bit = w.bits[level];
            start_node(&digest, &w.siblings[level], bit, state);
            state[BIT_COL] = if bit {
                BaseElement::ONE
            } else {
                BaseElement::ZERO
            };

            // ---- instance A ----------------------------------------------
            if step == CYCLE - 1 {
                // nk is done; open the nullifier sponge over limbs(nk) ‖ limbs(rho)
                let nk: [BaseElement; DIG] = state[A + RATE..A + RATE + DIG].try_into().unwrap();
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
                let pkd: [BaseElement; DIG] = state[B + RATE..B + RATE + DIG].try_into().unwrap();
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
        queries,
        8,
        0,
        FieldExtension::Cubic,
        8,
        31,
        BatchingMethod::Linear,
        BatchingMethod::Linear,
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
    println!("Step 2.3 -- spend authority and binding\n");

    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop();
    let path = p
        .join("tests")
        .join("vectors")
        .join("shielded_rescue-rp64-256.json");
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

    println!(
        "
witness from the node's published vectors (note {NOTE}):"
    );
    println!("  spending key {}", kd["spending_key"].as_str().unwrap());
    println!("  value        {}", note["value"]);
    println!("  commitment   {}", note["commitment"].as_str().unwrap());
    // NOT entry["root"]: that is the deep path's root for ITS leaf (note 0).
    // A different leaf under the same siblings gives a different anchor, and
    // printing the golden one here would look like agreement that never happened.
    println!(
        "  anchor       {}",
        hex(&native_root(&cm, &siblings, &bits))
    );
    println!("  nullifier    {}", note["nullifier"].as_str().unwrap());

    let w = Witness {
        ask,
        div,
        value,
        rho,
        rcm,
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
        (
            "anchor     = 32 node hashes",
            anchor,
            native_root(&cm, &siblings, &bits),
        ),
        // ^ against the native fold, not a published root: this leaf is not the
        //   deep path's own. The published root is pinned separately, above.
    ] {
        assert_eq!(
            got,
            want,
            "{label} disagrees with the node\n  got {}",
            hex(&got)
        );
        println!("  in-trace {label:<36} matches the node : OK");
    }
    // and independently, outside the trace
    let mut cm_elems = vec![value];
    cm_elems.extend_from_slice(&pkd);
    cm_elems.extend_from_slice(&rho);
    cm_elems.extend_from_slice(&rcm);
    assert_eq!(
        h_dom(DOMAIN_NOTE, &cm_elems),
        cm,
        "native H_dom disagrees on cm"
    );
    let mut pkd_elems = ask.to_vec();
    pkd_elems.extend_from_slice(&div);
    assert_eq!(
        h_dom(DOMAIN_DIVERSIFIED_KEY, &pkd_elems),
        golden_pkd,
        "native pk_d"
    );
    println!("  native H_dom agrees on cm and pk_d                       : OK");
    println!("\ntrace rows: {TRACE_LEN}  columns: {TRACE_WIDTH}\n");

    // ---- cost --------------------------------------------------------------
    println!(
        "{:<34} {:>11} {:>10} {:>10} {:>8}",
        "config", "proof bytes", "prove ms", "verify ms", "128-bit"
    );
    println!("{}", "-".repeat(78));
    for (label, queries) in [
        ("96-bit  (32q, blowup 8, cubic)", 32usize),
        ("128-bit (43q, blowup 8, cubic)", 43),
    ] {
        let prover = SpendProver {
            options: opts(queries),
        };
        let t = Instant::now();
        let proof = prover.prove(trace.clone()).expect("prove failed");
        let prove_ms = t.elapsed().as_secs_f64() * 1000.0;
        let size = proof.to_bytes().len();

        let t = Instant::now();
        for _ in 0..20 {
            assert!(
                verify_at(
                    proof.clone(),
                    PublicInputs {
                        anchor,
                        nullifier: nf
                    },
                    95
                ),
                "honest proof rejected"
            );
        }
        let verify_ms = t.elapsed().as_secs_f64() * 1000.0 / 20.0;
        let ok128 = verify_at(
            proof,
            PublicInputs {
                anchor,
                nullifier: nf,
            },
            128,
        );
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
        if verify_at(
            proof.clone(),
            PublicInputs {
                anchor: bad_anchor,
                nullifier: nf
            },
            95
        ) {
            "ACCEPTED -- UNSOUND"
        } else {
            "rejected"
        }
    );
    let mut bad_nf = nf;
    bad_nf[0] += BaseElement::ONE;
    println!(
        "  wrong nullifier                          : {}",
        if verify_at(
            proof,
            PublicInputs {
                anchor,
                nullifier: bad_nf
            },
            95
        ) {
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
    let thief = Witness {
        ask: forged_ask,
        ..w.clone()
    };
    let thief_nf = {
        // the thief reveals the nullifier their own key produces
        let nk2 = h_dom(DOMAIN_NULLIFIER_KEY, &forged_ask);
        let mut e = nk2.to_vec();
        e.extend_from_slice(&rho);
        h_dom(DOMAIN_NULLIFIER, &e)
    };
    println!(
        "  invented key over a public commitment    : {}",
        attempt(
            &thief,
            PublicInputs {
                anchor,
                nullifier: thief_nf
            }
        )
    );

    // (2) the note is real and the key is real, but the value is inflated. The
    //     commitment moves, so the leaf no longer matches.
    let inflated = Witness {
        value: value + BaseElement::ONE,
        ..w.clone()
    };
    println!(
        "  same note, inflated value                : {}",
        attempt(
            &inflated,
            PublicInputs {
                anchor,
                nullifier: nf
            }
        )
    );

    // (3) a different rho, hoping to spend the same note under a fresh
    //     nullifier and double-spend it.
    let mut rho2 = rho;
    rho2[0] += BaseElement::ONE;
    let replay = Witness {
        rho: rho2,
        ..w.clone()
    };
    let replay_nf = {
        let mut e = golden_nk.to_vec();
        e.extend_from_slice(&rho2);
        h_dom(DOMAIN_NULLIFIER, &e)
    };
    println!(
        "  fresh rho to re-spend the same leaf      : {}",
        attempt(
            &replay,
            PublicInputs {
                anchor,
                nullifier: replay_nf
            }
        )
    );

    // (4) a note the prover genuinely owns, but which is not in the tree.
    let mut rcm2 = rcm;
    rcm2[0] += BaseElement::ONE;
    let uncommitted = Witness {
        rcm: rcm2,
        ..w.clone()
    };
    println!(
        "  own note, never appended to the tree     : {}",
        attempt(
            &uncommitted,
            PublicInputs {
                anchor,
                nullifier: nf
            }
        )
    );

    println!(
        "\n  rho is one set of columns read by both the commitment and the\n  \
         nullifier, so \"the same rho\" is structural: there is no second rho\n  \
         to disagree with, and no constraint that could be left out."
    );
}

fn hex(d: &[BaseElement; DIG]) -> String {
    to_bytes(d).iter().map(|b| format!("{b:02x}")).collect()
}
