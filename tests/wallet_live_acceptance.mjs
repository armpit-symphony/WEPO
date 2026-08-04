#!/usr/bin/env node
/**
 * Opt-in live acceptance for the shipping self-custody wallet flow.
 *
 * This is deliberately not part of the default unit-test suite. It expects an
 * isolated, disposable test-profile node and gateway, then:
 *   build unsigned -> independently check sighash -> sign locally -> submit
 *   -> wait for confirmation -> verify exact recipient balance delta.
 *
 * No mnemonic or private key is written to the evidence artifact.
 */
import { createHash } from 'node:crypto';
import {
  existsSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  assertStandardSendIntent,
  canonicalSighashHex,
  canonicalTxidHex,
  deriveWepoKeypair,
  signTransaction,
  verifyTransactionInput,
} from '../frontend/src/utils/wepoSigner.js';

const COIN = 100000000;
const SENDER_PHRASE =
  'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';
const RECIPIENT_PHRASE =
  'legal winner thank year wave sausage worth useful legal winner thank yellow';

const args = Object.fromEntries(
  process.argv.slice(2).map((argument) => {
    const separator = argument.indexOf('=');
    if (separator < 0) throw new Error(`Expected --name=value, received: ${argument}`);
    return [argument.slice(0, separator), argument.slice(separator + 1)];
  }),
);

const gatewayUrl = (args['--gateway'] || 'http://127.0.0.1:8001').replace(/\/$/, '');
const nodeUrl = (args['--node'] || 'http://127.0.0.1:18212').replace(/\/$/, '');
const evidencePath = resolve(args['--evidence'] || 'wallet-live-acceptance.json');
const amount = args['--amount'] || '1.23456789';
const fee = args['--fee'] || '0.0001';
const timeoutMs = Number(args['--timeout-ms'] || 60000);

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const webBuild = join(projectRoot, 'frontend', 'build');
const unpackedRoot = process.env.WEPO_DESKTOP_UNPACKED_ROOT
  ? resolve(process.env.WEPO_DESKTOP_UNPACKED_ROOT)
  : join(projectRoot, 'wepo-desktop-wallet', 'dist', 'win-unpacked');
const packedBuild = join(unpackedRoot, 'resources', 'frontend');
const packedExecutable = join(unpackedRoot, 'WEPO Wallet.exe');

const sha256File = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
const findMainBundle = (root) => {
  const directory = join(root, 'static', 'js');
  const matches = readdirSync(directory).filter(
    (candidate) => /^main\.[A-Za-z0-9_-]+\.js$/.test(candidate),
  );
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one canonical main bundle under ${directory}`);
  }
  return join(directory, matches[0]);
};

const requestJson = async (url, options = {}) => {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${options.method || 'GET'} ${url} failed (${response.status}): ${JSON.stringify(payload)}`);
  }
  return payload;
};

const sleep = (milliseconds) => new Promise((resolvePromise) => {
  setTimeout(resolvePromise, milliseconds);
});

const amountAtomic = (decimal) => {
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?$/.test(decimal)) {
    throw new Error(`Non-canonical decimal: ${decimal}`);
  }
  const [whole, fraction = ''] = decimal.split('.');
  return (BigInt(whole) * BigInt(COIN))
    + BigInt((fraction + '00000000').slice(0, 8));
};

const sender = deriveWepoKeypair(SENDER_PHRASE);
const recipient = deriveWepoKeypair(RECIPIENT_PHRASE);
const amountAtoms = amountAtomic(amount);
const feeAtoms = amountAtomic(fee);

const webIndex = join(webBuild, 'index.html');
const packedIndex = join(packedBuild, 'index.html');
const webMain = findMainBundle(webBuild);
const packedMain = findMainBundle(packedBuild);
if (!existsSync(packedIndex)) throw new Error('Packed Electron frontend is missing');
if (!existsSync(packedExecutable)) throw new Error('Packed Electron executable is missing');

const packageEvidence = {
  web_index_sha256: sha256File(webIndex),
  executable_sha256: sha256File(packedExecutable),
  packed_index_sha256: sha256File(packedIndex),
  web_main_sha256: sha256File(webMain),
  packed_main_sha256: sha256File(packedMain),
};
if (packageEvidence.web_index_sha256 !== packageEvidence.packed_index_sha256) {
  throw new Error('Packed index.html differs from the validated web build');
}
if (packageEvidence.web_main_sha256 !== packageEvidence.packed_main_sha256) {
  throw new Error('Packed main JavaScript differs from the validated web build');
}

const networkBefore = await requestJson(`${nodeUrl}/api/network/status`);
if (networkBefore.network_profile !== 'test') {
  throw new Error(`Live acceptance refuses non-test profile: ${networkBefore.network_profile}`);
}

