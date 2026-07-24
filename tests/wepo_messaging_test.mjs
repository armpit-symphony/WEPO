// Post-quantum E2E messaging test — exercises the SHIPPED client module
// (frontend/src/utils/wepoMessaging.js). Run via tests/run_messaging_test.sh so
// @noble resolves from frontend/node_modules.
import {
  deriveMessagingKeypair,
  encryptMessage,
  decryptMessage,
  verifyEnvelope,
  keyOwnerBindingDigest,
  verifyOwnerBinding,
} from '../frontend/src/utils/wepoMessaging.js';
import { deriveWepoKeypair, signDigest } from '../frontend/src/utils/wepoSigner.js';

const FAIL = [];
const check = (name, cond) => {
  console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${name}`);
  if (!cond) FAIL.push(name);
};

const alice = deriveMessagingKeypair('alice messaging mnemonic fixed for test');
const bob = deriveMessagingKeypair('bob messaging mnemonic fixed for test');
const carol = deriveMessagingKeypair('carol messaging mnemonic fixed for test');

// 1) deterministic recovery
const bob2 = deriveMessagingKeypair('bob messaging mnemonic fixed for test');
check('messaging keypair is deterministic from the mnemonic (recovery)',
  bob.publicBundle.kem === bob2.publicBundle.kem && bob.publicBundle.sig === bob2.publicBundle.sig);

const secret = 'meet at the old bridge, midnight — bring the quantum keys';

// 2) round trip Alice -> Bob
const env = encryptMessage({
  plaintext: secret,
  fromAddress: 'wepo1qalice',
  toAddress: 'wepo1qbob',
  recipientKemPublicKeyHex: bob.publicBundle.kem,
  senderSigSecretKey: alice.sigSecretKey,
  senderSigPublicKey: alice.sigPublicKey,
});
const dec = decryptMessage(env, bob.kemSecretKey);
check('recipient decrypts the original plaintext', dec.plaintext === secret);
check('sender signature verifies', dec.verified === true && verifyEnvelope(env) === true);

// 3) blind server: the envelope carries no plaintext
const envJson = JSON.stringify(env);
check('envelope contains no plaintext (server is blind)', !envJson.includes('midnight'));
check('envelope carries only PQ ciphertext fields',
  !!env.kem_ct && !!env.ct && !!env.nonce && env.ct !== secret);

// 4) wrong recipient cannot decrypt
let carolBlocked = false;
try { decryptMessage(env, carol.kemSecretKey); } catch (e) { carolBlocked = true; }
check('a different recipient cannot decrypt', carolBlocked);

// 5) tamper detection (ciphertext)
const tampered = { ...env, ct: env.ct.slice(0, -2) + (env.ct.endsWith('00') ? '11' : '00') };
check('tampered ciphertext fails signature verification', verifyEnvelope(tampered) === false);
let tamperBlocked = false;
try { decryptMessage(tampered, bob.kemSecretKey); } catch (e) { tamperBlocked = true; }
check('tampered ciphertext refuses to decrypt', tamperBlocked);

// 6) sender authenticity: altering 'from' invalidates the signature
const spoofed = { ...env, from: 'wepo1qmallory' };
check('altering the sender invalidates the signature', verifyEnvelope(spoofed) === false);

// 7) spend-key OWNERSHIP binding (front-run prevention, sender-side trust check)
// Bob owns his address via the spend key; his messaging bundle is owner-bound.
const bobSpend = deriveWepoKeypair('bob wallet recovery phrase fixed for test');
const bobKem = bob.publicBundle.kem;
const bobSig = bob.publicBundle.sig;
const bobOwnerSig = signDigest(
  keyOwnerBindingDigest(bobSpend.address, bobKem, bobSig), bobSpend.secretKey);
check('owner-bound bundle verifies for the address that owns it',
  verifyOwnerBinding(bobSpend.address, bobKem, bobSig, bobSpend.publicKeyHex, bobOwnerSig) === true);

// Mallory tries to publish keys for Bob's address, signed with HER spend key.
const mallorySpend = deriveWepoKeypair('mallory wallet recovery phrase fixed for test');
const malloryOwnerSig = signDigest(
  keyOwnerBindingDigest(bobSpend.address, bobKem, bobSig), mallorySpend.secretKey);
check('a non-owner spend key cannot bind another address (front-run blocked)',
  verifyOwnerBinding(bobSpend.address, bobKem, bobSig, mallorySpend.publicKeyHex, malloryOwnerSig) === false);

// Claiming Bob's address while presenting Mallory's own key is rejected by the hash check.
check('owner binding whose pubkey does not hash to the address is rejected',
  verifyOwnerBinding(bobSpend.address, bobKem, bobSig, mallorySpend.publicKeyHex, bobOwnerSig) === false);

console.log('');
if (FAIL.length) { console.log(`RESULT: FAILED (${FAIL.length}): ${FAIL}`); process.exit(1); }
console.log('RESULT: ALL CHECKS PASSED');
