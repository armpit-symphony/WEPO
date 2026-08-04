const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const desktopRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(desktopRoot, '..');
const desktopPackage = require(path.join(desktopRoot, 'package.json'));
const frontendPackage = require(path.join(repoRoot, 'frontend', 'package.json'));

const source = desktopPackage.build?.extraResources?.[0]?.from;
if (source !== '../frontend/build') {
  throw new Error('Desktop package is not configured to ship the canonical frontend build');
}

const packagedFiles = desktopPackage.build?.files || [];
if (packagedFiles.includes('src/**/*') || packagedFiles.includes('src/backend/**/*')) {
  throw new Error('Desktop package still includes legacy simulated client/backend sources');
}
if (!packagedFiles.includes('src/main.js') || !packagedFiles.includes('src/preload.js')) {
  throw new Error('Desktop package must contain the constrained Electron main and preload bridge');
}
const ghostResource = (desktopPackage.build?.extraResources || []).find(
  (resource) => resource.from === '../release-artifacts/ghost/artifacts/ghost_wallet_bridge.exe'
);
if (!ghostResource || ghostResource.to !== 'ghost/ghost_wallet_bridge.exe') {
  throw new Error('Desktop package must ship the audited Ghost wallet bridge sidecar');
}
const wasmResource = (desktopPackage.build?.extraResources || []).find(
  (resource) => resource.from === '../release-artifacts/ghost/artifacts/wepo_zk.wasm'
);
const manifestResource = (desktopPackage.build?.extraResources || []).find(
  (resource) => resource.from === '../release-artifacts/ghost/ghost-artifacts.json'
);
if (!wasmResource || wasmResource.to !== 'ghost/wepo_zk.wasm') {
  throw new Error('Desktop package must ship the hash-pinned Ghost WASM artifact');
}
if (!manifestResource || manifestResource.to !== 'ghost/ghost-artifacts.json') {
  throw new Error('Desktop package must ship the Ghost artifact manifest');
}
const artifactRoot = path.resolve(desktopRoot, '..', 'release-artifacts', 'ghost');
const manifestPath = path.join(artifactRoot, 'ghost-artifacts.json');
if (!fs.existsSync(manifestPath)) {
  throw new Error('Ghost artifact manifest is missing; build artifacts first');
}
let ghostManifest;
try {
  ghostManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
} catch (error) {
  throw new Error('Ghost artifact manifest is not valid JSON');
}
if (ghostManifest.format !== 'wepo-ghost-artifacts-v1'
    || ghostManifest.source?.clean_worktree !== true) {
  throw new Error('Ghost artifact manifest is not a clean-runner release manifest');
}
const expectedGhostArtifacts = {
  'ghost_wallet_bridge.exe': 'artifacts/ghost_wallet_bridge.exe',
  'wepo_zk.wasm': 'artifacts/wepo_zk.wasm',
};
for (const [name, relativePath] of Object.entries(expectedGhostArtifacts)) {
  const entry = ghostManifest.artifacts?.[name];
  if (!entry || entry.path !== relativePath || !/^[0-9a-f]{64}$/.test(entry.sha256 || '')) {
    throw new Error('Ghost artifact manifest is missing the pinned ' + name);
  }
  const artifactPath = path.resolve(artifactRoot, relativePath);
  if (!artifactPath.startsWith(artifactRoot + path.sep) || !fs.existsSync(artifactPath)) {
    throw new Error('Pinned Ghost artifact is missing: ' + name);
  }
  const digest = crypto.createHash('sha256').update(fs.readFileSync(artifactPath)).digest('hex');
  if (digest !== entry.sha256) {
    throw new Error('Pinned Ghost artifact hash mismatch: ' + name);
  }
}
const signer = path.join(repoRoot, 'frontend', 'src', 'utils', 'wepoSigner.js');
const wallet = path.join(repoRoot, 'frontend', 'src', 'contexts', 'WalletContext.jsx');
const viteConfig = path.join(repoRoot, 'frontend', 'vite.config.mjs');
const desktopMain = fs.readFileSync(path.join(desktopRoot, 'src', 'main.js'), 'utf8');
const desktopPreload = fs.readFileSync(path.join(desktopRoot, 'src', 'preload.js'), 'utf8');
if (!fs.existsSync(signer) || !fs.existsSync(wallet)) {
  throw new Error('Canonical wallet signer or context is missing');
}
const security = path.join(repoRoot, 'frontend', 'src', 'utils', 'securityUtils.js');
if (!fs.existsSync(security)) {
  throw new Error('Canonical wallet secure-storage implementation is missing');
}
for (const [name, sourceText, marker] of [
  ['native Ghost IPC handler', desktopMain, "ipcMain.handle('ghost-wallet-request'"],
  ['native Ghost sidecar spawn', desktopMain, 'ghost_wallet_bridge'],
  ['native Ghost spawn hardening', desktopMain, 'windowsHide: true'],
  ['constrained Ghost preload', desktopPreload, 'ghostWalletRequest'],
]) {
  if (!sourceText.includes(marker)) {
    throw new Error('Canonical ' + name + ' is missing');
  }
}
if (desktopPreload.includes('openWallet') || desktopPreload.includes('saveWallet')) {
  throw new Error('Ghost preload must not expose legacy wallet filesystem operations');
}
const signerSource = fs.readFileSync(signer, 'utf8');
const walletSource = fs.readFileSync(wallet, 'utf8');
const securitySource = fs.readFileSync(security, 'utf8');
for (const [name, sourceText, marker] of [
  ['signer intent guard', signerSource, 'export function assertStandardSendIntent'],
  ['wallet intent call', walletSource, 'assertStandardSendIntent(build.unsigned_tx'],
  ['wallet local txid binding', walletSource, 'canonicalTxidHex(signedTx)'],
  ['wallet returned txid check', walletSource, 'transaction ID that does not match'],
  ['fixed vault KDF policy', securitySource, 'iterations !== SECURE_STORAGE_KDF_ITERATIONS'],
]) {
  if (!sourceText.includes(marker)) {
    throw new Error(`Canonical ${name} is missing`);
  }
}
if (walletSource.includes('/api/wallet/login')) {
  throw new Error('Canonical wallet must never send a local vault password to a login endpoint');
}
if (
  !fs.existsSync(viteConfig)
  || frontendPackage.scripts?.build !== 'vite build'
  || frontendPackage.scripts?.test !== 'vitest run'
  || frontendPackage.devDependencies?.['react-scripts']
  || frontendPackage.devDependencies?.['@craco/craco']
) {
  throw new Error('Canonical wallet must use the audited Vite/Vitest toolchain');
}