const senderBefore = await requestJson(`${nodeUrl}/api/wallet/${sender.address}`);
const recipientBefore = await requestJson(`${nodeUrl}/api/wallet/${recipient.address}`);
if (amountAtomic(String(senderBefore.spendable_balance)) < amountAtoms + feeAtoms) {
  throw new Error('Deterministic test sender is not sufficiently funded');
}

const buildRequest = {
  from_address: sender.address,
  to_address: recipient.address,
  amount,
  fee,
};
const unsigned = await requestJson(`${gatewayUrl}/api/transaction/build-unsigned`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(buildRequest),
});

const recomputedSighash = canonicalSighashHex(unsigned.unsigned_tx, unsigned.network);
if (recomputedSighash !== unsigned.sighash) {
  throw new Error('Gateway/node sighash differs from the shipping wallet recomputation');
}
assertStandardSendIntent(unsigned.unsigned_tx, {
  senderAddress: sender.address,
  recipientAddress: recipient.address,
  amountAtomic: amountAtoms,
  feeAtomic: feeAtoms,
});

const signedTx = signTransaction(
  unsigned.unsigned_tx,
  sender.secretKey,
  sender.publicKey,
  unsigned.sighash,
  unsigned.network,
);
const clientVerifiedInputs = signedTx.inputs.map(
  (_input, index) => verifyTransactionInput(signedTx, index, unsigned.network),
);
if (!clientVerifiedInputs.every(Boolean)) {
  throw new Error('Shipping wallet failed to verify one of its own signed inputs');
}
const localTxid = canonicalTxidHex(signedTx);

const submission = await requestJson(`${gatewayUrl}/api/transaction/send`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ signed_tx: signedTx }),
});
const txid = submission.tx_hash || submission.transaction_id || submission.txid;
if (!txid) throw new Error(`Gateway response omitted transaction id: ${JSON.stringify(submission)}`);
if (String(txid).toLowerCase() !== localTxid) {
  throw new Error('Gateway/node transaction ID differs from the locally signed transaction');
}

const deadline = Date.now() + timeoutMs;
let transaction = null;
while (Date.now() < deadline) {
  try {
    transaction = await requestJson(`${nodeUrl}/api/tx/${txid}`);
    if (Number(transaction.confirmations || 0) >= 1) break;
  } catch {
    // The transaction may briefly be between admission and lookup.
  }
  await sleep(500);
}
if (!transaction || Number(transaction.confirmations || 0) < 1) {
  throw new Error(`Transaction ${txid} did not confirm within ${timeoutMs} ms`);
}

const senderAfter = await requestJson(`${nodeUrl}/api/wallet/${sender.address}`);
const recipientAfter = await requestJson(`${nodeUrl}/api/wallet/${recipient.address}`);
const networkAfter = await requestJson(`${nodeUrl}/api/network/status`);
const recipientDelta = amountAtomic(String(recipientAfter.balance))
  - amountAtomic(String(recipientBefore.balance));
if (recipientDelta !== amountAtoms) {
  throw new Error(
    `Recipient balance delta ${recipientDelta} did not equal ${amountAtoms} atomic units`,
  );
}

const evidence = {
  schema: 'wepo-wallet-live-acceptance-v2',
  generated_at: new Date().toISOString(),
  network_profile: networkAfter.network_profile,
  gateway_url: gatewayUrl,
  node_url: nodeUrl,
  sender_address: sender.address,
  recipient_address: recipient.address,
  amount,
  amount_atomic: amountAtoms.toString(),
  fee,
  fee_atomic: feeAtoms.toString(),
  build_request: buildRequest,
  gateway_submission: {
    success: submission.success === true,
    source: submission.source,
  },
  intent_bound_before_signing: true,
  local_txid: localTxid,
  txid,
  confirmations: Number(transaction.confirmations),
  confirmed_height: transaction.block_height ?? transaction.height ?? null,
  node_height_before: networkBefore.height,
  node_height_after: networkAfter.height,
  sender_balance_before: String(senderBefore.balance),
  sender_balance_after: String(senderAfter.balance),
  recipient_balance_before: String(recipientBefore.balance),
  recipient_balance_after: String(recipientAfter.balance),
  recipient_delta_atomic: recipientDelta.toString(),
  wallet_recomputed_sighash: recomputedSighash,
  client_verified_inputs: clientVerifiedInputs,
  private_key_exported: false,
  mnemonic_exported: false,
  package_evidence: packageEvidence,
};

writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, {
  encoding: 'utf8',
  flag: 'wx',
});

console.log(`PASS live client-signed send confirmed: ${txid}`);
console.log(`Evidence: ${evidencePath}`);
