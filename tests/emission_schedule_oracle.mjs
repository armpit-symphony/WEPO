#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function atomic(value, label) {
  assert(typeof value === 'string' && /^[0-9]+$/.test(value), `${label} must be an unsigned decimal string`);
  return BigInt(value);
}

function posPoolAtHeight(height, parameters) {
  if (height <= parameters.pos_activation_height) return 0n;
  const year = Math.floor(
    (height - parameters.pos_activation_height) / parameters.blocks_per_year_longterm,
  );
  let base = atomic(parameters.pos_initial_base_reward_atomic, 'pos_initial_base_reward_atomic');
  if (year >= parameters.pos_second_tier_year) base /= 2n;
  if (year >= parameters.pos_third_tier_year) base /= 2n;
  if (year >= parameters.pos_recurring_halving_start_year) {
    const halvings = Math.floor(
      (year - parameters.pos_recurring_halving_start_year)
        / parameters.pos_recurring_halving_interval_years,
    );
    for (let index = 0; index < halvings; index += 1) base /= 2n;
  }
  return base / 2n;
}

function powBaseAtHeight(height, parameters) {
  if (height === 0) return atomic(parameters.genesis_bootstrap_atomic, 'genesis_bootstrap_atomic');
  const phase = parameters.pow_phases.find(
    (candidate) => height >= candidate.start_height && height <= candidate.end_height,
  );
  return phase ? atomic(phase.reward_atomic, `${phase.name}.reward_atomic`) : 0n;
}

export function evaluate(fixture) {
  assert(fixture.schema === 'wepo-emission-schedule-v1', 'unsupported emission fixture schema');
  const parameters = fixture.parameters;
  const expected = fixture.expected;
  const cap = atomic(parameters.hard_cap_atomic, 'hard_cap_atomic');
  const genesis = atomic(parameters.genesis_bootstrap_atomic, 'genesis_bootstrap_atomic');

  assert(parameters.pow_phases.length > 0, 'at least one PoW phase is required');
  let nextHeight = 1;
  let powPhaseTotal = 0n;
  const phaseTotals = [];
  for (const phase of parameters.pow_phases) {
    assert(phase.start_height === nextHeight, `${phase.name}: non-contiguous start height`);
    assert(phase.end_height >= phase.start_height, `${phase.name}: invalid height range`);
    const blockCount = phase.end_height - phase.start_height + 1;
    const reward = atomic(phase.reward_atomic, `${phase.name}.reward_atomic`);
    const total = BigInt(blockCount) * reward;
    phaseTotals.push({
      name: phase.name,
      start_height: phase.start_height,
      end_height: phase.end_height,
      block_count: blockCount,
      reward_atomic: reward.toString(),
      total_atomic: total.toString(),
    });
    powPhaseTotal += total;
    nextHeight = phase.end_height + 1;
  }
  assert(
    parameters.pow_phases[0].end_height === parameters.pos_activation_height,
    'PoS activation must equal the final pre-PoS height',
  );
  assert(
    parameters.pow_phases.at(-1).end_height === parameters.pow_end_height,
    'PoW end height differs from the final PoW phase',
  );

  let posTotal = 0n;
  let lastNonzeroYear = -1;
  for (let year = 0; year < parameters.pos_max_years_guard; year += 1) {
    const firstHeight = parameters.pos_activation_height + year * parameters.blocks_per_year_longterm;
    const sampleHeight = year === 0 ? firstHeight + 1 : firstHeight;
    const pool = posPoolAtHeight(sampleHeight, parameters);
    if (pool === 0n) break;
    const blockCount = year === 0
      ? parameters.blocks_per_year_longterm - 1
      : parameters.blocks_per_year_longterm;
    posTotal += BigInt(blockCount) * pool;
    lastNonzeroYear = year;
  }
  assert(lastNonzeroYear >= 0, 'PoS schedule never emits');
  assert(lastNonzeroYear + 1 < parameters.pos_max_years_guard, 'PoS zero-reward tail guard exhausted');

  const lastNonzeroPosHeight = parameters.pos_activation_height
    + (lastNonzeroYear + 1) * parameters.blocks_per_year_longterm - 1;
  const firstZeroPosHeight = lastNonzeroPosHeight + 1;
  assert(posPoolAtHeight(lastNonzeroPosHeight, parameters) > 0n, 'last PoS height is not positive');
  assert(posPoolAtHeight(firstZeroPosHeight, parameters) === 0n, 'first zero PoS height still emits');

  const powTotal = genesis + powPhaseTotal;
  const prePosTotal = BigInt(phaseTotals[0].total_atomic);
  const allPosAfterActivationTotal = genesis + prePosTotal + posTotal;
  const maximumQualifyingTotal = powTotal + posTotal;
  const cappedMaximum = maximumQualifyingTotal > cap ? cap : maximumQualifyingTotal;
  const shortfall = cap - cappedMaximum;

  const actual = {
    phase_totals: phaseTotals,
    pow_total_atomic: powTotal.toString(),
    pos_total_atomic: posTotal.toString(),
    all_pos_after_activation_atomic: allPosAfterActivationTotal.toString(),
    no_eligible_pos_recipients_atomic: powTotal.toString(),
    maximum_qualifying_issuance_atomic: cappedMaximum.toString(),
    maximum_scheduled_before_cap_atomic: maximumQualifyingTotal.toString(),
    cap_shortfall_atomic: shortfall.toString(),
    cap_reachable: maximumQualifyingTotal >= cap,
    clamp_triggered: maximumQualifyingTotal > cap,
    last_nonzero_pos_height: lastNonzeroPosHeight,
    first_zero_pos_height: firstZeroPosHeight,
  };

  assert(actual.phase_totals.length === expected.phase_totals.length, 'PoW phase totals changed');
  for (let index = 0; index < actual.phase_totals.length; index += 1) {
    const computed = actual.phase_totals[index];
    const pinned = expected.phase_totals[index];
    for (const key of [
      'name',
      'start_height',
      'end_height',
      'block_count',
      'reward_atomic',
      'total_atomic',
    ]) assert(computed[key] === pinned[key], 'PoW phase totals changed');
  }
  for (const key of [
    'pow_total_atomic',
    'pos_total_atomic',
    'all_pos_after_activation_atomic',
    'no_eligible_pos_recipients_atomic',
    'maximum_qualifying_issuance_atomic',
    'maximum_scheduled_before_cap_atomic',
    'cap_shortfall_atomic',
  ]) assert(actual[key] === expected[key], `${key} changed`);
  for (const key of ['cap_reachable', 'clamp_triggered']) {
    assert(actual[key] === expected[key], `${key} changed`);
  }
  for (const key of ['last_nonzero_pos_height', 'first_zero_pos_height']) {
    assert(actual[key] === expected[key], `${key} changed`);
  }

  for (const boundary of expected.boundary_rewards) {
    assert(
      powBaseAtHeight(boundary.height, parameters).toString() === boundary.pow_base_atomic,
      `PoW boundary reward changed at height ${boundary.height}`,
    );
    assert(
      posPoolAtHeight(boundary.height, parameters).toString() === boundary.pos_pool_atomic,
      `PoS boundary reward changed at height ${boundary.height}`,
    );
  }
  assert(maximumQualifyingTotal <= cap || cappedMaximum === cap, 'cap clamp failed');
  return actual;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  const fixturePath = process.argv[2];
  if (!fixturePath) fail('usage: node tests/emission_schedule_oracle.mjs <fixture.json>');
  const result = evaluate(JSON.parse(fs.readFileSync(fixturePath, 'utf8')));
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}
