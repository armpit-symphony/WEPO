import { vi } from 'vitest';

const FLAG_NAMES = [
  'REACT_APP_WEPO_FEATURE_PRIVACY',
  'REACT_APP_WEPO_FEATURE_RWA',
  'REACT_APP_WEPO_FEATURE_RWA_TRADE',
  'REACT_APP_WEPO_FEATURE_BTC',
  'REACT_APP_WEPO_FEATURE_MESSAGING',
  'REACT_APP_WEPO_FEATURE_BROWSER_MINING',
];

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.resetModules();
});

const loadFeatures = async () => {
  vi.resetModules();
  return (await import('./featureFlags')).default;
};

test('mainnet cannot enable unfinished launch surfaces', async () => {
  process.env.REACT_APP_WEPO_NETWORK_PROFILE = 'mainnet';
  FLAG_NAMES.forEach((name) => { process.env[name] = 'true'; });
  const features = await loadFeatures();
  expect(Object.values(features)).toEqual([
    false, false, false, false, false, false,
  ]);
});

test('an unknown or misspelled profile fails closed', async () => {
  process.env.REACT_APP_WEPO_NETWORK_PROFILE = 'staging';
  process.env.REACT_APP_WEPO_FEATURE_PRIVACY = 'true';
  const features = await loadFeatures();
  expect(features.privacy).toBe(false);
});

test('a non-mainnet profile may explicitly opt into a feature', async () => {
  process.env.REACT_APP_WEPO_NETWORK_PROFILE = 'test';
  process.env.REACT_APP_WEPO_FEATURE_PRIVACY = 'true';
  process.env.REACT_APP_WEPO_FEATURE_BTC = '1';
  process.env.REACT_APP_WEPO_FEATURE_BROWSER_MINING = 'yes';
  const features = await loadFeatures();
  expect(features.privacy).toBe(true);
  expect(features.btc).toBe(true);
  expect(features.browserMining).toBe(true);
  expect(features.rwa).toBe(false);
});