const icon = path.join(desktopRoot, 'assets', 'icon.ico');
if (desktopPackage.build?.win?.icon !== 'assets/icon.ico' || !fs.existsSync(icon)) {
  throw new Error('Desktop package must use the project-owned Windows icon');
}

const releaseVerifier = path.join(
  desktopRoot,
  'scripts',
  'verify-windows-release.ps1',
);
const packageVerifier = path.join(
  desktopRoot,
  'scripts',
  'verify-packaged-desktop.js',
);
const builderSecurityVerifier = path.join(
  desktopRoot,
  'scripts',
  'verify-builder-security.js',
);
if (
  !fs.existsSync(releaseVerifier)
  || !fs.existsSync(packageVerifier)
  || !fs.existsSync(builderSecurityVerifier)
  || !desktopPackage.scripts?.['signing-preflight']?.includes('-PreflightOnly')
  || !desktopPackage.scripts?.['build-ghost-artifacts']
  || !desktopPackage.scripts?.['verify-packaged-desktop']
  || !desktopPackage.scripts?.['verify-builder-security']
  || !desktopPackage.scripts?.['dist-win']?.startsWith('npm run build-ghost-artifacts && npm run build-frontend &&')
  || !desktopPackage.scripts?.['dist-win']?.includes('verify-builder-security')
  || !desktopPackage.scripts?.['dist-win']?.includes('verify-windows-release')
) {
  throw new Error('Windows release packaging must remain fail-closed on signing');
}

console.log(
  'Desktop package uses hash-pinned Ghost artifacts, the canonical web wallet, project icon, and fail-closed signing gate.',
);
