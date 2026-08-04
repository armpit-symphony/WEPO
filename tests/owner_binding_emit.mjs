// Emit a JS-produced, owner-bound messaging registration as JSON on stdout, so a
// Python process (the relay) can verify it — proving the wallet's spend-key
// ownership proof interoperates byte-for-byte with backend/messaging_relay.py.
// Run via tests/run_owner_binding_interop.sh (resolves @noble from frontend/).
import { deriveMessagingKeypair, keyOwnerBindingDigest } from '../frontend/src/utils/wepoMessaging.js';
import { deriveWepoKeypair, signDigest } from '../frontend/src/utils/wepoSigner.js';

const spend = deriveWepoKeypair('interop wallet recovery phrase fixed for test');
const msg = deriveMessagingKeypair('interop messaging seed fixed for test');
const kem_pub = msg.publicBundle.kem;
const sig_pub = msg.publicBundle.sig;
const owner_sig = signDigest(keyOwnerBindingDigest(spend.address, kem_pub, sig_pub), spend.secretKey);

// A different wallet's spend key, to prove the relay rejects a front-run attempt.
const attacker = deriveWepoKeypair('interop attacker recovery phrase fixed for test');
const attacker_owner_sig = signDigest(
  keyOwnerBindingDigest(spend.address, kem_pub, sig_pub), attacker.secretKey);

process.stdout.write(JSON.stringify({
  address: spend.address,
  kem_pub,
  sig_pub,
  owner_sig_pub: spend.publicKeyHex,
  owner_sig,
  attacker_owner_sig_pub: attacker.publicKeyHex,
  attacker_owner_sig,
}));
