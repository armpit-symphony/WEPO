//! Production Ghost wallet primitives and complete-bundle prover boundary.
//!
//! This module is a child of the complete bundle AIR so it cannot drift to a
//! second hash/proof implementation. Callers provide decoded, fixed-width local
//! wallet data; secret witness material is never serialized or sent to a node.

use super::*;
use std::{
    collections::HashSet,
    fmt,
    panic::{self, AssertUnwindSafe},
};

pub const WALLET_BRIDGE_KIND: &str = "wepo-local-ghost-crypto-v1";
pub const MERKLE_PATH_DEPTH: usize = DEPTH;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WalletError {
    Invalid(&'static str),
    Inconsistent(&'static str),
    ProverFailure,
}

impl fmt::Display for WalletError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid Ghost wallet input: {message}"),
            Self::Inconsistent(message) => {
                write!(formatter, "inconsistent Ghost witness: {message}")
            }
            Self::ProverFailure => formatter.write_str("Ghost proof engine rejected the witness"),
        }
    }
}

impl std::error::Error for WalletError {}

#[derive(Clone, Debug)]
pub struct SpendWitness {
    pub spending_key: [u8; 32],
    pub diversifier: [u8; 11],
    pub value: u64,
    pub rho: [u8; 32],
    pub rcm: [u8; 32],
    pub position: u32,
    pub siblings: [[u8; 32]; MERKLE_PATH_DEPTH],
}

#[derive(Clone, Debug)]
pub struct OutputWitness {
    pub value: u64,
    pub pk_d: [u8; 32],
    pub rho: [u8; 32],
    pub rcm: [u8; 32],
}

