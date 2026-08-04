#!/usr/bin/env node
// Independent transparent-state replay oracle for a committed WEPO block fixture.
import { createHash } from 'node:crypto';
import { argon2id } from '../frontend/node_modules/@noble/hashes/argon2.js';
import { ml_dsa44 } from '../frontend/node_modules/@noble/post-quantum/ml-dsa.js';
import { readFileSync } from 'node:fs';
import {
  canonicalSighashMaterialHex,
  canonicalTransactionMaterialHex,
  deriveAddressFromHex,
  verifyTransactionInput,
} from '../frontend/src/utils/wepoSigner.js';

const STATE_DOMAIN = Buffer.from('WEPO_STATE_ORACLE_V1\u0000', 'ascii');
const SIGNING_NETWORK = 'test';

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function sha256Hex(value) {
  return createHash('sha256').update(value).digest('hex');
}

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
    lengthPrefixed(Buffer.from(
      includeValidatorSignature ? header.validator_signature || '' : '', 'hex',
    )),
  ]);
}


const POW_PARAMETERS = Object.freeze({
  algorithm: 'argon2id-v19',
  time_cost: 3,
  memory_cost_kib: 4096,
  parallelism: 1,
  hash_length: 32,
  salt_length: 16,
  salt_domain: 'WEPO_POW_SALT',
  timestamp_bits: 64,
});

function powInput(header) {
  return Buffer.concat([
    uint32LE(header.version),
    Buffer.from(header.prev_hash, 'hex'),
    Buffer.from(header.merkle_root, 'hex'),
    uint64LE(header.timestamp),
    uint32LE(header.bits),
    uint32LE(header.nonce),
    Buffer.from(header.consensus_type, 'ascii'),
  ]);
}

function calculatePowHash(header) {
  const input = powInput(header);
  const salt = createHash('sha256')
    .update(Buffer.concat([Buffer.from(POW_PARAMETERS.salt_domain, 'ascii'), input]))
    .digest()
    .subarray(0, POW_PARAMETERS.salt_length);
  const derived = argon2id(input, salt, {
    t: POW_PARAMETERS.time_cost,
    m: POW_PARAMETERS.memory_cost_kib,
    p: POW_PARAMETERS.parallelism,
    version: 0x13,
    dkLen: POW_PARAMETERS.hash_length,
  });
  return sha256Hex(Buffer.from(derived));
}

function validatePowConfiguration(actual) {
  assert(canonicalJson(actual) === canonicalJson(POW_PARAMETERS), 'unexpected PoW parameters');
}

const DIFFICULTY_PARAMETERS = Object.freeze({
  window_pow_headers: 10,
  lower_ratio_numerator: 3,
  lower_ratio_denominator: 4,
  upper_ratio_numerator: 5,
  upper_ratio_denominator: 4,
  block_time_initial: 15,
  block_time_pow_hybrid: 20,
  total_initial_blocks: 12,
  minimum_bits: 1,
});

function expectedDifficulty(headers, currentHeight) {
  const powHeaders = headers.filter(
    (header) => header.consensus_type === 'pow',
  );
  assert(powHeaders.length > 0, 'difficulty vector has no PoW headers');
  const base = Math.max(
    DIFFICULTY_PARAMETERS.minimum_bits,
    powHeaders[powHeaders.length - 1].bits,
  );
  if (powHeaders.length < DIFFICULTY_PARAMETERS.window_pow_headers) {
    return base;
  }

  const recent = powHeaders.slice(-DIFFICULTY_PARAMETERS.window_pow_headers);
  let elapsed = 0;
  for (let index = 1; index < recent.length; index += 1) {
    elapsed += recent[index].timestamp - recent[index - 1].timestamp;
  }
  const intervals = recent.length - 1;
  const target = currentHeight + 1 <= DIFFICULTY_PARAMETERS.total_initial_blocks
    ? DIFFICULTY_PARAMETERS.block_time_initial
    : DIFFICULTY_PARAMETERS.block_time_pow_hybrid;
  const scaledElapsed = elapsed * DIFFICULTY_PARAMETERS.lower_ratio_denominator;

  if (
    scaledElapsed
    < target * DIFFICULTY_PARAMETERS.lower_ratio_numerator * intervals
  ) {
    return base + 1;
  }
  if (
    scaledElapsed
    > target * DIFFICULTY_PARAMETERS.upper_ratio_numerator * intervals
  ) {
    return Math.max(DIFFICULTY_PARAMETERS.minimum_bits, base - 1);
  }
  return base;
}

