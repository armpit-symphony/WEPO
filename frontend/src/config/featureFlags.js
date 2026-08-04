const enabled = (value) => ['1', 'true', 'yes', 'on'].includes(
  String(value || '').trim().toLowerCase()
);

// Build-time mirrors of the backend launch gates. A shipping build must not
// expose a feature unless the matching backend WEPO_FEATURE_* gate is enabled.
const networkProfile = String(
  process.env.REACT_APP_WEPO_NETWORK_PROFILE || 'mainnet'
).trim().toLowerCase();
export const NETWORK_PROFILE = networkProfile;


// These flags are test/staging opt-ins, not production activation switches.
// Mainnet cannot expose unfinished surfaces even if a feature flag is copied.
export const MAY_ENABLE_LAUNCH_FEATURES = networkProfile === 'test';

export const FEATURES = Object.freeze({
  privacy: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_PRIVACY),
  rwa: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_RWA),
  rwaTrade: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_RWA_TRADE),
  btc: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_BTC),
  messaging: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_MESSAGING),
  browserMining: MAY_ENABLE_LAUNCH_FEATURES && enabled(process.env.REACT_APP_WEPO_FEATURE_BROWSER_MINING),
});

export default FEATURES;