#[derive(Clone, Debug)]
pub struct BundleWitness {
    pub spends: Vec<SpendWitness>,
    pub outputs: Vec<OutputWitness>,
    pub value_balance: i64,
    pub sighash: [u8; 32],
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProvedBundle {
    pub anchor: [u8; 32],
    pub nullifiers: Vec<[u8; 32]>,
    pub commitments: Vec<[u8; 32]>,
    pub value_balance: i64,
    pub sighash: [u8; 32],
    pub raw_proof: Vec<u8>,
}

fn parse_digest(value: &[u8; 32], label: &'static str) -> Result<[BaseElement; DIG], WalletError> {
    let mut result = [BaseElement::ZERO; DIG];
    for (index, output) in result.iter_mut().enumerate() {
        let start = index * 8;
        let limb = u64::from_le_bytes(value[start..start + 8].try_into().expect("fixed slice"));
        if limb >= BaseElement::MODULUS {
            return Err(WalletError::Invalid(label));
        }
        *output = BaseElement::new(limb);
    }
    Ok(result)
}

fn digest_bytes(value: &[BaseElement; DIG]) -> [u8; 32] {
    to_bytes(value).try_into().expect("four field elements")
}

fn checked_value(value: u64) -> Result<BaseElement, WalletError> {
    if value > (1u64 << VALUE_BITS) - 1 {
        return Err(WalletError::Invalid("note value exceeds 61 bits"));
    }
    Ok(BaseElement::new(value))
}

fn note_commitment_elements(
    value: u64,
    pk_d: &[u8; 32],
    rho: &[u8; 32],
    rcm: &[u8; 32],
) -> Result<[BaseElement; DIG], WalletError> {
    let mut elements = vec![checked_value(value)?];
    elements.extend_from_slice(&parse_digest(pk_d, "non-canonical pk_d")?);
    elements.extend_from_slice(&parse_digest(rho, "non-canonical rho")?);
    elements.extend_from_slice(&parse_digest(rcm, "non-canonical rcm")?);
    Ok(h_dom(DOMAIN_NOTE, &elements))
}

pub fn derive_nullifier_key(spending_key: &[u8; 32]) -> Result<[u8; 32], WalletError> {
    let key = parse_digest(spending_key, "non-canonical spending key")?;
    Ok(digest_bytes(&h_dom(DOMAIN_NULLIFIER_KEY, &key)))
}

pub fn derive_diversified_key(
    spending_key: &[u8; 32],
    diversifier: &[u8; 11],
) -> Result<[u8; 32], WalletError> {
    let mut elements = parse_digest(spending_key, "non-canonical spending key")?.to_vec();
    elements.extend_from_slice(&encode_bytes(diversifier));
    Ok(digest_bytes(&h_dom(DOMAIN_DIVERSIFIED_KEY, &elements)))
}

pub fn note_commitment(
    value: u64,
    pk_d: &[u8; 32],
    rho: &[u8; 32],
    rcm: &[u8; 32],
) -> Result<[u8; 32], WalletError> {
    Ok(digest_bytes(&note_commitment_elements(
        value, pk_d, rho, rcm,
    )?))
}

pub fn note_nullifier(spending_key: &[u8; 32], rho: &[u8; 32]) -> Result<[u8; 32], WalletError> {
    let nk = parse_digest(
        &derive_nullifier_key(spending_key)?,
        "derived nullifier key",
    )?;
    let mut elements = nk.to_vec();
    elements.extend_from_slice(&parse_digest(rho, "non-canonical rho")?);
    Ok(digest_bytes(&h_dom(DOMAIN_NULLIFIER, &elements)))
}

/// Verify one durable-note Merkle witness against a claimed anchor.
///
/// This is exposed through the same native/WASM bridge as proving so the
/// wallet never falls back to a different browser hash implementation.
pub fn verify_merkle_path(
    commitment: &[u8; 32],
    anchor: &[u8; 32],
    position: u32,
    siblings: &[[u8; 32]; MERKLE_PATH_DEPTH],
) -> Result<(), WalletError> {
    let leaf = parse_digest(commitment, "non-canonical commitment")?;
    let parsed_siblings: Vec<[BaseElement; DIG]> = siblings
        .iter()
        .map(|value| parse_digest(value, "non-canonical Merkle sibling"))
        .collect::<Result<_, _>>()?;
    let bits: Vec<bool> = (0..DEPTH)
        .map(|level| ((position >> level) & 1) == 1)
        .collect();
    if digest_bytes(&native_root(&leaf, &parsed_siblings, &bits)) != *anchor {
        return Err(WalletError::Inconsistent(
            "Merkle witness does not match anchor",
        ));
    }
    Ok(())
}

fn empty_anchor() -> [BaseElement; DIG] {
    let mut root = h_dom(1, &[]); // DOMAIN_LEAF is frozen as 1 by consensus.
    for _ in 0..DEPTH {
        root = node(&root, &root);
    }
    root
}

fn prove_inner(bundle: BundleWitness) -> Result<ProvedBundle, WalletError> {
    if (bundle.spends.is_empty() && bundle.outputs.is_empty())
        || bundle.spends.len() > 4
        || bundle.outputs.len() > 2
    {
        return Err(WalletError::Invalid("bundle shape"));
    }
    if bundle.value_balance.unsigned_abs() > (1u64 << VALUE_BITS) - 1 {
        return Err(WalletError::Invalid("value balance exceeds 61 bits"));
    }

    let mut spends = Vec::with_capacity(bundle.spends.len());
    let mut nullifiers = Vec::with_capacity(bundle.spends.len());
    let mut anchor = None;
    let mut seen = HashSet::new();
    let mut spent_value = 0u128;
    for spend in bundle.spends {
        let ask = parse_digest(&spend.spending_key, "non-canonical spending key")?;
        let div: [BaseElement; 3] = encode_bytes(&spend.diversifier)
            .try_into()
            .map_err(|_| WalletError::Invalid("diversifier encoding"))?;
        let pk_d = parse_digest(
            &derive_diversified_key(&spend.spending_key, &spend.diversifier)?,
            "derived pk_d",
        )?;
        let rho = parse_digest(&spend.rho, "non-canonical rho")?;
        let rcm = parse_digest(&spend.rcm, "non-canonical rcm")?;
        let leaf =
            note_commitment_elements(spend.value, &digest_bytes(&pk_d), &spend.rho, &spend.rcm)?;
        let siblings: Vec<[BaseElement; DIG]> = spend
            .siblings
            .iter()
            .map(|value| parse_digest(value, "non-canonical Merkle sibling"))
            .collect::<Result<_, _>>()?;
        let bits: Vec<bool> = (0..DEPTH)
            .map(|level| ((spend.position >> level) & 1) == 1)
            .collect();
        let root = native_root(&leaf, &siblings, &bits);
        if anchor
            .replace(root)
            .is_some_and(|expected| expected != root)
        {
            return Err(WalletError::Inconsistent("spends do not share one anchor"));
        }
        let nullifier = parse_digest(
            &note_nullifier(&spend.spending_key, &spend.rho)?,
            "derived nullifier",
        )?;
        if !seen.insert(digest_bytes(&nullifier)) {
            return Err(WalletError::Inconsistent("duplicate nullifier"));
        }
        spent_value += spend.value as u128;
        nullifiers.push(nullifier);
        spends.push(SpendW {
            ask,
            div,
            value: checked_value(spend.value)?,
            rho,
            rcm,
            leaf,
            siblings,
            bits,
        });
    }

    let mut outputs = Vec::with_capacity(bundle.outputs.len());
    let mut commitments = Vec::with_capacity(bundle.outputs.len());
    let mut output_value = 0u128;
    for output in bundle.outputs {
        let witness = OutW {
            value: checked_value(output.value)?,
            pkd: parse_digest(&output.pk_d, "non-canonical output pk_d")?,
            rho: parse_digest(&output.rho, "non-canonical output rho")?,
            rcm: parse_digest(&output.rcm, "non-canonical output rcm")?,
        };
        output_value += output.value as u128;
        commitments.push(witness.commitment());
        outputs.push(witness);
    }

    let (vb_pos, vb_neg) = if bundle.value_balance >= 0 {
        (bundle.value_balance as u64, 0u64)
    } else {
        (0u64, bundle.value_balance.unsigned_abs())
    };
    if spent_value + vb_pos as u128 != output_value + vb_neg as u128 {
        return Err(WalletError::Inconsistent(
            "private and public values do not balance",
        ));
    }
    assert_no_wrap(VALUE_BITS, (spends.len() + 1).max(outputs.len() + 1));
    let anchor = anchor.unwrap_or_else(empty_anchor);
    let witness = BundleW {
        spends,
        outputs,
        vb_pos: BaseElement::new(vb_pos),
        vb_neg: BaseElement::new(vb_neg),
        value_bits: VALUE_BITS,
    };
    let public_inputs = PublicInputsTemplate {
        spends: witness.spends.len(),
        outputs: witness.outputs.len(),
        value_bits: VALUE_BITS,
        anchor,
        nullifiers: nullifiers.clone(),
        commitments: commitments.clone(),
        vb_pos: BaseElement::new(vb_pos),
        vb_neg: BaseElement::new(vb_neg),
        statement_binding: statement_binding(&bundle.sighash),
    };
    let prover = BundleProver {
        options: opts(43),
        pi: public_inputs.clone(),
    };
    let proof = prover
        .prove(build_trace(&witness))
        .map_err(|_| WalletError::ProverFailure)?;
    if !verify_at(proof.clone(), public_inputs.build(), 128) {
        return Err(WalletError::ProverFailure);
    }
    Ok(ProvedBundle {
        anchor: digest_bytes(&anchor),
        nullifiers: nullifiers.iter().map(digest_bytes).collect(),
        commitments: commitments.iter().map(digest_bytes).collect(),
        value_balance: bundle.value_balance,
        sighash: bundle.sighash,
        raw_proof: proof.to_bytes(),
    })
}

/// Build a complete proof locally. Any malformed witness, engine panic, or
/// self-verification failure is returned as an error rather than crossing FFI.
pub fn prove_bundle(bundle: BundleWitness) -> Result<ProvedBundle, WalletError> {
    match panic::catch_unwind(AssertUnwindSafe(|| prove_inner(bundle))) {
        Ok(result) => result,
        Err(_) => Err(WalletError::ProverFailure),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex<const N: usize>(value: &str) -> [u8; N] {
        assert_eq!(value.len(), N * 2);
        let mut result = [0u8; N];
        for (index, byte) in result.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).unwrap();
        }
        result
    }