function validateDifficultyVectors(difficulty) {
  assert(
    canonicalJson(difficulty.parameters) === canonicalJson(DIFFICULTY_PARAMETERS),
    'unexpected difficulty parameters',
  );
  assert(difficulty.cases.length >= 7, 'insufficient difficulty vectors');
  for (const vector of difficulty.cases) {
    assert(
      expectedDifficulty(vector.headers, vector.current_height)
        === vector.expected_next_bits,
      `difficulty vector failed: ${vector.name}`,
    );
  }
}
function pythonStringCompare(left, right) {
  const a = Array.from(left, (character) => character.codePointAt(0));
  const b = Array.from(right, (character) => character.codePointAt(0));
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function canonicalJson(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (typeof value === 'object') {
    return `{${Object.keys(value)
      .sort(pythonStringCompare)
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function isCoinbase(transaction) {
  return (
    transaction.inputs.length === 1
    && transaction.inputs[0].prev_txid === '0'.repeat(64)
    && transaction.inputs[0].prev_vout === 0xffffffff
  );
}

function merkleRoot(txids) {
  if (txids.length === 0) return '0'.repeat(64);
  let level = [...txids];
  while (level.length > 1) {
    const next = [];
    for (let index = 0; index < level.length; index += 2) {
      const left = level[index];
      const right = level[index + 1] || left;
      next.push(sha256Hex(Buffer.from(left + right, 'ascii')));
    }
    level = next;
  }
  return level[0];
}

function outpoint(txid, vout) {
  return `${txid}:${vout}`;
}

function validateOutput(output, context) {
  assert(Number.isSafeInteger(output.value) && output.value >= 0, `${context}: invalid value`);
  assert(typeof output.address === 'string' && output.address.length > 0, `${context}: invalid address`);
  assert(typeof output.script_pubkey === 'string', `${context}: invalid script`);
}

function applyBlock(block, state, coinbaseMaturity) {
  assert(block.transactions.length > 0, `block ${block.height}: empty transaction list`);
  assert(isCoinbase(block.transactions[0]), `block ${block.height}: first transaction is not coinbase`);
  assert(
    block.transactions.slice(1).every((transaction) => !isCoinbase(transaction)),
    `block ${block.height}: multiple coinbase transactions`,
  );

  const txids = block.transactions.map(
    (transaction) => canonicalTransactionMaterialHex(transaction).txid,
  );
  assert(
    merkleRoot(txids) === block.header.merkle_root,
    `block ${block.height}: Merkle root mismatch`,
  );

  for (let txIndex = 0; txIndex < block.transactions.length; txIndex += 1) {
    const transaction = block.transactions[txIndex];
    const txid = txids[txIndex];
    assert(!state.transactionIds.has(txid), `duplicate transaction ${txid}`);

    if (!isCoinbase(transaction)) {
      const seenInputs = new Set();
      const consumed = [];
      let inputTotal = 0;
      for (let inputIndex = 0; inputIndex < transaction.inputs.length; inputIndex += 1) {
        const input = transaction.inputs[inputIndex];
        const key = outpoint(input.prev_txid, input.prev_vout);
        assert(!seenInputs.has(key), `transaction ${txid}: duplicate input ${key}`);
        seenInputs.add(key);
        const utxo = state.utxos.get(key);
        assert(utxo, `transaction ${txid}: missing UTXO ${key}`);
        if (utxo.is_coinbase) {
          assert(
            block.height - utxo.created_height >= coinbaseMaturity,
            `transaction ${txid}: immature coinbase ${key}`,
          );
        }
        assert(input.script_sig === '', `transaction ${txid}: script_sig must be empty`);
        assert(
          deriveAddressFromHex(input.quantum_public_key) === utxo.address,
          `transaction ${txid}: signing key does not own ${key}`,
        );
        assert(
          verifyTransactionInput(transaction, inputIndex, SIGNING_NETWORK),
          `transaction ${txid}: invalid ML-DSA signature`,
        );
        inputTotal += utxo.amount;
        consumed.push(key);
      }

      let outputTotal = 0;
      transaction.outputs.forEach((output, outputIndex) => {
        validateOutput(output, `transaction ${txid} output ${outputIndex}`);
        outputTotal += output.value;
      });
      const valueBalance = transaction.shielded_bundle?.value_balance ?? 0;
      assert(
        Number.isSafeInteger(valueBalance),
        `transaction ${txid}: unsafe shielded value balance`,
      );
      assert(
        inputTotal - outputTotal - valueBalance === transaction.fee,
        `transaction ${txid}: fee/value conservation mismatch`,
      );
      consumed.forEach((key) => state.utxos.delete(key));
    } else {
      transaction.outputs.forEach((output, outputIndex) => {
        validateOutput(output, `coinbase ${txid} output ${outputIndex}`);
      });
    }

    transaction.outputs.forEach((output, vout) => {
      const key = outpoint(txid, vout);
      assert(!state.utxos.has(key), `duplicate UTXO ${key}`);
      state.utxos.set(key, {
        txid,
        vout,
        address: output.address,
        amount: output.value,
        script_pubkey: output.script_pubkey.toLowerCase(),
        created_height: block.height,
        is_coinbase: isCoinbase(transaction),
      });
    });
    state.transactionIds.add(txid);
  }
  return txids;
}

function sortedUtxos(state) {
  return [...state.utxos.values()].sort(
    (left, right) => left.txid.localeCompare(right.txid) || left.vout - right.vout,
  );
}

function branchScore(blocks) {
  let powWork = 0n;
  let posBlocks = 0;
  for (const block of blocks) {
    if (block.header.consensus_type === 'pow') {
      assert(
        Number.isInteger(block.header.bits) && block.header.bits >= 0,
        `block ${block.height}: invalid work bits`,
      );
      powWork += 1n << (4n * BigInt(block.header.bits));
    } else {
      posBlocks += 1;
    }
  }
  return { pow_work: powWork.toString(), pos_blocks: posBlocks };
}

function compareScores(left, right) {
  const powComparison = BigInt(left.pow_work) - BigInt(right.pow_work);
  if (powComparison !== 0n) return powComparison > 0n ? 1 : -1;
  return Math.sign(left.pos_blocks - right.pos_blocks);
}

function replayBranch(blocks, expectedPowHashes, coinbaseMaturity, label) {
  assert(Array.isArray(blocks) && blocks.length > 0, `${label}: empty branch`);
  assert(
    Array.isArray(expectedPowHashes) && expectedPowHashes.length === blocks.length,
    `${label}: PoW hash count mismatch`,
  );
  const state = { utxos: new Map(), transactionIds: new Set() };
  const headers = [];
  const blockHashes = [];
  let previousHash = null;
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    assert(block.height === index, `${label}: non-contiguous height ${block.height}`);
    if (index === 0) {
      assert(
        block.header.prev_hash === '0'.repeat(64),
        `${label}: genesis previous hash is not zero`,
      );
    } else {
      assert(
        block.header.prev_hash === previousHash,
        `${label} block ${index}: broken parent link`,
      );
      assert(
        block.header.timestamp > blocks[index - 1].header.timestamp,
        `${label} block ${index}: non-monotonic timestamp`,
      );
    }

    const blockHash = sha256Hex(canonicalHeaderBytes(block.header));
    if (block.header.consensus_type === 'pow') {
      if (index === 0) {
        assert(
          block.header.bits === DIFFICULTY_PARAMETERS.minimum_bits,
          `${label}: unexpected genesis difficulty`,
        );
      } else {
        const expectedBits = expectedDifficulty(headers, block.height - 1);
        assert(
          block.header.bits === expectedBits,
          `${label} block ${index}: live difficulty mismatch; got ${block.header.bits}, expected ${expectedBits}`,
        );
      }
      const powHash = calculatePowHash(block.header);
      assert(
        powHash === expectedPowHashes[index],
        `${label} block ${index}: cross-runtime PoW hash mismatch`,
      );
      assert(
        powHash.startsWith('0'.repeat(block.header.bits)),
        `${label} block ${index}: proof of work misses its difficulty target`,
      );
    } else {
      assert(block.header.bits === 0, `${label} block ${index}: PoS bits must be zero`);
    }

    applyBlock(block, state, coinbaseMaturity);
    headers.push(block.header);
    blockHashes.push(blockHash);
    previousHash = blockHash;
  }

  const rows = sortedUtxos(state);
  const payload = Buffer.from(canonicalJson(rows), 'utf8');
  const commitment = sha256Hex(Buffer.concat([
    STATE_DOMAIN,
    uint32LE(payload.length),
    payload,
  ]));
  const total = rows.reduce((sum, row) => sum + row.amount, 0);
  return {
    blocks,
    blockHashes,
    rows,
    payload,
    commitment,
    total,
    height: blocks.length - 1,
    tip: previousHash,
    score: branchScore(blocks),
  };
}

function validateExpectedBranch(actual, expected, label) {
  assert(expected.height === actual.height, `${label}: expected height mismatch`);
  assert(actual.tip === expected.tip, `${label}: tip mismatch`);
  assert(actual.total === expected.utxo_total, `${label}: UTXO total mismatch`);
  const shieldedPoolBalance = expected.shielded_pool_balance ?? 0;
  assert(
    actual.total + shieldedPoolBalance === expected.issued_supply,
    `${label}: issued supply mismatch`,
  );
  assert(
    canonicalJson(actual.rows) === canonicalJson(expected.utxos),
    `${label}: UTXO set mismatch`,
  );
  assert(
    actual.payload.toString('hex') === expected.state_payload_utf8_hex,
    `${label}: state payload mismatch`,
  );
  assert(
    actual.commitment === expected.state_commitment,
    `${label}: state commitment mismatch`,
  );
  if (expected.score !== undefined) {
    assert(
      canonicalJson(actual.score) === canonicalJson(expected.score),
      `${label}: branch score mismatch`,
    );
  }
}

function commonAncestorHeight(results) {
  const commonLength = Math.min(...results.map((result) => result.blockHashes.length));
  let height = -1;
  for (let index = 0; index < commonLength; index += 1) {
    const candidate = results[0].blockHashes[index];
    if (!results.every((result) => result.blockHashes[index] === candidate)) break;
    height = index;
  }
  return height;
}

function validateForkChoice(forkChoice, coinbaseMaturity) {
  const expectedParameters = {
    pow_work: '2^(4*bits)',
    branch_order: 'pow_work_then_pos_count',
    activation_height: 12,
    pre_pos_pow_reward: 5251141552,
    phase_2a_end_height: 30,
    phase_2a_pow_reward: 3317000000,
    rwa_creation_min_fee: 10000,
    messaging_key_register_min_fee: 10000,
    ml_kem768_public_key_hex_length: 2368,
    ml_dsa44_public_key_hex_length: 2624,
    metadata_fee_policy: 'fully_redistributed_via_coinbase',
  };
  assert(
    canonicalJson(forkChoice.parameters) === canonicalJson(expectedParameters),
    'unexpected fork-choice parameters',
  );
  assert(
    Array.isArray(forkChoice.branches) && forkChoice.branches.length === 2,
    'fork choice must contain exactly two branches',
  );
  const names = new Set(forkChoice.branches.map((branch) => branch.name));
  assert(names.size === forkChoice.branches.length, 'fork branch names must be unique');

  const candidates = forkChoice.branches.map((branch) => {
    const result = replayBranch(
      branch.blocks,
      branch.expected.pow_hashes,
      coinbaseMaturity,
      `fork ${branch.name}`,
    );
    validateExpectedBranch(result, branch.expected, `fork ${branch.name}`);
    const metadataIndexes = deriveMetadataIndexes(branch.blocks, forkChoice.parameters);
    assert(
      canonicalJson(metadataIndexes.rwaAssets) === canonicalJson(branch.expected.rwa_assets),
      `fork ${branch.name}: RWA index mismatch`,
    );
    assert(
      canonicalJson(metadataIndexes.messagingKeys)
        === canonicalJson(branch.expected.messaging_keys),
      `fork ${branch.name}: messaging index mismatch`,
    );
    assert(
      metadataIndexes.metadataFeeTotal === metadataIndexes.metadataFeeRedistributedTotal,
      `fork ${branch.name}: metadata fees were not conserved`,
    );
    return { name: branch.name, result, metadataIndexes };
  });
  const ancestorHeight = commonAncestorHeight(candidates.map((candidate) => candidate.result));
  assert(
    ancestorHeight === forkChoice.expected.common_ancestor_height,
    'fork common-ancestor mismatch',
  );

  const comparison = compareScores(candidates[0].result.score, candidates[1].result.score);
  assert(comparison !== 0, 'fixture fork branches have equal scores');
  const winner = comparison > 0 ? candidates[0] : candidates[1];
  const loser = comparison > 0 ? candidates[1] : candidates[0];
  assert(winner.name === forkChoice.expected.winner, 'fork winner mismatch');
  assert(loser.name === forkChoice.expected.loser, 'fork loser mismatch');
  assert(
    Array.isArray(forkChoice.expected.python_adoption_results)
      && forkChoice.expected.python_adoption_results.at(-1) === true
      && forkChoice.expected.python_adoption_results.slice(0, -1).every((value) => value === false),
    'Python adoption evidence has an unexpected shape',
  );
  assert(
    forkChoice.expected.losing_tip_preserved_noncanonical === true,
    'Python losing-tip preservation evidence is missing',
  );
  assert(
    winner.result.height === forkChoice.expected.canonical_height,
    'fork canonical height mismatch',
  );
  assert(winner.result.tip === forkChoice.expected.canonical_tip, 'fork canonical tip mismatch');
  assert(
    winner.result.total === forkChoice.expected.canonical_issued_supply,
    'fork canonical supply mismatch',
  );
  assert(
    canonicalJson(winner.result.rows) === canonicalJson(forkChoice.expected.canonical_utxos),
    'fork canonical UTXO mismatch',
  );
  assert(
    winner.result.payload.toString('hex')
      === forkChoice.expected.canonical_state_payload_utf8_hex,
    'fork canonical state payload mismatch',
  );
  assert(
    winner.result.commitment === forkChoice.expected.canonical_state_commitment,
    'fork canonical state commitment mismatch',
  );
  assert(
    canonicalJson(winner.metadataIndexes.rwaAssets)
      === canonicalJson(forkChoice.expected.canonical_rwa_assets),
    'fork canonical RWA index mismatch',
  );
  assert(
    canonicalJson(winner.metadataIndexes.messagingKeys)
      === canonicalJson(forkChoice.expected.canonical_messaging_keys),
    'fork canonical messaging index mismatch',
  );
  assert(
    canonicalJson(loser.metadataIndexes.rwaAssets)
      !== canonicalJson(winner.metadataIndexes.rwaAssets),
    'fork RWA state did not diverge',
  );
  assert(
    canonicalJson(loser.metadataIndexes.messagingKeys)
      !== canonicalJson(winner.metadataIndexes.messagingKeys),
    'fork messaging state did not diverge',
  );
  assert(
    forkChoice.expected.losing_rwa_assets_removed === true
      && forkChoice.expected.winning_rwa_assets_present === true,
    'Python RWA reorganization evidence is missing',
  );
  assert(
    forkChoice.expected.losing_messaging_keys_replaced === true
      && forkChoice.expected.winning_messaging_keys_selected === true,
    'Python messaging reorganization evidence is missing',
  );
  return winner;
}
function validateShieldedScenario(scenario, coinbaseMaturity) {
  const expectedParameters = {
    activation_height: 1,
    merkle_depth: 32,
    anchor_window: 100,
    maximum_spends: 4,
    maximum_outputs: 2,
    maximum_proof_bytes: 1048576,
    pool_hash: 'rescue-rp64-256',
    node_hash_domain: 2,
    empty_leaf_domain: 1,
    bundle_statement_tag: 'WEPO-Shielded-BundleStatement-v1',
    proof_evidence:
      'state-machine test double; real proof validity is covered by test_ghost_verifier_integration.py',
  };
  assert(
    canonicalJson(scenario.parameters) === canonicalJson(expectedParameters),
    'unexpected shielded scenario parameters',
  );
  const replayed = replayBranch(
    scenario.blocks,
    scenario.expected.pow_hashes,
    coinbaseMaturity,
    'shielded scenario',
  );
  validateExpectedBranch(replayed, scenario.expected, 'shielded scenario');

  const commitments = [];
  const nullifiers = [];
  const transactionIds = [];
  const sighashes = [];
  const knownAnchors = new Set();
  const seenNullifiers = new Set();
  let position = 0;
  let poolBalance = 0;

  const expectedAnchorByHeight = new Map(
    scenario.expected.anchors.map((row) => [row.block_height, row.anchor]),
  );
  for (const block of scenario.blocks) {
    for (const transaction of block.transactions) {
      const bundle = transaction.shielded_bundle;
      if (!bundle) continue;
      assert(
        block.height >= scenario.parameters.activation_height,
        `shielded transaction before activation at height ${block.height}`,
      );
      assert(
        Array.isArray(bundle.spends)
          && bundle.spends.length <= scenario.parameters.maximum_spends,
        `shielded transaction at height ${block.height}: invalid spend count`,
      );
      assert(
        Array.isArray(bundle.outputs)
          && bundle.outputs.length <= scenario.parameters.maximum_outputs,
        `shielded transaction at height ${block.height}: invalid output count`,
      );
      assert(
        bundle.spends.length > 0 || bundle.outputs.length > 0,
        `shielded transaction at height ${block.height}: empty bundle`,
      );
      assert(
        Number.isSafeInteger(bundle.value_balance),
        `shielded transaction at height ${block.height}: unsafe value balance`,
      );
      assert(
        typeof bundle.proof === 'string'
          && bundle.proof.length > 0
          && bundle.proof.length % 2 === 0
          && bundle.proof.length <= scenario.parameters.maximum_proof_bytes * 2
          && /^[0-9a-f]+$/u.test(bundle.proof),
        `shielded transaction at height ${block.height}: invalid proof envelope`,
      );

      const txid = canonicalTransactionMaterialHex(transaction).txid;
      const sighash = canonicalSighashMaterialHex(transaction, SIGNING_NETWORK).digest;
      transactionIds.push(txid);
      sighashes.push(sighash);
      poolBalance += bundle.value_balance;

      const bundleAnchors = new Set();
      bundle.spends.forEach((spend, spendIndex) => {
        assert(
          typeof spend.anchor === 'string'
            && /^[0-9a-f]{64}$/u.test(spend.anchor)
            && typeof spend.nullifier === 'string'
            && /^[0-9a-f]{64}$/u.test(spend.nullifier),
          `shielded spend ${txid}:${spendIndex} has invalid public fields`,
        );
        bundleAnchors.add(spend.anchor);
        assert(
          knownAnchors.has(spend.anchor),
          `shielded spend ${txid}:${spendIndex} references an unknown anchor`,
        );
        assert(
          !seenNullifiers.has(spend.nullifier),
          `shielded spend ${txid}:${spendIndex} reuses a nullifier`,
        );
        seenNullifiers.add(spend.nullifier);
        nullifiers.push({
          nullifier: spend.nullifier,
          block_height: block.height,
          txid,
          spend_index: spendIndex,
        });
      });
      assert(
        bundleAnchors.size <= 1,
        `shielded transaction ${txid} uses multiple anchors`,
      );

      bundle.outputs.forEach((output, outputIndex) => {
        assert(
          typeof output.commitment === 'string'
            && /^[0-9a-f]{64}$/u.test(output.commitment)
            && typeof output.enc_note === 'string'
            && output.enc_note.length % 2 === 0
            && /^[0-9a-f]*$/u.test(output.enc_note),
          `shielded output ${txid}:${outputIndex} has invalid public fields`,
        );
        commitments.push({
          position,
          commitment: output.commitment,
          block_height: block.height,
          txid,
          output_index: outputIndex,
        });
        position += 1;
      });
    }

    if (block.height >= scenario.parameters.activation_height) {
      const anchor = expectedAnchorByHeight.get(block.height);
      assert(
        typeof anchor === 'string' && /^[0-9a-f]{64}$/u.test(anchor),
        `shielded block ${block.height}: missing canonical anchor evidence`,
      );
      knownAnchors.add(anchor);
    }
  }

  assert(
    canonicalJson(commitments) === canonicalJson(scenario.expected.commitments),
    'shielded commitment index mismatch',
  );
  assert(
    canonicalJson(nullifiers) === canonicalJson(scenario.expected.nullifiers),
    'shielded nullifier index mismatch',
  );
  assert(
    canonicalJson(transactionIds) === canonicalJson(scenario.expected.transaction_ids),
    'shielded transaction identity mismatch',
  );
  assert(
    canonicalJson(sighashes) === canonicalJson(scenario.expected.sighashes),
    'shielded canonical sighash mismatch',
  );
  assert(
    scenario.expected.statement_digests.length === transactionIds.length
      && scenario.expected.statement_digests.every(
        (digest) => typeof digest === 'string' && /^[0-9a-f]{64}$/u.test(digest),
      ),
    'shielded statement-digest evidence is malformed',
  );
  assert(
    poolBalance === scenario.expected.shielded_pool_balance,
    'shielded pool balance mismatch',
  );
  const transparentTotal = replayed.rows.reduce((sum, row) => sum + row.amount, 0);
  const supplyDelta = scenario.expected.issued_supply - transparentTotal;
  assert(
    supplyDelta === scenario.expected.supply_minus_transparent_utxo_total
      && supplyDelta === poolBalance,
    'shielded supply reconciliation mismatch',
  );
  assert(
    scenario.expected.tree_root === scenario.expected.anchors.at(-1).anchor,
    'shielded final root/anchor mismatch',
  );

  const disconnectHeight = scenario.expected.disconnect.height;
  assert(
    canonicalJson(
      commitments.filter((row) => row.block_height <= disconnectHeight),
    ) === canonicalJson(scenario.expected.disconnect.commitments),
    'shielded disconnect commitment mismatch',
  );
  assert(
    canonicalJson(
      nullifiers.filter((row) => row.block_height <= disconnectHeight),
    ) === canonicalJson(scenario.expected.disconnect.nullifiers),
    'shielded disconnect nullifier mismatch',
  );
  assert(
    scenario.expected.disconnect.tree_root
      === scenario.expected.disconnect.anchors.at(-1).anchor,
    'shielded disconnect root/anchor mismatch',
  );
  assert(
    scenario.expected.reconnect_restored_exact_state === true,
    'Python shielded reconnect evidence is missing',
  );

  return {
    height: replayed.height,
    tip: replayed.tip,
    treeRoot: scenario.expected.tree_root,
    poolBalance,
    commitments: commitments.length,
    nullifiers: nullifiers.length,
    transactionIds,
    sighashes,
    statementDigests: scenario.expected.statement_digests,
  };
}

function scriptMarker(scriptHex) {
  return Buffer.from(scriptHex, 'hex').toString('utf8');
}

function deriveActiveStakes(blocks, parameters, includeInactive = false) {
  const outputHistory = new Map();
  const stakes = new Map();
  for (const block of blocks) {
    for (const transaction of block.transactions) {
      const txid = canonicalTransactionMaterialHex(transaction).txid;
      if (transaction.tx_type === 'stake_create') {
        assert(
          block.height > parameters.activation_height,
          `stake ${txid}: created before activation`,
        );
        const metadata = transaction.extra_data;
        assert(metadata && typeof metadata === 'object', `stake ${txid}: missing metadata`);
        const stakeId = metadata.stake_id;
        const stakerAddress = metadata.staker_address;
        const amount = metadata.amount;
        assert(typeof stakeId === 'string' && stakeId.length > 0, `stake ${txid}: invalid ID`);
        assert(
          typeof stakerAddress === 'string' && stakerAddress.length > 0,
          `stake ${txid}: invalid address`,
        );
        assert(
          Number.isSafeInteger(amount) && amount >= parameters.minimum_stake_amount,
          `stake ${txid}: amount below minimum`,
        );
        assert(!stakes.has(stakeId), `stake ${txid}: duplicate stake ID`);
        for (const input of transaction.inputs) {
          const previous = outputHistory.get(outpoint(input.prev_txid, input.prev_vout));
          assert(previous, `stake ${txid}: input history is missing`);
          assert(
            previous.address === stakerAddress,
            `stake ${txid}: input is not owned by staker`,
          );
        }

        const marker = `stake_lock:${stakeId}`;
        const lockIndexes = [];
        transaction.outputs.forEach((output, index) => {
          if (scriptMarker(output.script_pubkey) === marker) lockIndexes.push(index);
        });
        assert(lockIndexes.length === 1, `stake ${txid}: canonical lock output mismatch`);
        const lockVout = lockIndexes[0];
        const lockOutput = transaction.outputs[lockVout];
        assert(lockOutput.address === stakerAddress, `stake ${txid}: lock owner mismatch`);
        assert(lockOutput.value === amount, `stake ${txid}: lock amount mismatch`);
        assert(
          transaction.outputs.length === 1 || transaction.outputs.length === 2,
          `stake ${txid}: non-canonical output count`,
        );
        transaction.outputs.forEach((output, index) => {
          if (index === lockVout) return;
          assert(
            output.address === stakerAddress && scriptMarker(output.script_pubkey) === 'change_script',
            `stake ${txid}: non-canonical change output`,
          );
        });
        stakes.set(stakeId, {
          stake_id: stakeId,
          staker_address: stakerAddress,
          amount,
          start_height: block.height,
          start_time: transaction.timestamp || block.header.timestamp,
          last_reward_height: 0,
          total_rewards: 0,
          status: 'active',
          unlock_height: null,
          lock_txid: txid,
          lock_vout: lockVout,
          deactivation_txid: null,
        });
      } else if (transaction.tx_type === 'stake_deactivate') {
        const metadata = transaction.extra_data;
        const stakeId = metadata?.stake_id;
        const stake = stakes.get(stakeId);
        assert(stake?.status === 'active', `stake deactivation ${txid}: unknown active stake`);
        assert(
          metadata.staker_address === stake.staker_address,
          `stake deactivation ${txid}: owner mismatch`,
        );
        assert(
          transaction.inputs.length === 1
            && transaction.inputs[0].prev_txid === stake.lock_txid
            && transaction.inputs[0].prev_vout === stake.lock_vout,
          `stake deactivation ${txid}: lock outpoint mismatch`,
        );
        const previous = outputHistory.get(outpoint(stake.lock_txid, stake.lock_vout));
        assert(previous?.address === stake.staker_address, `stake deactivation ${txid}: lock owner mismatch`);
        assert(transaction.outputs.length === 1, `stake deactivation ${txid}: output count mismatch`);
        const unlock = transaction.outputs[0];
        assert(
          unlock.address === stake.staker_address
            && scriptMarker(unlock.script_pubkey) === 'stake_unlock'
            && unlock.value > 0
            && unlock.value + transaction.fee === stake.amount,
          `stake deactivation ${txid}: principal return mismatch`,
        );
        stake.status = 'inactive';
        stake.unlock_height = block.height;
        stake.deactivation_txid = txid;
      }

      transaction.outputs.forEach((output, vout) => {
        outputHistory.set(outpoint(txid, vout), output);
      });
    }
  }
  return [...stakes.values()]
    .filter((stake) => includeInactive || stake.status === 'active')
    .sort(
      (left, right) => pythonStringCompare(left.staker_address, right.staker_address)
        || pythonStringCompare(left.stake_id, right.stake_id),
    );
}

function deriveMasternodes(blocks, parameters, includeInactive = false) {
  const outputHistory = new Map();
  const masternodes = new Map();
  for (const block of blocks) {
    for (const transaction of block.transactions) {
      const txid = canonicalTransactionMaterialHex(transaction).txid;
      if (transaction.tx_type === 'masternode_create') {
        const metadata = transaction.extra_data;
        assert(metadata && typeof metadata === 'object', `masternode ${txid}: missing metadata`);
        const masternodeId = metadata.masternode_id;
        const operatorAddress = metadata.operator_address;
        const ipAddress = metadata.ip_address;
        const port = metadata.port;
        assert(typeof masternodeId === 'string' && masternodeId.length > 0, `masternode ${txid}: invalid ID`);
        assert(typeof operatorAddress === 'string' && operatorAddress.length > 0, `masternode ${txid}: invalid operator`);
        assert(
          (ipAddress === null || typeof ipAddress === 'string')
            && Number.isSafeInteger(port) && port >= 1 && port <= 65535,
          `masternode ${txid}: invalid endpoint`,
        );
        assert(!masternodes.has(masternodeId), `masternode ${txid}: duplicate ID`);
        assert(transaction.inputs.length >= 1, `masternode ${txid}: missing collateral input`);
        const inputRows = transaction.inputs.map((input) => {
          const previous = outputHistory.get(outpoint(input.prev_txid, input.prev_vout));
          assert(previous, `masternode ${txid}: input history is missing`);
          assert(previous.address === operatorAddress, `masternode ${txid}: input is not owned by operator`);
          return previous;
        });
        const collateralInput = inputRows[0];
        assert(
          collateralInput.value >= parameters.minimum_masternode_collateral,
          `masternode ${txid}: collateral below minimum`,
        );
        const marker = `masternode_lock:${masternodeId}`;
        const lockIndexes = [];
        transaction.outputs.forEach((output, index) => {
          if (scriptMarker(output.script_pubkey) === marker) lockIndexes.push(index);
        });
        assert(lockIndexes.length === 1, `masternode ${txid}: canonical lock output mismatch`);
        const collateralVout = lockIndexes[0];
        const collateralOutput = transaction.outputs[collateralVout];
        const feeFundingValue = inputRows.slice(1).reduce((sum, output) => sum + output.value, 0);
        const expectedChange = feeFundingValue - transaction.fee;
        assert(
          collateralOutput.address === operatorAddress
            && collateralOutput.value === collateralInput.value
            && expectedChange >= 0,
          `masternode ${txid}: collateral preservation mismatch`,
        );
        assert(
          transaction.outputs.length === (expectedChange > 0 ? 2 : 1),
          `masternode ${txid}: non-canonical output count`,
        );
        transaction.outputs.forEach((output, index) => {
          if (index === collateralVout) return;
          assert(
            output.address === operatorAddress
              && scriptMarker(output.script_pubkey) === 'change_script'
              && output.value === expectedChange,
            `masternode ${txid}: non-canonical fee change`,
          );
        });
        masternodes.set(masternodeId, {
          masternode_id: masternodeId,
          operator_address: operatorAddress,
          collateral_txid: txid,
          collateral_vout: collateralVout,
          ip_address: ipAddress,
          port,
          start_height: block.height,
          start_time: transaction.timestamp || block.header.timestamp,
          last_ping: 0,
          status: 'active',
          total_rewards: 0,
          deactivation_txid: null,
        });
      } else if (transaction.tx_type === 'masternode_deactivate') {
        const metadata = transaction.extra_data;
        const masternodeId = metadata?.masternode_id;
        const masternode = masternodes.get(masternodeId);
        assert(masternode?.status === 'active', `masternode deactivation ${txid}: unknown active masternode`);
        assert(metadata.operator_address === masternode.operator_address, `masternode deactivation ${txid}: operator mismatch`);
        assert(
          transaction.inputs.length === 1
            && transaction.inputs[0].prev_txid === masternode.collateral_txid
            && transaction.inputs[0].prev_vout === masternode.collateral_vout,
          `masternode deactivation ${txid}: collateral outpoint mismatch`,
        );
        const previous = outputHistory.get(outpoint(masternode.collateral_txid, masternode.collateral_vout));
        assert(previous?.address === masternode.operator_address, `masternode deactivation ${txid}: collateral owner mismatch`);
        assert(transaction.outputs.length === 1, `masternode deactivation ${txid}: output count mismatch`);
        const unlock = transaction.outputs[0];
        assert(
          unlock.address === masternode.operator_address
            && scriptMarker(unlock.script_pubkey) === 'masternode_unlock'
            && unlock.value > 0
            && unlock.value + transaction.fee === previous.value,
          `masternode deactivation ${txid}: collateral return mismatch`,
        );
        masternode.status = 'inactive';
        masternode.deactivation_txid = txid;
      }
      transaction.outputs.forEach((output, vout) => {
        outputHistory.set(outpoint(txid, vout), output);
      });
    }
  }
  return [...masternodes.values()]
    .filter((masternode) => includeInactive || masternode.status === 'active')
    .sort((left, right) => pythonStringCompare(left.masternode_id, right.masternode_id));
}

function deriveMetadataIndexes(blocks, parameters) {
  const outputHistory = new Map();
  const rwaAssets = new Map();
  const messagingKeys = new Map();
  const metadataFeeBlocks = [];
  const messagingRegistrationTxids = [];
  let rwaCreateTxid = null;

  for (const block of blocks) {
    const blockMetadataTransactions = [];
    for (const transaction of block.transactions) {
      const txid = canonicalTransactionMaterialHex(transaction).txid;
      const metadata = transaction.extra_data;
      if (transaction.tx_type === 'rwa_create') {
        assert(metadata && typeof metadata === 'object', `RWA ${txid}: missing metadata`);
        const assetId = metadata.asset_id;
        const ownerAddress = metadata.owner_address;
        const assetHash = metadata.asset_hash;
        assert(typeof assetId === 'string' && assetId.length > 0, `RWA ${txid}: invalid asset ID`);
        assert(typeof ownerAddress === 'string' && ownerAddress.length > 0, `RWA ${txid}: invalid owner`);
        assert(
          typeof assetHash === 'string' && /^[0-9a-f]{64}$/i.test(assetHash),
          `RWA ${txid}: invalid asset hash`,
        );
        assert(!rwaAssets.has(assetId), `RWA ${txid}: duplicate asset ID`);
        assert(
          transaction.fee >= parameters.rwa_creation_min_fee,
          `RWA ${txid}: fee below minimum`,
        );
        transaction.inputs.forEach((input) => {
          const previous = outputHistory.get(outpoint(input.prev_txid, input.prev_vout));
          assert(previous?.address === ownerAddress, `RWA ${txid}: input owner mismatch`);
        });
        transaction.outputs.forEach((output) => {
          assert(output.address === ownerAddress, `RWA ${txid}: output owner mismatch`);
        });

        const reserved = new Set([
          'asset_id',
          'owner_address',
          'asset_hash',
          'name',
          'asset_type',
        ]);
        const extraMetadata = {};
        Object.keys(metadata)
          .filter((key) => !reserved.has(key))
          .sort(pythonStringCompare)
          .forEach((key) => {
            extraMetadata[key] = metadata[key];
          });
        rwaAssets.set(assetId, {
          asset_id: assetId,
          owner_address: ownerAddress,
          asset_hash: assetHash,
          name: metadata.name ?? null,
          asset_type: metadata.asset_type ?? null,
          create_txid: txid,
          create_height: block.height,
          created_time: transaction.timestamp || block.header.timestamp,
          metadata: extraMetadata,
        });
        rwaCreateTxid = txid;
        blockMetadataTransactions.push({ transaction, txid });
      } else if (transaction.tx_type === 'key_register') {
        assert(metadata && typeof metadata === 'object', `key registration ${txid}: missing metadata`);
        const ownerAddress = metadata.owner_address;
        const kemPub = metadata.kem_pub;
        const sigPub = metadata.sig_pub;
        assert(typeof ownerAddress === 'string' && ownerAddress.length > 0, `key registration ${txid}: invalid owner`);
        assert(
          typeof kemPub === 'string'
            && kemPub.length === parameters.ml_kem768_public_key_hex_length
            && /^[0-9a-f]+$/i.test(kemPub),
          `key registration ${txid}: invalid ML-KEM key`,
        );
        assert(
          typeof sigPub === 'string'
            && sigPub.length === parameters.ml_dsa44_public_key_hex_length
            && /^[0-9a-f]+$/i.test(sigPub),
          `key registration ${txid}: invalid ML-DSA key`,
        );
        assert(
          transaction.fee >= parameters.messaging_key_register_min_fee,
          `key registration ${txid}: fee below minimum`,
        );
        transaction.inputs.forEach((input) => {
          const previous = outputHistory.get(outpoint(input.prev_txid, input.prev_vout));
          assert(previous?.address === ownerAddress, `key registration ${txid}: input owner mismatch`);
        });
        transaction.outputs.forEach((output) => {
          assert(output.address === ownerAddress, `key registration ${txid}: output owner mismatch`);
        });
        messagingKeys.set(ownerAddress, {
          address: ownerAddress,
          kem_pub: kemPub,
          sig_pub: sigPub,
          register_txid: txid,
          register_height: block.height,
          registered_time: transaction.timestamp || block.header.timestamp,
        });
        messagingRegistrationTxids.push(txid);
        blockMetadataTransactions.push({ transaction, txid });
      }

      transaction.outputs.forEach((output, vout) => {
        outputHistory.set(outpoint(txid, vout), output);
      });
    }

    if (blockMetadataTransactions.length > 0) {
      assert(
        blockMetadataTransactions.length === 1 && block.transactions.length === 2,
        `block ${block.height}: metadata fee fixture must contain one metadata transaction`,
      );
      assert(
        block.header.consensus_type === 'pow'
          && block.height > 0
          && block.height <= parameters.phase_2a_end_height,
        `block ${block.height}: metadata fee block is outside pinned PoW reward phases`,
      );
      assert(
        parameters.metadata_fee_policy === 'fully_redistributed_via_coinbase',
        'metadata fee policy changed',
      );
      const scheduledPowBase = block.height <= parameters.activation_height
        ? parameters.pre_pos_pow_reward
        : parameters.phase_2a_pow_reward;
      assert(
        Number.isSafeInteger(scheduledPowBase) && scheduledPowBase > 0,
        `block ${block.height}: scheduled PoW reward is missing`,
      );
      const [{ transaction, txid }] = blockMetadataTransactions;
      const coinbaseOutputTotal = block.transactions[0].outputs.reduce(
        (sum, output) => sum + output.value,
        0,
      );
      const redistributedFee = coinbaseOutputTotal - scheduledPowBase;
      assert(
        redistributedFee === transaction.fee,
        `block ${block.height}: metadata fee was not fully redistributed`,
      );
      metadataFeeBlocks.push({
        height: block.height,
        transaction_type: transaction.tx_type,
        transaction_id: txid,
        fee: transaction.fee,
        scheduled_pow_base: scheduledPowBase,
        coinbase_output_total: coinbaseOutputTotal,
        redistributed_fee: redistributedFee,
      });
    }
  }

  return {
    rwaAssets: [...rwaAssets.values()]
      .sort((left, right) => pythonStringCompare(left.asset_id, right.asset_id)),
    messagingKeys: [...messagingKeys.values()]
      .sort((left, right) => pythonStringCompare(left.address, right.address)),
    metadataFeeBlocks,
    metadataFeeTotal: metadataFeeBlocks.reduce((sum, row) => sum + row.fee, 0),
    metadataFeeRedistributedTotal: metadataFeeBlocks.reduce(
      (sum, row) => sum + row.redistributed_fee,
      0,
    ),
    rwaCreateTxid,
    messagingRegistrationTxids,
  };
}

function deriveProtocolRewards(blocks, parameters) {
  const stakeDefinitions = deriveActiveStakes(blocks, parameters, true);
  const stakeDefinitionById = new Map(stakeDefinitions.map((stake) => [stake.stake_id, stake]));
  const masternodeDefinitions = deriveMasternodes(blocks, parameters, true);
  const masternodeDefinitionById = new Map(
    masternodeDefinitions.map((masternode) => [masternode.masternode_id, masternode]),
  );
  const stakes = new Map();
  const masternodes = new Map();
  const rewards = [];
  const rewardUtxos = [];
  const recordReward = (block, address, type, amount, rewardId) => {
    rewards.push({
      reward_id: rewardId,
      recipient_address: address,
      recipient_type: type,
      amount,
      block_height: block.height,
      block_hash: sha256Hex(canonicalHeaderBytes(block.header)),
      timestamp: block.header.timestamp,
    });
    rewardUtxos.push({
      txid: `pos_reward_${rewardId}`,
      vout: 0,
      address,
      amount,
      script_pubkey: Buffer.from('pos_reward', 'ascii').toString('hex'),
      created_height: block.height,
      is_coinbase: true,
    });
  };

  for (const block of blocks) {
    const spentInBlock = new Set();
    for (const transaction of block.transactions) {
      if (isCoinbase(transaction)) continue;
      for (const input of transaction.inputs) {
        spentInBlock.add(outpoint(input.prev_txid, input.prev_vout));
      }
    }
    const eligibleStakes = [...stakes.values()]
      .filter((stake) => stake.status === 'active'
        && !spentInBlock.has(outpoint(stake.lock_txid, stake.lock_vout)))
      .sort((left, right) => pythonStringCompare(left.staker_address, right.staker_address)
        || pythonStringCompare(left.stake_id, right.stake_id));
    const eligibleMasternodes = [...masternodes.values()]
      .filter((masternode) => masternode.status === 'active'
        && !spentInBlock.has(outpoint(masternode.collateral_txid, masternode.collateral_vout)))
      .sort((left, right) => pythonStringCompare(left.masternode_id, right.masternode_id));

    if (
      block.height > parameters.activation_height
      && (eligibleStakes.length > 0 || eligibleMasternodes.length > 0)
    ) {
      assert(parameters.empty_side_rolls_over === true, 'reward rollover policy changed');
      const rewardPool = Math.floor(parameters.initial_pos_base_reward / parameters.pos_pool_divisor);
      let stakerPool = 0;
      let masternodePool = 0;
      if (eligibleStakes.length > 0 && eligibleMasternodes.length > 0) {
        stakerPool = Math.floor(rewardPool * parameters.staker_pool_percent / 100);
        masternodePool = rewardPool - stakerPool;
      } else if (eligibleStakes.length > 0) {
        stakerPool = rewardPool;
      } else {
        masternodePool = rewardPool;
      }

      let distributed = 0;
      if (stakerPool > 0) {
        const totalStake = eligibleStakes.reduce((sum, stake) => sum + stake.amount, 0);
        let remaining = stakerPool;
        eligibleStakes.forEach((stake, index) => {
          const amount = index === eligibleStakes.length - 1
            ? remaining
            : Math.min(Math.floor(stakerPool * stake.amount / totalStake), remaining);
          remaining -= amount;
          if (amount <= 0) return;
          stake.total_rewards += amount;
          stake.last_reward_height = block.height;
          recordReward(block, stake.staker_address, 'staker', amount, `reward_staker_${block.height}_${stake.stake_id}`);
          distributed += amount;
        });
        assert(remaining === 0, `block ${block.height}: staker pool was not conserved`);
      }
      if (masternodePool > 0) {
        const perMasternode = Math.floor(masternodePool / eligibleMasternodes.length);
        const remainder = masternodePool % eligibleMasternodes.length;
        eligibleMasternodes.forEach((masternode, index) => {
          const amount = perMasternode + (index < remainder ? 1 : 0);
          if (amount <= 0) return;
          masternode.total_rewards += amount;
          masternode.last_ping = block.header.timestamp;
          recordReward(
            block,
            masternode.operator_address,
            'masternode',
            amount,
            `reward_masternode_${block.height}_${masternode.masternode_id}`,
          );
          distributed += amount;
        });
      }
      assert(distributed === rewardPool, `block ${block.height}: protocol reward pool was not conserved`);
    }

    for (const transaction of block.transactions) {
      const txid = canonicalTransactionMaterialHex(transaction).txid;
      if (transaction.tx_type === 'stake_create') {
        const definition = stakeDefinitionById.get(transaction.extra_data?.stake_id);
        assert(definition, `stake reward replay ${txid}: missing definition`);
        stakes.set(definition.stake_id, {
          ...definition,
          last_reward_height: 0,
          total_rewards: 0,
          status: 'active',
          unlock_height: null,
          deactivation_txid: null,
        });
      } else if (transaction.tx_type === 'stake_deactivate') {
        const stake = stakes.get(transaction.extra_data?.stake_id);
        assert(stake?.status === 'active', `stake reward replay ${txid}: inactive stake`);
        stake.status = 'inactive';
        stake.unlock_height = block.height;
        stake.deactivation_txid = txid;
      } else if (transaction.tx_type === 'masternode_create') {
        const definition = masternodeDefinitionById.get(transaction.extra_data?.masternode_id);
        assert(definition, `masternode reward replay ${txid}: missing definition`);
        masternodes.set(definition.masternode_id, {
          ...definition,
          last_ping: 0,
          total_rewards: 0,
          status: 'active',
          deactivation_txid: null,
        });
      } else if (transaction.tx_type === 'masternode_deactivate') {
        const masternode = masternodes.get(transaction.extra_data?.masternode_id);
        assert(masternode?.status === 'active', `masternode reward replay ${txid}: inactive masternode`);
        masternode.status = 'inactive';
        masternode.deactivation_txid = txid;
      }
    }
  }

  return {
    stakes: [...stakes.values()].sort(
      (left, right) => pythonStringCompare(left.staker_address, right.staker_address)
        || pythonStringCompare(left.stake_id, right.stake_id),
    ),
    masternodes: [...masternodes.values()]
      .sort((left, right) => pythonStringCompare(left.masternode_id, right.masternode_id)),
    rewards: rewards.sort(
      (left, right) => left.block_height - right.block_height
        || pythonStringCompare(left.reward_id, right.reward_id),
    ),
    rewardUtxos,
  };
}

function selectPosValidator(stakes, blockHeight, parentHash) {
  const totalStake = stakes.reduce((sum, stake) => sum + BigInt(stake.amount), 0n);
  assert(totalStake > 0n, 'PoS selection has no stake');
  const selectionPayload = Buffer.concat([
    Buffer.from('WEPO_POS_VALIDATOR_SELECTION_V1\u0000', 'ascii'),
    uint64LE(blockHeight),
    Buffer.from(parentHash, 'hex'),
    uint64LE(totalStake),
  ]);
  const digest = createHash('sha3-256').update(selectionPayload).digest();
  const randomPoint = BigInt(`0x${digest.toString('hex')}`) % totalStake;
  let cumulative = 0n;
  for (const stake of stakes) {
    cumulative += BigInt(stake.amount);
    if (cumulative > randomPoint) return stake.staker_address;
  }
  fail('PoS selection did not choose a validator');
}

function posSigningMessage(candidate, networkName) {
  const payload = Buffer.concat([
    Buffer.from('WEPO_POS_BLOCK_SIGNATURE_V1\u0000', 'ascii'),
    lengthPrefixed(Buffer.from(networkName, 'ascii')),
    uint64LE(candidate.height),
    canonicalHeaderBytes(candidate.header, false),
  ]);
  return createHash('sha3-256').update(payload).digest();
}

function validatePosScenario(scenario, coinbaseMaturity) {
  const expectedParameters = {
    network_name: 'test',
    activation_height: 12,
    first_active_height: 13,
    block_time_pos: 10,
    minimum_stake_amount: 10000000000,
    minimum_masternode_collateral: 50000000000,
    rwa_creation_min_fee: 10000,
    messaging_key_register_min_fee: 10000,
    ml_kem768_public_key_hex_length: 2368,
    ml_dsa44_public_key_hex_length: 2624,
    metadata_fee_policy: 'fully_redistributed_via_coinbase',
    phase_2a_end_height: 30,
    phase_2a_pow_reward: 3317000000,
    initial_pos_base_reward: 2500000000,
    pos_pool_divisor: 2,
    staker_pool_percent: 60,
    masternode_pool_percent: 40,
    empty_side_rolls_over: true,
    selection_domain: 'WEPO_POS_VALIDATOR_SELECTION_V1\\0',
    signature_domain: 'WEPO_POS_BLOCK_SIGNATURE_V1\\0',
    score_order: 'pow_work_then_pos_count',
  };
  assert(
    canonicalJson(scenario.parameters) === canonicalJson(expectedParameters),
    'unexpected PoS parameters',
  );
  const parent = replayBranch(
    scenario.parent.blocks,
    scenario.parent.expected.pow_hashes,
    coinbaseMaturity,
    'PoS parent',
  );
  validateExpectedBranch(parent, scenario.parent.expected, 'PoS parent');

  const stakes = deriveActiveStakes(scenario.parent.blocks, scenario.parameters);
  assert(
    canonicalJson(stakes) === canonicalJson(scenario.active_stakes),
    'PoS active-stake derivation mismatch',
  );
  const candidate = scenario.candidate;
  assert(
    candidate.height === parent.height + 1
      && candidate.height === scenario.expected.candidate_height,
    'PoS candidate height mismatch',
  );
  assert(candidate.header.prev_hash === parent.tip, 'PoS candidate parent mismatch');
  assert(candidate.header.consensus_type === 'pos', 'PoS candidate has wrong consensus type');
  assert(candidate.header.bits === 0 && candidate.header.nonce === 0, 'PoS work fields are nonzero');

  const previousPos = [...scenario.parent.blocks]
    .reverse()
    .find((block) => block.header.consensus_type === 'pos');
  const slotAnchor = previousPos
    ? previousPos.header.timestamp
    : scenario.parent.blocks.at(-1).header.timestamp;
  assert(slotAnchor === scenario.expected.slot_anchor, 'PoS slot anchor mismatch');
  assert(
    candidate.header.timestamp >= slotAnchor + scenario.parameters.block_time_pos
      && candidate.header.timestamp === scenario.expected.candidate_timestamp,
    'PoS candidate violates slot pacing',
  );

  const selected = selectPosValidator(stakes, candidate.height, parent.tip);
  assert(selected === scenario.expected.selected_validator, 'PoS selected validator mismatch');
  assert(candidate.header.validator_address === selected, 'PoS candidate uses non-selected validator');
  const validatorStake = stakes
    .filter((stake) => stake.staker_address === selected)
    .reduce((sum, stake) => sum + stake.amount, 0);
  assert(
    validatorStake >= scenario.parameters.minimum_stake_amount,
    'PoS validator is below minimum stake',
  );
  assert(
    deriveAddressFromHex(candidate.header.validator_public_key) === selected,
    'PoS validator public key does not own its address',
  );
  assert(
    candidate.header.validator_public_key === scenario.expected.validator_public_key,
    'PoS validator public key mismatch',
  );
  assert(
    candidate.header.validator_signature === scenario.expected.validator_signature,
    'PoS validator signature fixture mismatch',
  );

  const signingMessage = posSigningMessage(candidate, scenario.parameters.network_name);
  assert(
    signingMessage.toString('hex') === scenario.expected.signing_message_hex,
    'PoS cross-runtime signing digest mismatch',
  );
  assert(
    ml_dsa44.verify(
      Buffer.from(candidate.header.validator_signature, 'hex'),
      signingMessage,
      Buffer.from(candidate.header.validator_public_key, 'hex'),
    ),
    'PoS ML-DSA validator signature is invalid',
  );
  const candidateHash = sha256Hex(canonicalHeaderBytes(candidate.header));
  assert(candidateHash === scenario.expected.candidate_hash, 'PoS candidate hash mismatch');

  const candidateReplay = replayBranch(
    [...scenario.parent.blocks, candidate],
    [...scenario.parent.expected.pow_hashes, null],
    coinbaseMaturity,
    'PoS candidate chain',
  );
  assert(candidateReplay.tip === candidateHash, 'PoS candidate replay tip mismatch');
  assert(candidateReplay.score.pos_blocks === 1, 'PoS candidate score tie-breaker mismatch');
  assert(
    candidateReplay.score.pow_work === parent.score.pow_work,
    'PoS candidate manufactured proof-of-work',
  );
  assert(
    Array.isArray(scenario.continuation_blocks)
      && scenario.continuation_blocks.length === 8,
    'PoS protocol lifecycle continuation is missing',
  );
  const fullBlocks = [
    ...scenario.parent.blocks,
    candidate,
    ...scenario.continuation_blocks,
  ];
  const finalReplay = replayBranch(
    fullBlocks,
    scenario.expected_final.pow_hashes,
    coinbaseMaturity,
    'PoS protocol lifecycle chain',
  );
  const registrationBlocks = [
    ...scenario.parent.blocks,
    candidate,
    ...scenario.continuation_blocks.slice(0, 2),
  ];
  const registeredMasternodes = deriveMasternodes(
    registrationBlocks,
    scenario.parameters,
  );
  assert(
    canonicalJson(registeredMasternodes)
      === canonicalJson(scenario.active_masternodes_after_registration),
    'PoS active-masternode derivation mismatch',
  );

  const lifecycle = deriveProtocolRewards(fullBlocks, scenario.parameters);
  assert(
    canonicalJson(lifecycle.stakes) === canonicalJson(scenario.expected_final.stakes),
    'PoS final stake state mismatch',
  );
  assert(
    canonicalJson(lifecycle.masternodes)
      === canonicalJson(scenario.expected_final.masternodes),
    'PoS final masternode state mismatch',
  );
  assert(
    canonicalJson(lifecycle.rewards) === canonicalJson(scenario.expected_final.rewards),
    'PoS reward history mismatch',
  );
  assert(
    lifecycle.stakes.every((stake) => stake.status !== 'active')
      && lifecycle.masternodes.every((masternode) => masternode.status !== 'active'),
    'PoS deactivated protocol participant remained eligible',
  );
  const derivedRewardTotal = lifecycle.rewards.reduce(
    (sum, reward) => sum + reward.amount,
    0,
  );
  const derivedStakeRewards = lifecycle.rewards
    .filter((reward) => reward.recipient_type === 'staker')
    .reduce((sum, reward) => sum + reward.amount, 0);
  const derivedMasternodeRewards = lifecycle.rewards
    .filter((reward) => reward.recipient_type === 'masternode')
    .reduce((sum, reward) => sum + reward.amount, 0);
  assert(
    derivedRewardTotal === scenario.expected_final.total_pos_rewards
      && derivedStakeRewards === scenario.expected_final.stake_rewards
      && derivedMasternodeRewards === scenario.expected_final.masternode_rewards,
    'PoS protocol reward totals mismatch',
  );

  const metadataIndexes = deriveMetadataIndexes(fullBlocks, scenario.parameters);
  assert(
    canonicalJson(metadataIndexes.rwaAssets)
      === canonicalJson(scenario.expected_final.rwa_assets),
    'RWA derived index mismatch',
  );
  assert(
    canonicalJson(metadataIndexes.messagingKeys)
      === canonicalJson(scenario.expected_final.messaging_keys),
    'messaging-key derived index mismatch',
  );
  assert(
    canonicalJson(metadataIndexes.metadataFeeBlocks)
      === canonicalJson(scenario.expected_final.metadata_fee_blocks),
    'metadata fee redistribution evidence mismatch',
  );
  assert(
    metadataIndexes.metadataFeeTotal === scenario.expected_final.metadata_fee_total
      && metadataIndexes.metadataFeeRedistributedTotal
        === scenario.expected_final.metadata_fee_redistributed_total
      && metadataIndexes.metadataFeeTotal
        === metadataIndexes.metadataFeeRedistributedTotal,
    'metadata fees were not exactly conserved',
  );
  assert(
    metadataIndexes.rwaCreateTxid === scenario.expected_final.rwa_create_txid,
    'RWA creation transaction identity mismatch',
  );
  assert(
    canonicalJson(metadataIndexes.messagingRegistrationTxids)
      === canonicalJson(scenario.expected_final.messaging_registration_txids),
    'messaging registration history mismatch',
  );

  const rows = [...finalReplay.rows, ...lifecycle.rewardUtxos].sort(
    (left, right) => left.txid.localeCompare(right.txid) || left.vout - right.vout,
  );
  const payload = Buffer.from(canonicalJson(rows), 'utf8');
  const commitment = sha256Hex(Buffer.concat([
    STATE_DOMAIN,
    uint32LE(payload.length),
    payload,
  ]));
  const total = rows.reduce((sum, row) => sum + row.amount, 0);
  assert(finalReplay.height === scenario.expected_final.height, 'PoS final height mismatch');
  assert(finalReplay.tip === scenario.expected_final.tip, 'PoS final tip mismatch');
  assert(total === scenario.expected_final.utxo_total, 'PoS final UTXO total mismatch');
  assert(total === scenario.expected_final.issued_supply, 'PoS final issued supply mismatch');
  assert(
    scenario.expected_final.supply_minus_utxo_total
      === scenario.expected_final.issued_supply - total
      && scenario.expected_final.supply_minus_utxo_total === 0,
    'metadata fee conservation changed issued-supply semantics',
  );

  assert(
    canonicalJson(rows) === canonicalJson(scenario.expected_final.utxos),
    'PoS final UTXO set mismatch',
  );
  assert(
    payload.toString('hex') === scenario.expected_final.state_payload_utf8_hex,
    'PoS final state payload mismatch',
  );
  assert(
    commitment === scenario.expected_final.state_commitment,
    'PoS final state commitment mismatch',
  );

  const transactions = fullBlocks.flatMap((block) => block.transactions);
  const registration = transactions.find(
    (transaction) => transaction.tx_type === 'masternode_create',
  );
  const stakeDeactivation = transactions.find(
    (transaction) => transaction.tx_type === 'stake_deactivate',
  );
  const masternodeDeactivation = transactions.find(
    (transaction) => transaction.tx_type === 'masternode_deactivate',
  );
  assert(registration, 'PoS masternode registration transaction is missing');
  assert(stakeDeactivation, 'PoS stake deactivation transaction is missing');
  assert(masternodeDeactivation, 'PoS masternode deactivation transaction is missing');
  assert(
    canonicalTransactionMaterialHex(registration).txid
      === scenario.expected_final.masternode_registration_txid
      && registration.extra_data?.masternode_id === scenario.expected_final.masternode_id,
    'PoS masternode registration identity mismatch',
  );
  assert(
    canonicalTransactionMaterialHex(stakeDeactivation).txid
      === scenario.expected_final.stake_deactivation_txid,
    'PoS stake deactivation transaction identity mismatch',
  );
  assert(
    canonicalTransactionMaterialHex(masternodeDeactivation).txid
      === scenario.expected_final.masternode_deactivation_txid,
    'PoS masternode deactivation transaction identity mismatch',
  );
  return {
    lifecycleHeight: finalReplay.height,
    lifecycleTip: finalReplay.tip,
    lifecycleCommitment: commitment,
    lifecycleRewards: derivedRewardTotal,
    lifecycleStakeRewards: derivedStakeRewards,
    lifecycleMasternodeRewards: derivedMasternodeRewards,
    stakeDeactivationTxid: scenario.expected_final.stake_deactivation_txid,
    masternodeId: scenario.expected_final.masternode_id,
    masternodeRegistrationTxid: scenario.expected_final.masternode_registration_txid,
    masternodeDeactivationTxid: scenario.expected_final.masternode_deactivation_txid,
    rwaAssetId: metadataIndexes.rwaAssets[0]?.asset_id,
    rwaCreateTxid: metadataIndexes.rwaCreateTxid,
    messagingLatestTxid: metadataIndexes.messagingKeys[0]?.register_txid,
    messagingRegistrationTxids: metadataIndexes.messagingRegistrationTxids,
    metadataFeeTotal: metadataIndexes.metadataFeeTotal,
    metadataFeeRedistributedTotal: metadataIndexes.metadataFeeRedistributedTotal,
    supplyMinusUtxoTotal: scenario.expected_final.supply_minus_utxo_total,
    validator: selected,
    height: candidate.height,
    tip: candidateHash,
    signingMessage: signingMessage.toString('hex'),
  };
}
function replay(fixture) {
  assert(fixture.schema === 'wepo-state-transition-oracle-v1', 'unsupported fixture schema');
  assert(fixture.network_profile === 'test', 'oracle fixture must use the test profile');
  assert(Number.isInteger(fixture.coinbase_maturity), 'missing coinbase maturity');
  validatePowConfiguration(fixture.pow);
  validateDifficultyVectors(fixture.difficulty);

  const primary = replayBranch(
    fixture.blocks,
    fixture.expected.pow_hashes,
    fixture.coinbase_maturity,
    'primary',
  );
  validateExpectedBranch(primary, fixture.expected, 'primary');
  const forkWinner = validateForkChoice(fixture.fork_choice, fixture.coinbase_maturity);
  const shielded = validateShieldedScenario(
    fixture.shielded_scenario,
    fixture.coinbase_maturity,
  );
  const pos = validatePosScenario(fixture.pos_scenario, fixture.coinbase_maturity);
  return {
    status: 'pass',
    height: primary.height,
    tip: primary.tip,
    issued_supply: primary.total,
    utxo_count: primary.rows.length,
    state_commitment: primary.commitment,
    fork_winner: forkWinner.name,
    fork_height: forkWinner.result.height,
    fork_tip: forkWinner.result.tip,
    fork_pow_work: forkWinner.result.score.pow_work,
    fork_rwa_asset_id: forkWinner.metadataIndexes.rwaAssets[0]?.asset_id,
    fork_messaging_key_txid: forkWinner.metadataIndexes.messagingKeys[0]?.register_txid,
    fork_metadata_fee_total: forkWinner.metadataIndexes.metadataFeeTotal,
    fork_metadata_fee_redistributed_total:
      forkWinner.metadataIndexes.metadataFeeRedistributedTotal,
    shielded_height: shielded.height,
    shielded_tip: shielded.tip,
    shielded_tree_root: shielded.treeRoot,
    shielded_pool_balance: shielded.poolBalance,
    shielded_commitment_count: shielded.commitments,
    shielded_nullifier_count: shielded.nullifiers,
    shielded_transaction_ids: shielded.transactionIds,
    shielded_sighashes: shielded.sighashes,
    shielded_statement_digests: shielded.statementDigests,
    pos_validator: pos.validator,
    pos_height: pos.height,
    pos_tip: pos.tip,
    pos_signing_message: pos.signingMessage,
    lifecycle_height: pos.lifecycleHeight,
    lifecycle_tip: pos.lifecycleTip,
    lifecycle_state_commitment: pos.lifecycleCommitment,
    lifecycle_pos_rewards: pos.lifecycleRewards,
    lifecycle_stake_rewards: pos.lifecycleStakeRewards,
    lifecycle_masternode_rewards: pos.lifecycleMasternodeRewards,
    stake_deactivation_txid: pos.stakeDeactivationTxid,
    masternode_id: pos.masternodeId,
    masternode_registration_txid: pos.masternodeRegistrationTxid,
    rwa_asset_id: pos.rwaAssetId,
    rwa_create_txid: pos.rwaCreateTxid,
    messaging_latest_txid: pos.messagingLatestTxid,
    messaging_registration_txids: pos.messagingRegistrationTxids,
    metadata_fee_total: pos.metadataFeeTotal,
    metadata_fee_redistributed_total: pos.metadataFeeRedistributedTotal,
    supply_minus_utxo_total: pos.supplyMinusUtxoTotal,
    masternode_deactivation_txid: pos.masternodeDeactivationTxid,
  };
}

try {
  const fixturePath = process.argv[2];
  if (!fixturePath) fail('Usage: node state_transition_oracle.mjs <fixture.json>');
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));
  process.stdout.write(`${JSON.stringify(replay(fixture))}\n`);
} catch (error) {
  process.stderr.write(`state oracle failed: ${error.message}\n`);
  process.exitCode = 1;
}
