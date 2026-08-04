import { sha256 } from '@noble/hashes/sha2.js';
import {
  GHOST_LOCAL_CRYPTO_BRIDGE_KIND,
  createEncryptedGhostOutput,
  createGhostReceiver,
  decodeGhostReceiver,
  deriveGhostSecretMaterial,
  encodeGhostReceiver,
  randomCanonicalFieldValue,
  recoverOutgoingGhostOutput,
  scanGhostOutput,
} from './wepoGhost.js';

const phrase = 'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';

function canonicalDigest(parts) {
  const digest = sha256(Uint8Array.from(parts.flatMap((part) => Array.from(part))));
  const result = digest.slice();
  // SHA-256 limbs can rarely exceed the Goldilocks modulus. Clear each high
  // word in this test-only bridge so its output always satisfies the wallet's
  // canonical-byte contract. This is not a consensus hash implementation.
  for (let offset = 0; offset < result.length; offset += 8) result[offset + 7] = 0;
  return result;
}

function testBridge() {
  return {
    kind: GHOST_LOCAL_CRYPTO_BRIDGE_KIND,
    localOnly: true,
    async deriveDiversifiedKey({ spendingKey, diversifier }) {
      return canonicalDigest([spendingKey, diversifier]);
    },
    async commitNote({ value, pkD, rho, rcm }) {
      const amount = new Uint8Array(8);
      new DataView(amount.buffer).setBigUint64(0, BigInt(value), true);
      return canonicalDigest([amount, pkD, rho, rcm]);
    },
  };
}

test('derives deterministic domain-separated Ghost keys and a checksummed receiver', async () => {
  const first = deriveGhostSecretMaterial(phrase);
  const second = deriveGhostSecretMaterial(phrase);
  expect(() => deriveGhostSecretMaterial('abandon abandon')).toThrow(/BIP-39/);
  expect(first.spendingKey).toEqual(second.spendingKey);
  expect(first.incomingViewingPublicKey).toEqual(second.incomingViewingPublicKey);
  expect(first.outgoingViewingPublicKey).not.toEqual(first.incomingViewingPublicKey);

  const receiver = await createGhostReceiver(first, testBridge(), 'test');
  const decoded = decodeGhostReceiver(receiver, 'test');
  expect(decoded.network).toBe('test');
  expect(decoded.diversifier).toEqual(first.diversifier);
  expect(decoded.incomingViewingPublicKey).toEqual(first.incomingViewingPublicKey);
  expect(() => decodeGhostReceiver(receiver, 'mainnet')).toThrow(/different network/);

  const replacement = receiver.endsWith('A') ? 'B' : 'A';
  expect(() => decodeGhostReceiver(receiver.slice(0, -1) + replacement)).toThrow();
});

test('rejects malformed receiver material and a missing local consensus bridge', async () => {
  const keys = deriveGhostSecretMaterial(phrase);
  await expect(createGhostReceiver(keys, null, 'test')).rejects.toThrow(/local Ghost crypto bridge/);
  expect(() => encodeGhostReceiver({
    network: 'test',
    diversifier: keys.diversifier,
    pkD: new Uint8Array(32).fill(0xff),
    incomingViewingPublicKey: keys.incomingViewingPublicKey,
  })).toThrow(/non-canonical/);
});

test('recipient scanning and outgoing recovery authenticate the commitment and network', async () => {
  const sender = deriveGhostSecretMaterial(phrase, 'sender');
  const recipient = deriveGhostSecretMaterial(phrase, 'recipient');
  const bridge = testBridge();
  const receiver = await createGhostReceiver(recipient, bridge, 'test');
  const output = await createEncryptedGhostOutput({
    receiver,
    senderOutgoingViewingPublicKey: sender.outgoingViewingPublicKey,
    value: 123456789n,
    memo: 'launch-qualified Ghost note',
    rho: randomCanonicalFieldValue(),
    rcm: randomCanonicalFieldValue(),
    bridge,
  });

  expect(new TextDecoder().decode(output.encNote.slice(0, 23))).toBe(
    `WEPO_GHOST_ENC_NOTE_V1${String.fromCharCode(0)}`,
  );
  expect(output.encNote.length).toBeLessThan(16 * 1024);
  const received = await scanGhostOutput({
    commitment: output.commitment,
    encNote: output.encNote,
    secretMaterial: recipient,
    network: 'test',
    bridge,
  });
  expect(received.value).toBe(123456789n);
  expect(received.memo).toBe('launch-qualified Ghost note');

  const recovered = await recoverOutgoingGhostOutput({
    commitment: output.commitment,
    encNote: output.encNote,
    secretMaterial: sender,
    network: 'test',
    bridge,
  });
  expect(recovered.value).toBe(123456789n);
  expect(recovered.pkD).toEqual(received.pkD);

  const stranger = deriveGhostSecretMaterial(phrase, 'stranger');
  expect(await scanGhostOutput({
    commitment: output.commitment,
    encNote: output.encNote,
    secretMaterial: stranger,
    network: 'test',
    bridge,
  })).toBeNull();
  expect(await scanGhostOutput({
    commitment: output.commitment,
    encNote: output.encNote,
    secretMaterial: recipient,
    network: 'mainnet',
    bridge,
  })).toBeNull();
});

test('ciphertext and commitment tampering fail closed without exposing plaintext', async () => {
  const sender = deriveGhostSecretMaterial(phrase, 'sender');
  const recipient = deriveGhostSecretMaterial(phrase, 'recipient');
  const bridge = testBridge();
  const receiver = await createGhostReceiver(recipient, bridge, 'test');
  const output = await createEncryptedGhostOutput({
    receiver,
    senderOutgoingViewingPublicKey: sender.outgoingViewingPublicKey,
    value: 1n,
    bridge,
  });
  const tamperedCiphertext = output.encNote.slice();
  tamperedCiphertext[tamperedCiphertext.length - 1] ^= 1;
  expect(await recoverOutgoingGhostOutput({
    commitment: output.commitment,
    encNote: tamperedCiphertext,
    secretMaterial: sender,
    network: 'test',
    bridge,
  })).toBeNull();

  const tamperedCommitment = output.commitment.slice();
  tamperedCommitment[0] ^= 1;
  expect(await scanGhostOutput({
    commitment: tamperedCommitment,
    encNote: output.encNote,
    secretMaterial: recipient,
    network: 'test',
    bridge,
  })).toBeNull();
});