    #[test]
    fn key_and_note_primitives_match_consensus_vectors() {
        let spending_key = [1u8; 32];
        let diversifier = [0u8; 11];
        assert_eq!(
            derive_nullifier_key(&spending_key).unwrap(),
            hex("572f95f90e639777dccb9288aecfca571ae8c8986f08fbfea34a98a243259387")
        );
        let pk_d = derive_diversified_key(&spending_key, &diversifier).unwrap();
        assert_eq!(
            pk_d,
            hex("0f1d1fc851f8a9edcd583be3f131d3ef53f10dc5e76b961033f16f9cdace3628")
        );
        let rho = hex("000b16212c37424d58636e79848f9aa5b0bbc6d1dce7f2fd08131e29343f4a55");
        let rcm = hex("747f8a95a0abb6c1ccd7e2edf8030e19242f3a45505b66717c87929da8b3bec9");
        assert_eq!(
            note_commitment(0, &pk_d, &rho, &rcm).unwrap(),
            hex("9c5067130f437ee8394148c1ff3c65031a4f4a98213d17291ef528d6370f23a2")
        );
        assert_eq!(
            note_nullifier(&spending_key, &rho).unwrap(),
            hex("3649ced389684e21b21b0d384b2a4c388169a4c7306af50874c32e2675843ebc")
        );
    }

