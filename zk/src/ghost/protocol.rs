//! Versioned wire formats shared by the Ghost proof producer and verifier.
//!
//! The outer request is the node-to-verifier subprocess protocol. The inner
//! proof envelope carries only public bundle data plus the raw Winterfell proof.
//! The verifier recomputes the node's statement digest from those public fields
//! before passing them to the complete bundle AIR.

use winterfell::{
    crypto::{hashers::Rp64_256, Digest, ElementHasher},
    math::fields::f64::BaseElement,
};

pub const REQUEST_MAGIC: &[u8; 21] = b"WEPO_GHOST_VERIFY_V1\0";
pub const PROOF_MAGIC: &[u8; 20] = b"WEPO_GHOST_PROOF_V1\0";
pub const STATEMENT_DIGEST_LEN: usize = 32;
pub const MAX_PROOF_BYTES: usize = 1024 * 1024;
pub const MAX_SHIELDED_SPENDS: usize = 4;
pub const MAX_SHIELDED_OUTPUTS: usize = 2;
pub const SHIELDED_VALUE_BITS: u32 = 61;
pub const MAX_NOTE_VALUE: i64 = (1i64 << SHIELDED_VALUE_BITS) - 1;

const BUNDLE_TAG: &[u8] = b"WEPO-Shielded-BundleStatement-v1";
const FELT_BYTES: usize = 7;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PublicStatement {
    pub anchor: [u8; 32],
    pub nullifiers: Vec<[u8; 32]>,
    pub commitments: Vec<[u8; 32]>,
    pub value_balance: i64,
    pub sighash: [u8; 32],
}

pub struct ProofEnvelope<'a> {
    pub statement: PublicStatement,
    pub raw_proof: &'a [u8],
}

fn push_field(out: &mut Vec<u8>, value: &[u8]) {
    out.extend_from_slice(&(value.len() as u32).to_le_bytes());
    out.extend_from_slice(value);
}

fn pool_hash(data: &[u8]) -> [u8; 32] {
    let mut elements = Vec::with_capacity(1 + data.len() / FELT_BYTES + 1);
    elements.push(BaseElement::new(data.len() as u64));
    for chunk in data.chunks(FELT_BYTES) {
        let mut buf = [0u8; 8];
        buf[..chunk.len()].copy_from_slice(chunk);
        elements.push(BaseElement::new(u64::from_le_bytes(buf)));
    }
    Rp64_256::hash_elements(&elements).as_bytes()
}

pub fn statement_digest(statement: &PublicStatement) -> [u8; 32] {
    let mut encoded = Vec::new();
    push_field(&mut encoded, BUNDLE_TAG);
    push_field(&mut encoded, &statement.anchor);
    push_field(
        &mut encoded,
        &(statement.nullifiers.len() as u32).to_le_bytes(),
    );
    let mut nullifiers = Vec::with_capacity(statement.nullifiers.len() * 32);
    for nullifier in &statement.nullifiers {
        nullifiers.extend_from_slice(nullifier);
    }
    push_field(&mut encoded, &nullifiers);
    push_field(
        &mut encoded,
        &(statement.commitments.len() as u32).to_le_bytes(),
    );
    let mut commitments = Vec::with_capacity(statement.commitments.len() * 32);
    for commitment in &statement.commitments {
        commitments.extend_from_slice(commitment);
    }
    push_field(&mut encoded, &commitments);
    push_field(&mut encoded, &statement.value_balance.to_le_bytes());
    push_field(&mut encoded, &statement.sighash);
    pool_hash(&encoded)
}

pub fn encode_envelope(statement: &PublicStatement, raw_proof: &[u8]) -> Option<Vec<u8>> {
    if !valid_shape(statement) || raw_proof.is_empty() || raw_proof.len() > MAX_PROOF_BYTES {
        return None;
    }
    let mut out = Vec::with_capacity(
        PROOF_MAGIC.len()
            + 2
            + 32
            + statement.nullifiers.len() * 32
            + statement.commitments.len() * 32
            + 8
            + 32
            + 4
            + raw_proof.len(),
    );
    out.extend_from_slice(PROOF_MAGIC);
    out.push(statement.nullifiers.len() as u8);
    out.push(statement.commitments.len() as u8);
    out.extend_from_slice(&statement.anchor);
    for nullifier in &statement.nullifiers {
        out.extend_from_slice(nullifier);
    }
    for commitment in &statement.commitments {
        out.extend_from_slice(commitment);
    }
    out.extend_from_slice(&statement.value_balance.to_le_bytes());
    out.extend_from_slice(&statement.sighash);
    out.extend_from_slice(&(raw_proof.len() as u32).to_le_bytes());
    out.extend_from_slice(raw_proof);
    Some(out)
}

pub fn encode_request(statement_digest: &[u8; 32], envelope: &[u8]) -> Option<Vec<u8>> {
    if envelope.is_empty() || envelope.len() > MAX_PROOF_BYTES {
        return None;
    }
    let mut out =
        Vec::with_capacity(REQUEST_MAGIC.len() + STATEMENT_DIGEST_LEN + 4 + envelope.len());
    out.extend_from_slice(REQUEST_MAGIC);
    out.extend_from_slice(statement_digest);
    out.extend_from_slice(&(envelope.len() as u32).to_le_bytes());
    out.extend_from_slice(envelope);
    Some(out)
}

