//! Production verification entry point for the complete five-condition AIR.

use super::*;
use winter_utils::{ByteReader, Deserializable, DeserializationError};

// Winterfell's generic SliceReader allocates `read_many()` capacity from proof
// metadata before every claimed element has been consumed. A proof is capped at
// one MiB, so accepting an unbounded collection count here would let a few
// hostile bytes request multi-gigabyte allocation before deserialization fails.
const MAX_PROOF_COLLECTION_ITEMS: usize = 65_536;
const HASH_DIGEST_BYTES: usize = 32;

/// A bounded reader for untrusted Winterfell proof bytes.
///
/// Every requested byte vector must fit in the unread input; every generic
/// collection is additionally bounded before Winterfell can reserve capacity.
/// The latter is needed because its default `ByteReader::read_many()` reserves
/// based on a metadata count before it discovers truncated elements.
struct BoundedProofReader<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> BoundedProofReader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn remaining(&self) -> usize {
        self.bytes.len() - self.offset
    }

    fn invalid_size() -> DeserializationError {
        DeserializationError::InvalidValue("proof collection exceeds verifier limit".into())
    }
}

fn invalid_proof_size() -> DeserializationError {
    DeserializationError::InvalidValue("proof structure exceeds verifier limit".into())
}

fn skip_bytes(reader: &mut BoundedProofReader<'_>, len: usize) -> Result<(), DeserializationError> {
    reader.read_slice(len).map(|_| ())
}

fn preflight_batch_merkle_proof(bytes: &[u8]) -> Result<(), DeserializationError> {
    let mut reader = BoundedProofReader::new(bytes);
    let depth = reader.read_u8()?;
    if depth > 64 {
        return Err(invalid_proof_size());
    }

    let node_vectors = reader.read_usize()?;
    if node_vectors > MAX_PROOF_COLLECTION_ITEMS || node_vectors > reader.remaining() {
        return Err(invalid_proof_size());
    }

    for _ in 0..node_vectors {
        let digests = reader.read_usize()?;
        if digests > MAX_PROOF_COLLECTION_ITEMS || digests > reader.remaining() / HASH_DIGEST_BYTES
        {
            return Err(invalid_proof_size());
        }
        skip_bytes(&mut reader, digests * HASH_DIGEST_BYTES)?;
    }

    if reader.has_more_bytes() {
        return Err(DeserializationError::UnconsumedBytes);
    }
    Ok(())
}

fn preflight_queries(reader: &mut BoundedProofReader<'_>) -> Result<(), DeserializationError> {
    let values_len = reader.read_usize()?;
    skip_bytes(reader, values_len)?;

    let paths_len = reader.read_usize()?;
    if paths_len > reader.remaining() {
        return Err(invalid_proof_size());
    }
    let paths = reader.read_slice(paths_len)?.to_vec();
    preflight_batch_merkle_proof(&paths)
}

fn preflight_fri_proof(reader: &mut BoundedProofReader<'_>) -> Result<(), DeserializationError> {
    let layers = reader.read_u8()? as usize;
    for _ in 0..layers {
        let values_len = reader.read_u32()? as usize;
        if values_len == 0 {
            return Err(invalid_proof_size());
        }
        skip_bytes(reader, values_len)?;

        let paths_len = reader.read_u32()? as usize;
        if paths_len > reader.remaining() {
            return Err(invalid_proof_size());
        }
        let paths = reader.read_slice(paths_len)?.to_vec();
        preflight_batch_merkle_proof(&paths)?;
    }

    let remainder_len = reader.read_u16()? as usize;
    skip_bytes(reader, remainder_len)?;
    reader.read_u8()?;
    Ok(())
}

fn preflight_context(reader: &mut BoundedProofReader<'_>) -> Result<usize, DeserializationError> {
    let main_width = reader.read_u8()?;
    if main_width == 0 {
        return Err(invalid_proof_size());
    }
    let aux_width = reader.read_u8()?;
    reader.read_u8()?;
    reader.read_u8()?;

    let trace_meta_len = reader.read_u16()? as usize;
    skip_bytes(reader, trace_meta_len)?;

    let modulus_len = reader.read_u8()? as usize;
    if modulus_len == 0 {
        return Err(invalid_proof_size());
    }
    skip_bytes(reader, modulus_len)?;

    skip_bytes(reader, 10)?;
    let constraints = reader.read_usize()?;
    if constraints == 0 || constraints > MAX_PROOF_COLLECTION_ITEMS {
        return Err(invalid_proof_size());
    }

    Ok(if aux_width == 0 { 1 } else { 2 })
}