    #[test]
    fn primitives_reject_noncanonical_or_oversized_inputs() {
        assert!(derive_nullifier_key(&[0xff; 32]).is_err());
        assert!(note_commitment(1u64 << VALUE_BITS, &[0u8; 32], &[0u8; 32], &[0u8; 32]).is_err());
    }

    #[test]
    fn prover_rejects_an_unbalanced_witness_before_proving() {
        let output = OutputWitness {
            value: 1,
            pk_d: [0u8; 32],
            rho: [0u8; 32],
            rcm: [0u8; 32],
        };
        let bundle = BundleWitness {
            spends: vec![],
            outputs: vec![output],
            value_balance: 0,
            sighash: [0u8; 32],
        };
        assert!(matches!(
            prove_bundle(bundle),
            Err(WalletError::Inconsistent(_))
        ));
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn production_prover_builds_a_self_verified_shielding_bundle() {
        let output = OutputWitness {
            value: 900_000_000_000_003,
            pk_d: hex("0f1d1fc851f8a9edcd583be3f131d3ef53f10dc5e76b961033f16f9cdace3628"),
            rho: hex("000b16212c37424d58636e79848f9aa5b0bbc6d1dce7f2fd08131e29343f4a55"),
            rcm: hex("747f8a95a0abb6c1ccd7e2edf8030e19242f3a45505b66717c87929da8b3bec9"),
        };
        let proved = prove_bundle(BundleWitness {
            spends: vec![],
            outputs: vec![output],
            value_balance: 900_000_000_000_003,
            sighash: [7u8; 32],
        })
        .expect("balanced shielding bundle must prove");
        assert_eq!(proved.nullifiers, Vec::<[u8; 32]>::new());
        assert_eq!(proved.commitments.len(), 1);
        assert!(production::verify_complete_bundle(
            &proved.anchor,
            &proved.nullifiers,
            &proved.commitments,
            proved.value_balance,
            &proved.sighash,
            &proved.raw_proof,
        ));
    }
}