fn valid_shape(statement: &PublicStatement) -> bool {
    let spends = statement.nullifiers.len();
    let outputs = statement.commitments.len();
    (spends != 0 || outputs != 0)
        && spends <= MAX_SHIELDED_SPENDS
        && outputs <= MAX_SHIELDED_OUTPUTS
        && statement.value_balance.unsigned_abs() <= MAX_NOTE_VALUE as u64
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, count: usize) -> Option<&'a [u8]> {
        let end = self.offset.checked_add(count)?;
        let value = self.bytes.get(self.offset..end)?;
        self.offset = end;
        Some(value)
    }

    fn u8(&mut self) -> Option<u8> {
        Some(*self.take(1)?.first()?)
    }

    fn u32(&mut self) -> Option<u32> {
        Some(u32::from_le_bytes(self.take(4)?.try_into().ok()?))
    }

    fn i64(&mut self) -> Option<i64> {
        Some(i64::from_le_bytes(self.take(8)?.try_into().ok()?))
    }

    fn array32(&mut self) -> Option<[u8; 32]> {
        self.take(32)?.try_into().ok()
    }

    fn finished(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

pub fn parse_request(request: &[u8]) -> Option<([u8; 32], &[u8])> {
    let mut cursor = Cursor::new(request);
    if cursor.take(REQUEST_MAGIC.len())? != REQUEST_MAGIC {
        return None;
    }
    let digest = cursor.array32()?;
    let envelope_len = cursor.u32()? as usize;
    if envelope_len == 0 || envelope_len > MAX_PROOF_BYTES {
        return None;
    }
    let envelope = cursor.take(envelope_len)?;
    if !cursor.finished() {
        return None;
    }
    Some((digest, envelope))
}

pub fn parse_envelope(envelope: &[u8]) -> Option<ProofEnvelope<'_>> {
    let mut cursor = Cursor::new(envelope);
    if cursor.take(PROOF_MAGIC.len())? != PROOF_MAGIC {
        return None;
    }
    let spends = cursor.u8()? as usize;
    let outputs = cursor.u8()? as usize;
    if (spends == 0 && outputs == 0)
        || spends > MAX_SHIELDED_SPENDS
        || outputs > MAX_SHIELDED_OUTPUTS
    {
        return None;
    }
    let anchor = cursor.array32()?;
    let mut nullifiers = Vec::with_capacity(spends);
    for _ in 0..spends {
        nullifiers.push(cursor.array32()?);
    }
    let mut commitments = Vec::with_capacity(outputs);
    for _ in 0..outputs {
        commitments.push(cursor.array32()?);
    }
    let value_balance = cursor.i64()?;
    let sighash = cursor.array32()?;
    let raw_proof_len = cursor.u32()? as usize;
    if raw_proof_len == 0 || raw_proof_len > MAX_PROOF_BYTES {
        return None;
    }
    let raw_proof = cursor.take(raw_proof_len)?;
    if !cursor.finished() {
        return None;
    }
    let statement = PublicStatement {
        anchor,
        nullifiers,
        commitments,
        value_balance,
        sighash,
    };
    if !valid_shape(&statement) {
        return None;
    }
    Some(ProofEnvelope {
        statement,
        raw_proof,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn from_hex<const N: usize>(value: &str) -> [u8; N] {
        assert_eq!(value.len(), N * 2);
        let mut out = [0u8; N];
        for (index, byte) in out.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).unwrap();
        }
        out
    }

    #[test]
    fn statement_digest_matches_python_vector() {
        let statement = PublicStatement {
            anchor: from_hex("a45e7ecc761a8be2c56658abb4907c9bcd00bfb3bd794bb201c57fa37fb80a0d"),
            nullifiers: vec![
                from_hex("3649ced389684e21b21b0d384b2a4c388169a4c7306af50874c32e2675843ebc"),
                from_hex("15b1516313b181975058065f05d8a6892323464647e1da38a4a4e6f46fef955f"),
            ],
            commitments: vec![
                from_hex("e8ec86360e97174560e8b73db1d2a3adc0eb3b8590f9932a7f07bf4055081a18"),
                from_hex("3069097aeb338d183a08ac3c6672137cc372321fd63a2d05d4cd2a29c0a48e6e"),
            ],
            value_balance: -12345,
            sighash: from_hex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
        };
        assert_eq!(
            statement_digest(&statement),
            from_hex("eef182de038c6c940015ceec330e8ff850921f6b9acf26bbedb5d80cd5a889fa")
        );
    }

    #[test]
    fn envelope_round_trip_is_exact_and_bounded() {
        let statement = PublicStatement {
            anchor: [1u8; 32],
            nullifiers: vec![[2u8; 32]],
            commitments: vec![[3u8; 32], [4u8; 32]],
            value_balance: 7,
            sighash: [5u8; 32],
        };
        let proof = [9u8; 16];
        let envelope = encode_envelope(&statement, &proof).unwrap();
        let parsed = parse_envelope(&envelope).unwrap();
        assert_eq!(parsed.statement, statement);
        assert_eq!(parsed.raw_proof, proof);
        assert!(parse_envelope(&envelope[..envelope.len() - 1]).is_none());

        let digest = statement_digest(&statement);
        let request = encode_request(&digest, &envelope).unwrap();
        let (parsed_digest, parsed_envelope) = parse_request(&request).unwrap();
        assert_eq!(parsed_digest, digest);
        assert_eq!(parsed_envelope, envelope);
        let mut trailing = request;
        trailing.push(0);
        assert!(parse_request(&trailing).is_none());
    }
}
