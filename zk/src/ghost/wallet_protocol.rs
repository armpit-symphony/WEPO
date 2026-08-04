//! Bounded local transport for the Ghost wallet bridge.
//!
//! The same request handler is intended for the native desktop sidecar and a
//! browser-WASM wrapper. Secret witness bytes are request-only; responses carry
//! public derivations, a proof envelope, or a fixed error code.

use super::{
    protocol::{self, PublicStatement},
    wallet::{self, BundleWitness, OutputWitness, SpendWitness, MERKLE_PATH_DEPTH},
};

pub const REQUEST_MAGIC: &[u8; 21] = b"WEPO_GHOST_WALLET_V1\0";
pub const RESPONSE_MAGIC: &[u8; 21] = b"WEPO_GHOST_WALLET_R1\0";
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_RESPONSE_BYTES: usize = protocol::MAX_PROOF_BYTES + 4096;

const STATUS_OK: u8 = 0;
const STATUS_REJECTED: u8 = 1;
const OP_DERIVE_DIVERSIFIED_KEY: u8 = 1;
const OP_COMMIT_NOTE: u8 = 2;
const OP_NULLIFIER: u8 = 3;
const OP_PROVE_BUNDLE: u8 = 4;
const OP_VERIFY_MERKLE_PATH: u8 = 5;

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

    fn byte(&mut self) -> Option<u8> {
        Some(*self.take(1)?.first()?)
    }
    fn u32(&mut self) -> Option<u32> {
        Some(u32::from_le_bytes(self.take(4)?.try_into().ok()?))
    }
    fn u64(&mut self) -> Option<u64> {
        Some(u64::from_le_bytes(self.take(8)?.try_into().ok()?))
    }
    fn i64(&mut self) -> Option<i64> {
        Some(i64::from_le_bytes(self.take(8)?.try_into().ok()?))
    }
    fn array<const N: usize>(&mut self) -> Option<[u8; N]> {
        self.take(N)?.try_into().ok()
    }
    fn finished(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

fn response(status: u8, payload: &[u8]) -> Vec<u8> {
    let mut result = Vec::with_capacity(RESPONSE_MAGIC.len() + 5 + payload.len());
    result.extend_from_slice(RESPONSE_MAGIC);
    result.push(status);
    result.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    result.extend_from_slice(payload);
    result
}

fn rejected() -> Vec<u8> {
    response(STATUS_REJECTED, &[])
}

fn decode_bundle(cursor: &mut Cursor<'_>) -> Option<BundleWitness> {
    let spend_count = cursor.byte()? as usize;
    let output_count = cursor.byte()? as usize;
    if (spend_count == 0 && output_count == 0) || spend_count > 4 || output_count > 2 {
        return None;
    }
    let value_balance = cursor.i64()?;
    let sighash = cursor.array()?;
    let mut spends = Vec::with_capacity(spend_count);
    for _ in 0..spend_count {
        let spending_key = cursor.array()?;
        let diversifier = cursor.array()?;
        let value = cursor.u64()?;
        let rho = cursor.array()?;
        let rcm = cursor.array()?;
        let position = cursor.u32()?;
        let mut siblings = [[0u8; 32]; MERKLE_PATH_DEPTH];
        for sibling in &mut siblings {
            *sibling = cursor.array()?;
        }
        spends.push(SpendWitness {
            spending_key,
            diversifier,
            value,
            rho,
            rcm,
            position,
            siblings,
        });
    }
    let mut outputs = Vec::with_capacity(output_count);
    for _ in 0..output_count {
        outputs.push(OutputWitness {
            value: cursor.u64()?,
            pk_d: cursor.array()?,
            rho: cursor.array()?,
            rcm: cursor.array()?,
        });
    }
    Some(BundleWitness {
        spends,
        outputs,
        value_balance,
        sighash,
    })
}

fn handle_inner(request: &[u8]) -> Option<Vec<u8>> {
    if request.len() > MAX_REQUEST_BYTES {
        return None;
    }
    let mut cursor = Cursor::new(request);
    if cursor.take(REQUEST_MAGIC.len())? != REQUEST_MAGIC {
        return None;
    }
    let operation = cursor.byte()?;
    let payload = match operation {
        OP_DERIVE_DIVERSIFIED_KEY => {
            let spending_key = cursor.array()?;
            let diversifier = cursor.array()?;
            if !cursor.finished() {
                return None;
            }
            wallet::derive_diversified_key(&spending_key, &diversifier)
                .ok()?
                .to_vec()
        }
        OP_COMMIT_NOTE => {
            let value = cursor.u64()?;
            let pk_d = cursor.array()?;
            let rho = cursor.array()?;
            let rcm = cursor.array()?;
            if !cursor.finished() {
                return None;
            }
            wallet::note_commitment(value, &pk_d, &rho, &rcm)
                .ok()?
                .to_vec()
        }
        OP_NULLIFIER => {
            let spending_key = cursor.array()?;
            let rho = cursor.array()?;
            if !cursor.finished() {
                return None;
            }
            wallet::note_nullifier(&spending_key, &rho).ok()?.to_vec()
        }
        OP_PROVE_BUNDLE => {
            let bundle = decode_bundle(&mut cursor)?;
            if !cursor.finished() {
                return None;
            }
            let proved = wallet::prove_bundle(bundle).ok()?;
            let statement = PublicStatement {
                anchor: proved.anchor,
                nullifiers: proved.nullifiers,
                commitments: proved.commitments,
                value_balance: proved.value_balance,
                sighash: proved.sighash,
            };
            protocol::encode_envelope(&statement, &proved.raw_proof)?
        }
        OP_VERIFY_MERKLE_PATH => {
            let commitment = cursor.array()?;
            let anchor = cursor.array()?;
            let position = cursor.u32()?;
            let mut siblings = [[0u8; 32]; MERKLE_PATH_DEPTH];
            for sibling in &mut siblings {
                *sibling = cursor.array()?;
            }
            if !cursor.finished() {
                return None;
            }
            wallet::verify_merkle_path(&commitment, &anchor, position, &siblings).ok()?;
            vec![1]
        }
        _ => return None,
    };
    if payload.len() > MAX_RESPONSE_BYTES {
        return None;
    }
    Some(response(STATUS_OK, &payload))
}

/// Handle exactly one local bridge request. Malformed and cryptographically
/// invalid requests have the same empty rejection response to avoid echoing
/// witness material or creating a parser oracle at the FFI boundary.
pub fn handle_request(request: &[u8]) -> Vec<u8> {
    handle_inner(request).unwrap_or_else(rejected)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_response(value: &[u8]) -> (u8, &[u8]) {
        let mut cursor = Cursor::new(value);
        assert_eq!(cursor.take(RESPONSE_MAGIC.len()).unwrap(), RESPONSE_MAGIC);
        let status = cursor.byte().unwrap();
        let length = cursor.u32().unwrap() as usize;
        let payload = cursor.take(length).unwrap();
        assert!(cursor.finished());
        (status, payload)
    }

    #[test]
    fn diversified_key_request_matches_consensus_vector() {
        let mut request = REQUEST_MAGIC.to_vec();
        request.push(OP_DERIVE_DIVERSIFIED_KEY);
        request.extend_from_slice(&[1u8; 32]);
        request.extend_from_slice(&[0u8; 11]);
        let response = handle_request(&request);
        let (status, payload) = parse_response(&response);
        assert_eq!(status, STATUS_OK);
        assert_eq!(
            payload,
            wallet::derive_diversified_key(&[1u8; 32], &[0u8; 11]).unwrap()
        );
    }

    #[test]
    fn malformed_requests_fail_closed_without_echoing_secrets() {
        let mut request = REQUEST_MAGIC.to_vec();
        request.push(OP_NULLIFIER);
        request.extend_from_slice(&[0x42; 64]);
        request.push(0);
        let result = handle_request(&request);
        let (status, payload) = parse_response(&result);
        assert_eq!(status, STATUS_REJECTED);
        assert!(payload.is_empty());
        assert!(!result.windows(8).any(|window| window == [0x42; 8]));
        assert_eq!(
            handle_request(&vec![0u8; MAX_REQUEST_BYTES + 1]),
            rejected()
        );
    }
}