fn preflight_serialized_proof(raw_proof: &[u8]) -> Result<(), DeserializationError> {
    let mut reader = BoundedProofReader::new(raw_proof);
    let trace_segments = preflight_context(&mut reader)?;
    reader.read_u8()?;

    let commitments_len = reader.read_u16()? as usize;
    skip_bytes(&mut reader, commitments_len)?;

    for _ in 0..trace_segments {
        preflight_queries(&mut reader)?;
    }
    preflight_queries(&mut reader)?;

    let trace_state_len = reader.read_u16()? as usize;
    skip_bytes(&mut reader, trace_state_len)?;
    let constraint_state_len = reader.read_u16()? as usize;
    skip_bytes(&mut reader, constraint_state_len)?;

    preflight_fri_proof(&mut reader)?;
    reader.read_u64()?;

    if reader.has_more_bytes() {
        return Err(DeserializationError::UnconsumedBytes);
    }
    Ok(())
}
impl ByteReader for BoundedProofReader<'_> {
    fn read_u8(&mut self) -> Result<u8, DeserializationError> {
        Ok(self.read_slice(1)?[0])
    }

    fn peek_u8(&self) -> Result<u8, DeserializationError> {
        self.bytes
            .get(self.offset)
            .copied()
            .ok_or(DeserializationError::UnexpectedEOF)
    }

    fn read_slice(&mut self, len: usize) -> Result<&[u8], DeserializationError> {
        self.check_eor(len)?;
        let end = self.offset + len;
        let value = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(value)
    }

    fn read_array<const N: usize>(&mut self) -> Result<[u8; N], DeserializationError> {
        self.read_slice(N)?
            .try_into()
            .map_err(|_| DeserializationError::UnexpectedEOF)
    }

    fn check_eor(&self, num_bytes: usize) -> Result<(), DeserializationError> {
        if num_bytes <= self.remaining() {
            Ok(())
        } else {
            Err(DeserializationError::UnexpectedEOF)
        }
    }

    fn has_more_bytes(&self) -> bool {
        self.offset != self.bytes.len()
    }

    fn read_vec(&mut self, len: usize) -> Result<Vec<u8>, DeserializationError> {
        if len > self.remaining() {
            return Err(DeserializationError::UnexpectedEOF);
        }
        Ok(self.read_slice(len)?.to_vec())
    }

    fn read_many<D>(&mut self, num_elements: usize) -> Result<Vec<D>, DeserializationError>
    where
        Self: Sized,
        D: Deserializable,
    {
        if num_elements > MAX_PROOF_COLLECTION_ITEMS || num_elements > self.remaining() {
            return Err(Self::invalid_size());
        }
        let mut result = Vec::with_capacity(num_elements);
        for _ in 0..num_elements {
            result.push(D::read_from(self)?);
        }
        Ok(result)
    }
}

/// Verify a complete Ghost proof against its public bundle statement.
///
/// The caller has already checked that the versioned envelope hashes to the
/// node-supplied statement digest. This function independently freezes the AIR
/// shape and value width, parses canonical field limbs, and contains every
/// Winterfell parse/AIR panic as a simple rejection.
pub fn verify_complete_bundle(
    anchor: &[u8; 32],
    nullifiers: &[[u8; 32]],
    commitments: &[[u8; 32]],
    value_balance: i64,
    sighash: &[u8; 32],
    raw_proof: &[u8],
) -> bool {
    let outcome = panic::catch_unwind(AssertUnwindSafe(|| {
        let spends = nullifiers.len();
        let outputs = commitments.len();
        if (spends == 0 && outputs == 0)
            || spends > 4
            || outputs > 2
            || value_balance.unsigned_abs() > (1u64 << VALUE_BITS) - 1
            || raw_proof.is_empty()
            || raw_proof.len() > 1024 * 1024
        {
            return false;
        }
        let layout = Layout { spends, outputs };
        if layout.width() > WIDTH_CAP {
            return false;
        }
        assert_no_wrap(VALUE_BITS, (spends + 1).max(outputs + 1));

        let (vb_pos, vb_neg) = if value_balance >= 0 {
            (BaseElement::new(value_balance as u64), BaseElement::ZERO)
        } else {
            (
                BaseElement::ZERO,
                BaseElement::new(value_balance.unsigned_abs()),
            )
        };
        let pi = PublicInputs {
            spends,
            outputs,
            value_bits: VALUE_BITS,
            anchor: limbs(anchor),
            nullifiers: nullifiers.iter().map(|value| limbs(value)).collect(),
            commitments: commitments.iter().map(|value| limbs(value)).collect(),
            vb_pos,
            vb_neg,
            statement_binding: statement_binding(sighash),
        };
        if preflight_serialized_proof(raw_proof).is_err() {
            return false;
        }
        let mut reader = BoundedProofReader::new(raw_proof);
        match Proof::read_from(&mut reader) {
            Ok(proof) if !reader.has_more_bytes() => verify_at(proof, pi, 128),
            _ => false,
        }
    }));
    matches!(outcome, Ok(true))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_reader_rejects_untrusted_collection_before_reserving() {
        let proof = vec![0u8; MAX_PROOF_COLLECTION_ITEMS + 1];
        let mut reader = BoundedProofReader::new(&proof);
        assert!(reader
            .read_many::<u8>(MAX_PROOF_COLLECTION_ITEMS + 1)
            .is_err());
    }

    #[test]
    fn nested_merkle_preflight_rejects_impossible_node_vector_count() {
        let mut proof = vec![0u8];
        proof.push(0);
        proof.extend_from_slice(&u64::MAX.to_le_bytes());
        assert!(preflight_batch_merkle_proof(&proof).is_err());
    }

    #[test]
    fn nested_merkle_preflight_rejects_impossible_digest_count() {
        let mut proof = vec![0u8, 3, 0];
        proof.extend_from_slice(&u64::MAX.to_le_bytes());
        assert!(preflight_batch_merkle_proof(&proof).is_err());
    }
}
