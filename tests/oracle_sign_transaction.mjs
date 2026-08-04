#!/usr/bin/env node
// Deterministically signs oracle-fixture transactions or exact message bytes.
import { readFileSync } from 'node:fs';
import { ml_dsa44 } from '../frontend/node_modules/@noble/post-quantum/ml-dsa.js';
import {
  bytesToHex,
  canonicalSighashHex,
  deriveWepoKeypair,
  hexToBytes,
} from '../frontend/src/utils/wepoSigner.js';

const request = JSON.parse(readFileSync(0, 'utf8'));
if (typeof request.mnemonic !== 'string') {
  throw new Error('Expected mnemonic');
}
const hasTransaction = request.unsigned_tx && typeof request.unsigned_tx === 'object';
const hasMessage = typeof request.message_hex === 'string';
if (hasTransaction === hasMessage) {
  throw new Error('Expected exactly one of unsigned_tx or message_hex');
}

const keypair = deriveWepoKeypair(request.mnemonic);
if (hasMessage) {
  if (
    request.message_hex.length % 2 !== 0
    || !/^[0-9a-f]*$/u.test(request.message_hex)
  ) {
    throw new Error('message_hex must be lowercase even-length hex');
  }
  const message = hexToBytes(request.message_hex);
  const signature = ml_dsa44.sign(message, keypair.secretKey, {
    extraEntropy: false,
  });
  if (!ml_dsa44.verify(signature, message, keypair.publicKey)) {
    throw new Error('Deterministic fixture signature did not self-verify');
  }
  process.stdout.write(JSON.stringify({
    address: keypair.address,
    public_key: keypair.publicKeyHex,
    message_hex: request.message_hex,
    signature: bytesToHex(signature),
  }));
} else {
  if (typeof request.network !== 'string') {
    throw new Error('Expected network for transaction signing');
  }
  const sighash = canonicalSighashHex(request.unsigned_tx, request.network);
  const signature = ml_dsa44.sign(hexToBytes(sighash), keypair.secretKey, {
    extraEntropy: false,
  });
  if (!ml_dsa44.verify(signature, hexToBytes(sighash), keypair.publicKey)) {
    throw new Error('Deterministic fixture signature did not self-verify');
  }
  const signed = {
    ...request.unsigned_tx,
    inputs: request.unsigned_tx.inputs.map((input) => ({
      ...input,
      script_sig: '',
      signature_type: 'dilithium',
      quantum_public_key: keypair.publicKeyHex,
      quantum_signature: bytesToHex(signature),
    })),
  };
  process.stdout.write(JSON.stringify({
    address: keypair.address,
    public_key: keypair.publicKeyHex,
    sighash,
    signed_tx: signed,
  }));
}
