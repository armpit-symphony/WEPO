#!/usr/bin/env node
// Generate the public protocol-v3 validator-signer vector from the independent
// state-transition fixture. No validator private key is read or emitted.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';


const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.join(here, 'vectors', 'state_transition_oracle_v1.json');
const sourceBytes = fs.readFileSync(sourcePath);
const fixture = JSON.parse(sourceBytes.toString('utf8'));
const scenario = fixture.pos_scenario;
const candidate = scenario.candidate;
const header = candidate.header;

function u32(value) {
  const output = Buffer.alloc(4);
  output.writeUInt32LE(value);
  return output;
}

function u64(value) {
  const output = Buffer.alloc(8);
  output.writeBigUInt64LE(BigInt(value));
  return output;
}

function lengthPrefixed(value) {
  return Buffer.concat([u32(value.length), value]);
}

const canonicalHeader = Buffer.concat([
  Buffer.from('WEPO_BLOCK_HEADER_V2\0', 'ascii'),
  u32(header.version),
  Buffer.from(header.prev_hash, 'hex'),
  Buffer.from(header.merkle_root, 'hex'),
  u64(header.timestamp),
  u32(header.bits),
  u32(header.nonce),
  lengthPrefixed(Buffer.from(header.consensus_type, 'ascii')),
  lengthPrefixed(Buffer.from(header.validator_address, 'ascii')),
  lengthPrefixed(Buffer.from(header.validator_public_key, 'hex')),
  lengthPrefixed(Buffer.alloc(0)),
]);
const network = Buffer.from(scenario.parameters.network_name, 'ascii');
const signingPayload = Buffer.concat([
  Buffer.from('WEPO_POS_BLOCK_SIGNATURE_V1\0', 'ascii'),
  lengthPrefixed(network),
  u64(candidate.height),
  canonicalHeader,
]);
const message = crypto.createHash('sha3-256').update(signingPayload).digest('hex');
if (message !== scenario.expected.signing_message_hex) {
  throw new Error('derived signer message differs from the state-transition fixture');
}

const vector = {
  schema: 'wepo-validator-signer-protocol-v3',
  test_only: true,
  source_fixture: 'state_transition_oracle_v1.json',
  source_fixture_sha256: crypto.createHash('sha256').update(sourceBytes).digest('hex'),
  request: {
    version: 3,
    operation: 'sign',
    validator_address: header.validator_address,
    network: scenario.parameters.network_name,
    block_height: candidate.height,
    previous_block_hash: header.prev_hash,
    message,
    signing_payload: signingPayload.toString('hex'),
  },
  response: {
    version: 3,
    ok: true,
    signature: scenario.expected.validator_signature,
  },
  expected: {
    validator_public_key: scenario.expected.validator_public_key,
    candidate_hash: scenario.expected.candidate_hash,
    signing_payload_sha256: crypto.createHash('sha256').update(signingPayload).digest('hex'),
  },
};

const serialized = `${JSON.stringify(vector, null, 2)}\n`;
if (process.argv.includes('--write')) {
  const outputPath = path.join(here, 'vectors', 'validator_signer_protocol_v3.json');
  fs.writeFileSync(outputPath, serialized, 'utf8');
  process.stdout.write(`Wrote ${outputPath}\n`);
} else {
  process.stdout.write(serialized);
}
