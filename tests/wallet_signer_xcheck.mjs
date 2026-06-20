// JS half of the wallet-signer cross-check. Imports the SHIPPED wallet module,
// derives a keypair from a fixed mnemonic, builds and signs a transfer, and
// emits a fixture the Python half verifies against the real chain.
// Run from the frontend/ directory so @noble resolves from frontend/node_modules.
import {
  deriveWepoKeypair,
  canonicalSighashHex,
  signTransaction,
  verifyTransactionInput,
} from '../frontend/src/utils/wepoSigner.js';
import { writeFileSync } from 'node:fs';

const mnemonic = 'wepo signer cross check fixed mnemonic for deterministic test';
const owner = deriveWepoKeypair(mnemonic);
const recipient = deriveWepoKeypair('a different recipient mnemonic');

const COIN = 100000000;
const unsignedTx = {
  version: 1,
  lock_time: 0,
  fee: 10000,
  tx_type: 'transfer',
  timestamp: 1700000000,
  extra_data: {},
  privacy_proof: null,
  ring_signature: null,
  inputs: [
    { prev_txid: 'a'.repeat(64), prev_vout: 0, sequence: 4294967295,
      script_sig: '', signature_type: 'ecdsa', quantum_signature: null, quantum_public_key: null },
  ],
  outputs: [
    { value: 3 * COIN, address: recipient.address, script_pubkey: Buffer.from('output_script').toString('hex') },
    { value: 7 * COIN - 10000, address: owner.address, script_pubkey: Buffer.from('change_script').toString('hex') },
  ],
};

const sighash = canonicalSighashHex(unsignedTx);
const signed = signTransaction(unsignedTx, owner.secretKey, owner.publicKey, sighash);

writeFileSync('/tmp/wepo_signer_fixture.json', JSON.stringify({
  owner_address: owner.address,
  owner_pubkey: owner.publicKeyHex,
  sighash,
  signed_tx: signed,
  js_self_verify: verifyTransactionInput(signed, 0),
}));
console.log('JS: owner', owner.address, '| self-verify', verifyTransactionInput(signed, 0));
