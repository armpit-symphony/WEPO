// Regenerates the committed, test-only wallet/consensus signing vector.
// The fixed ML-DSA hedging input makes the sample signature reproducible.
import { writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { ml_dsa44 } from '../frontend/node_modules/@noble/post-quantum/ml-dsa.js';
import {
  bytesToHex,
  canonicalSighashHex,
  canonicalSighashMaterialHex,
  canonicalTransactionMaterialHex,
  deriveWepoKeypair,
  hexToBytes,
} from '../frontend/src/utils/wepoSigner.js';

function uint32LE(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value);
  return buffer;
}

function uint64LE(value) {
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64LE(BigInt(value));
  return buffer;
}

function lengthPrefixed(value) {
  return Buffer.concat([uint32LE(value.length), value]);
}

function canonicalHeaderBytes(header, includeValidatorSignature = true) {
  const validatorSignature = includeValidatorSignature
    ? Buffer.from(header.validator_signature || '', 'hex')
    : Buffer.alloc(0);
  return Buffer.concat([
    Buffer.from('WEPO_BLOCK_HEADER_V2\u0000', 'ascii'),
    uint32LE(header.version),
    Buffer.from(header.prev_hash, 'hex'),
    Buffer.from(header.merkle_root, 'hex'),
    uint64LE(header.timestamp),
    uint32LE(header.bits),
    uint32LE(header.nonce),
    lengthPrefixed(Buffer.from(header.consensus_type, 'ascii')),
    lengthPrefixed(Buffer.from(header.validator_address || '', 'ascii')),
    lengthPrefixed(Buffer.from(header.validator_public_key || '', 'hex')),
    lengthPrefixed(validatorSignature),
  ]);
}

function blockHeaderVector(fields) {
  const canonical = canonicalHeaderBytes(fields);
  const signing = canonicalHeaderBytes(fields, false);
  return {
    fields,
    expected: {
      canonical_bytes_hex: canonical.toString('hex'),
      signing_bytes_hex: signing.toString('hex'),
      block_hash: createHash('sha256').update(canonical).digest('hex'),
    },
  };
}

const ownerMnemonic =
  'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';
const recipientMnemonic =
  'legal winner thank year wave sausage worth useful legal winner thank yellow';
const owner = deriveWepoKeypair(ownerMnemonic);
const recipient = deriveWepoKeypair(recipientMnemonic);

const coin = 100_000_000;
const unsignedTx = {
  version: 1,
  lock_time: 0,
  fee: 10_000,
  tx_type: 'transfer',
  timestamp: 1_700_000_000,
  extra_data: {
    zeta: { '\u{1F600}': 2, '\uE000': 1 },
    alpha: [null, true, 'café'],
  },
  privacy_proof: null,
  ring_signature: null,
  inputs: [
    {
      prev_txid: 'a'.repeat(64),
      prev_vout: 0,
      sequence: 4_294_967_295,
      script_sig: '',
      signature_type: 'ecdsa',
      quantum_signature: null,
      quantum_public_key: null,
    },
  ],
  outputs: [
    {
      value: 3 * coin,
      address: recipient.address,
      script_pubkey: Buffer.from('output_script').toString('hex'),
    },
    {
      value: 7 * coin - 10_000,
      address: owner.address,
      script_pubkey: Buffer.from('change_script').toString('hex'),
    },
  ],
};

const network = 'test';
const sighash = canonicalSighashHex(unsignedTx, network);
const signature = ml_dsa44.sign(hexToBytes(sighash), owner.secretKey, {
  extraEntropy: false,
});
if (!ml_dsa44.verify(signature, hexToBytes(sighash), owner.publicKey)) {
  throw new Error('Generated ML-DSA vector does not self-verify');
}
const signedTx = {
  ...unsignedTx,
  inputs: unsignedTx.inputs.map((input) => ({
    ...input,
    signature_type: 'dilithium',
    quantum_public_key: owner.publicKeyHex,
    quantum_signature: bytesToHex(signature),
    script_sig: '',
  })),
};
const sighashMaterial = canonicalSighashMaterialHex(unsignedTx, network);
const transactionMaterial = canonicalTransactionMaterialHex(signedTx);

const blockHeaders = {
  pow: blockHeaderVector({
    version: 1,
    prev_hash: '11'.repeat(32),
    merkle_root: '22'.repeat(32),
    timestamp: 1_700_000_123,
    bits: 4,
    nonce: 42,
    consensus_type: 'pow',
    validator_address: null,
    validator_public_key: null,
    validator_signature: null,
  }),
  pos_serialization: {
    serialization_only: true,
    note: 'Short key/signature bytes exercise framing; cryptographic sizes are covered separately.',
    ...blockHeaderVector({
      version: 1,
      prev_hash: '33'.repeat(32),
      merkle_root: '44'.repeat(32),
      timestamp: 1_700_000_456,
      bits: 0,
      nonce: 0,
      consensus_type: 'pos',
      validator_address: owner.address,
      validator_public_key: '01020304',
      validator_signature: 'aabbcc',
    }),
  },
};


const vector = {
  schema: 'wepo-wallet-signing-vector-v3',
  network,
  test_only: true,
  warning: 'Public deterministic test key; never fund or use outside tests.',
  algorithm: 'ML-DSA-44 (FIPS 204)',
  sighash_domain: 'WEPO_SIGHASH_V3\\0',
  owner_mnemonic: ownerMnemonic,
  recipient_mnemonic: recipientMnemonic,
  block_headers: blockHeaders,
  unsigned_tx: unsignedTx,
  expected: {
    owner_address: owner.address,
    owner_public_key: owner.publicKeyHex,
    recipient_address: recipient.address,
    canonical_sighash: sighash,
    deterministic_signature: bytesToHex(signature),
    sighash_payload_utf8_hex: sighashMaterial.payload,
    sighash_preimage_hex: sighashMaterial.preimage,
    signed_transaction_payload_utf8_hex: transactionMaterial.payload,
    txid_preimage_hex: transactionMaterial.preimage,
    txid: transactionMaterial.txid,
  },
};

const output = fileURLToPath(
  new URL('./vectors/wallet_signing_v3.json', import.meta.url),
);
writeFileSync(output, `${JSON.stringify(vector, null, 2)}\n`, 'utf8');
console.log(`Wrote ${output}`);
