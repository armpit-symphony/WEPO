#!/usr/bin/env node
/** Verify that retained live-wallet evidence survives a node restart. */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const args = Object.fromEntries(
  process.argv.slice(2).map((argument) => {
    const separator = argument.indexOf('=');
    if (separator < 0) throw new Error(`Expected --name=value, received: ${argument}`);
    return [argument.slice(0, separator), argument.slice(separator + 1)];
  }),
);

const nodeUrl = (args['--node'] || 'http://127.0.0.1:18212').replace(/\/$/, '');
const evidencePath = resolve(args['--evidence'] || 'wallet-live-acceptance.json');
const outputPath = resolve(args['--output'] || 'wallet-live-restart-evidence.json');
const evidenceBytes = readFileSync(evidencePath);
const prior = JSON.parse(evidenceBytes.toString('utf8'));

if (![
  'wepo-wallet-live-acceptance-v1',
  'wepo-wallet-live-acceptance-v2',
].includes(prior.schema)) {
  throw new Error(`Unexpected prior evidence schema: ${prior.schema}`);
}
if (prior.schema === 'wepo-wallet-live-acceptance-v2'
    && prior.local_txid !== prior.txid) {
  throw new Error('Prior evidence did not bind the node txid to the local txid');
}

const requestJson = async (url) => {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`GET ${url} failed (${response.status}): ${JSON.stringify(payload)}`);
  }
  return payload;
};

const decimalToAtomic = (decimal) => {
  const text = String(decimal);
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?$/.test(text)) {
    throw new Error(`Non-canonical decimal in restart response: ${text}`);
  }
  const [whole, fraction = ''] = text.split('.');
  return (BigInt(whole) * 100000000n)
    + BigInt((fraction + '00000000').slice(0, 8));
};

const network = await requestJson(`${nodeUrl}/api/network/status`);
const transaction = await requestJson(`${nodeUrl}/api/tx/${prior.txid}`);
const recipient = await requestJson(
  `${nodeUrl}/api/wallet/${prior.recipient_address}`,
);

if (network.network_profile !== 'test') {
  throw new Error(`Restart verification refuses non-test profile: ${network.network_profile}`);
}
if (network.background_mining_enabled !== false) {
  throw new Error('Restart verification requires background mining to be disabled');
}
if (transaction.txid !== prior.txid) throw new Error('Restarted node returned a different txid');
if (transaction.block_height !== prior.confirmed_height) {
  throw new Error('Confirmed transaction moved to a different block after restart');
}
if (Number(transaction.confirmations || 0) < Number(prior.confirmations || 0)) {
  throw new Error('Confirmed transaction lost confirmations after restart');
}
if (decimalToAtomic(recipient.balance) !== BigInt(prior.amount_atomic)) {
  throw new Error('Recipient balance did not survive restart exactly');
}

const restartEvidence = {
  schema: 'wepo-wallet-live-restart-evidence-v2',
  generated_at: new Date().toISOString(),
  source_evidence_sha256: createHash('sha256').update(evidenceBytes).digest('hex'),
  node_url: nodeUrl,
  network_profile: network.network_profile,
  background_mining_enabled: network.background_mining_enabled,
  reopened_height: network.height,
  reopened_tip: network.best_block_hash,
  txid: transaction.txid,
  confirmed_height: transaction.block_height,
  confirmations_after_restart: Number(transaction.confirmations),
  recipient_address: prior.recipient_address,
  recipient_balance_after_restart: String(recipient.balance),
  recipient_balance_atomic_after_restart: decimalToAtomic(recipient.balance).toString(),
  expected_recipient_balance_atomic: prior.amount_atomic,
};

writeFileSync(outputPath, `${JSON.stringify(restartEvidence, null, 2)}\n`, {
  encoding: 'utf8',
  flag: 'wx',
});

console.log(`PASS confirmed transaction survived restart: ${transaction.txid}`);
console.log(`Evidence: ${outputPath}`);
