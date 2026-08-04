const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const desktopRoot = path.resolve(__dirname, '..');
const lockPath = path.join(desktopRoot, 'package-lock.json');
const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));

// CVE-2026-14257 was fixed on each maintained brace-expansion line after the
// advisory database initially named only 5.0.8. Keep this fail-closed proof
// until scanners recognize the backports used by Electron Builder.
const patchedMinimum = new Map([
  [1, [1, 1, 17]],
  [2, [2, 1, 3]],
  [3, [3, 0, 5]],
  [5, [5, 0, 8]],
]);

function parseVersion(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if (!match) {
    throw new Error(`Unsupported brace-expansion version: ${version}`);
  }
  return match.slice(1).map(Number);
}

function atLeast(actual, minimum) {
  for (let index = 0; index < 3; index += 1) {
    if (actual[index] !== minimum[index]) {
      return actual[index] > minimum[index];
    }
  }
  return true;
}

const entries = Object.entries(lock.packages || {}).filter(
  ([packagePath]) => packagePath.endsWith('node_modules/brace-expansion'),
);
if (entries.length === 0) {
  throw new Error('No brace-expansion packages found in the desktop lockfile');
}

const representatives = new Map();
for (const [packagePath, metadata] of entries) {
  const version = metadata.version;
  const parsed = parseVersion(version);
  const minimum = patchedMinimum.get(parsed[0]);
  if (!minimum || !atLeast(parsed, minimum)) {
    throw new Error(
      `Unapproved brace-expansion release ${version} at ${packagePath}`,
    );
  }

  const installedRoot = path.join(desktopRoot, packagePath);
  const manifest = JSON.parse(
    fs.readFileSync(path.join(installedRoot, 'package.json'), 'utf8'),
  );
  if (manifest.version !== version) {
    throw new Error(
      `Lockfile/install mismatch at ${packagePath}: ${version} != ${manifest.version}`,
    );
  }

  const entryName = typeof manifest.main === 'string' ? manifest.main : 'index.js';
  const entryPath = path.join(installedRoot, entryName);
  const source = fs.readFileSync(entryPath, 'utf8');
  for (const marker of [
    'EXPANSION_MAX_LENGTH',
    'maxLength',
    'CVE-2026-14257',
  ]) {
    if (!source.includes(marker)) {
      throw new Error(
        `brace-expansion ${version} at ${packagePath} lacks ${marker}`,
      );
    }
  }
  if (!/4_?000_?000/.test(source)) {
    throw new Error(
      `brace-expansion ${version} at ${packagePath} lacks the 4M bound`,
    );
  }
  representatives.set(version, entryPath);
}

async function verifyRuntimeLimit(version, entryPath) {
  const imported = await import(pathToFileURL(entryPath).href);
  const expand =
    typeof imported.default === 'function' ? imported.default : imported.expand;
  if (typeof expand !== 'function') {
    throw new Error(`Cannot load brace-expansion ${version}`);
  }

  const maxLength = 10_000;
  const result = expand('{a,b}'.repeat(30), {
    max: 100_000,
    maxLength,
  });
  const totalLength = result.reduce((sum, item) => sum + item.length, 0);
  if (totalLength > maxLength) {
    throw new Error(
      `brace-expansion ${version} exceeded maxLength: ${totalLength}`,
    );
  }
  return totalLength;
}

(async () => {
  const verified = [];
  for (const [version, entryPath] of representatives) {
    const totalLength = await verifyRuntimeLimit(version, entryPath);
    verified.push({ version, totalLength });
  }
  console.log(
    JSON.stringify(
      {
        status: 'pass',
        advisory: 'GHSA-mh99-v99m-4gvg / CVE-2026-14257',
        lockedInstances: entries.length,
        verified,
      },
      null,
      2,
    ),
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
