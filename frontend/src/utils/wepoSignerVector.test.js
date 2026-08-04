import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  assertStandardSendIntent,
  canonicalSighashHex,
  canonicalSighashMaterialHex,
  canonicalTransactionMaterialHex,
  deriveWepoKeypair,
  estimateSignedTransactionWireSize,
  signTransaction,
  verifyTransactionInput,
} from './wepoSigner';

const vector = JSON.parse(
  readFileSync(
    resolve(process.cwd(), '..', 'tests', 'vectors', 'wallet_signing_v3.json'),
    'utf8',
  ),
);

function vectorSignedTransaction() {
  return {
    ...vector.unsigned_tx,
    inputs: vector.unsigned_tx.inputs.map((input) => ({
      ...input,
      signature_type: 'dilithium',
      quantum_public_key: vector.expected.owner_public_key,
      quantum_signature: vector.expected.deterministic_signature,
      script_sig: '',
    })),
  };
}

test('published wallet signing vector matches the shipping JavaScript signer', () => {
  expect(vector.schema).toBe('wepo-wallet-signing-vector-v3');
  expect(vector.test_only).toBe(true);

  const owner = deriveWepoKeypair(vector.owner_mnemonic);
  const recipient = deriveWepoKeypair(vector.recipient_mnemonic);
  expect(owner.address).toBe(vector.expected.owner_address);
  expect(owner.publicKeyHex).toBe(vector.expected.owner_public_key);
  expect(recipient.address).toBe(vector.expected.recipient_address);
  expect(canonicalSighashHex(vector.unsigned_tx, vector.network)).toBe(
    vector.expected.canonical_sighash,
  );
  const sighashMaterial = canonicalSighashMaterialHex(vector.unsigned_tx, vector.network);
  expect(sighashMaterial.payload).toBe(
    vector.expected.sighash_payload_utf8_hex,
  );
  expect(sighashMaterial.preimage).toBe(vector.expected.sighash_preimage_hex);

  const signedVector = vectorSignedTransaction();
  const transactionMaterial = canonicalTransactionMaterialHex(signedVector);
  expect(transactionMaterial.payload).toBe(
    vector.expected.signed_transaction_payload_utf8_hex,
  );
  expect(transactionMaterial.preimage).toBe(vector.expected.txid_preimage_hex);
  expect(transactionMaterial.txid).toBe(vector.expected.txid);
  expect(verifyTransactionInput(signedVector, 0, vector.network)).toBe(true);
  expect(estimateSignedTransactionWireSize(vector.unsigned_tx)).toBe(
    vector.expected.signed_transaction_payload_utf8_hex.length / 2,
  );

  expect(
    canonicalTransactionMaterialHex({
      ...signedVector,
      shielded_bundle: null,
    }).txid,
  ).toBe(vector.expected.txid);

  const tamperedSignature = {
    ...signedVector,
    inputs: signedVector.inputs.map((input, index) => ({
      ...input,
      quantum_signature:
        index === 0 ? `00${input.quantum_signature.slice(2)}` : input.quantum_signature,
    })),
  };
  expect(canonicalSighashHex(tamperedSignature, vector.network)).toBe(
    vector.expected.canonical_sighash,
  );
  expect(canonicalTransactionMaterialHex(tamperedSignature).txid).not.toBe(
    vector.expected.txid,
  );

  const fresh = signTransaction(
    vector.unsigned_tx,
    owner.secretKey,
    owner.publicKey,
    vector.expected.canonical_sighash,
    vector.network,
  );
  expect(verifyTransactionInput(fresh, 0, vector.network)).toBe(true);
});
describe('standard send intent binding', () => {
  const ownerAddress = vector.expected.owner_address;
  const recipientAddress = vector.expected.recipient_address;
  const intent = {
    senderAddress: ownerAddress,
    recipientAddress,
    amountAtomic: 300000000n,
    feeAtomic: 10000n,
  };
  const standardUnsigned = () => ({
    version: 1,
    lock_time: 0,
    timestamp: 1700000000,
    fee: 10000,
    tx_type: 'transfer',
    extra_data: {},
    privacy_proof: null,
    ring_signature: null,
    shielded_bundle: null,
    inputs: [{
      prev_txid: 'aa'.repeat(32),
      prev_vout: 0,
      sequence: 4294967295,
      script_sig: '7369676e61747572655f706c616365686f6c646572',
      signature_type: 'ecdsa',
      quantum_signature: null,
      quantum_public_key: null,
    }],
    outputs: [{
      value: 300000000,
      address: recipientAddress,
      script_pubkey: '6f75747075745f736372697074',
    }, {
      value: 699990000,
      address: ownerAddress,
      script_pubkey: '6368616e67655f736372697074',
    }],
  });

  test('accepts only the exact transparent transfer the user approved', () => {
    expect(assertStandardSendIntent(standardUnsigned(), intent)).toBe(true);
  });

  test.each([
    ['recipient', (tx) => { tx.outputs[0].address = ownerAddress; }],
    ['amount', (tx) => { tx.outputs[0].value += 1; }],
    ['fee', (tx) => { tx.fee += 1; }],
    ['third-party output', (tx) => { tx.outputs.push({ ...tx.outputs[1], address: recipientAddress }); }],
    ['change owner', (tx) => { tx.outputs[1].address = recipientAddress; }],
    ['metadata', (tx) => { tx.extra_data = { memo: 'hidden' }; }],
    ['lock time', (tx) => { tx.lock_time = 1; }],
    ['shielded data', (tx) => { tx.shielded_bundle = { spends: [], outputs: [], value_balance: 0 }; }],
    ['duplicate input', (tx) => { tx.inputs.push({ ...tx.inputs[0] }); }],
    ['sequence', (tx) => { tx.inputs[0].sequence = 0; }],
    ['placeholder', (tx) => { tx.inputs[0].script_sig = ''; }],
    ['pre-attached signature', (tx) => { tx.inputs[0].signature_type = 'dilithium'; }],
    ['unsafe output value', (tx) => { tx.outputs[0].value = Number.MAX_SAFE_INTEGER + 1; }],
  ])('rejects builder tampering of %s', (_label, mutate) => {
    const tx = standardUnsigned();
    mutate(tx);
    expect(() => assertStandardSendIntent(tx, intent)).toThrow(/Refusing to sign/);
  });
});
