const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const PELibrary = require('pe-library');
const ResEdit = require('resedit');

const desktopRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(desktopRoot, '..');
const unpackedRoot = process.env.WEPO_DESKTOP_UNPACKED_ROOT
  ? path.resolve(process.env.WEPO_DESKTOP_UNPACKED_ROOT)
  : path.join(desktopRoot, 'dist', 'win-unpacked');
const executablePath = path.join(unpackedRoot, 'WEPO Wallet.exe');
const sourceFrontend = path.join(repoRoot, 'frontend', 'build');
const packedFrontend = path.join(unpackedRoot, 'resources', 'frontend');
const iconPath = path.join(desktopRoot, 'assets', 'icon.ico');
const evidencePrefix = '--evidence=';
const evidenceArgument = process.argv
  .slice(2)
  .find((argument) => argument.startsWith(evidencePrefix));
const evidencePath = evidenceArgument
  ? path.resolve(evidenceArgument.slice(evidencePrefix.length))
  : null;
if (evidencePath && fs.existsSync(evidencePath)) {
  fail(`evidence output already exists: ${evidencePath}`);
}

function fail(message) {
  throw new Error(`Packaged desktop verification failed: ${message}`);
}

function requireFile(filePath) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    fail(`required file is missing: ${filePath}`);
  }
}

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function fileSha256(filePath) {
  return sha256(fs.readFileSync(filePath));
}

function findMainBundle(root) {
  const directory = path.join(root, 'static', 'js');
  if (!fs.existsSync(directory)) {
    fail(`JavaScript bundle directory is missing: ${directory}`);
  }
  const matches = fs
    .readdirSync(directory)
    .filter((name) => /^main\..+\.js$/.test(name) && !name.endsWith('.map'));
  if (matches.length !== 1) {
    fail(`expected exactly one main JavaScript bundle in ${directory}`);
  }
  return path.join(directory, matches[0]);
}

function iconBytes(icon) {
  return Buffer.from(icon.isRaw() ? icon.bin : icon.generate());
}

function verifyIconResources() {
  const sourceIcon = ResEdit.Data.IconFile.from(fs.readFileSync(iconPath));
  const executable = PELibrary.NtExecutable.from(
    fs.readFileSync(executablePath),
    { ignoreCert: true },
  );
  const resources = PELibrary.NtExecutableResource.from(executable);
  const groups = ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries);

  if (groups.length !== 1) {
    fail(`expected one executable icon group, found ${groups.length}`);
  }

  const embeddedIcons = groups[0].getIconItemsFromEntries(resources.entries);
  if (sourceIcon.icons.length !== embeddedIcons.length) {
    fail(
      `icon frame count differs: source=${sourceIcon.icons.length}, ` +
        `embedded=${embeddedIcons.length}`,
    );
  }

  const frameHashes = [];
  for (let index = 0; index < sourceIcon.icons.length; index += 1) {
    const sourceFrame = iconBytes(sourceIcon.icons[index].data);
    const embeddedFrame = iconBytes(embeddedIcons[index]);
    if (!sourceFrame.equals(embeddedFrame)) {
      fail(`embedded icon frame ${index} differs from assets/icon.ico`);
    }
    frameHashes.push(sha256(sourceFrame));
  }
  return frameHashes;
}

requireFile(executablePath);
requireFile(iconPath);

const sourceIndex = path.join(sourceFrontend, 'index.html');
const packedIndex = path.join(packedFrontend, 'index.html');
requireFile(sourceIndex);
requireFile(packedIndex);

const sourceMain = findMainBundle(sourceFrontend);
const packedMain = findMainBundle(packedFrontend);
const hashes = {
  source_index: fileSha256(sourceIndex),
  packed_index: fileSha256(packedIndex),
  source_main: fileSha256(sourceMain),
  packed_main: fileSha256(packedMain),
};
if (hashes.source_index !== hashes.packed_index) {
  fail('packaged index.html differs from the canonical frontend build');
}
if (hashes.source_main !== hashes.packed_main) {
  fail('packaged main JavaScript differs from the canonical frontend build');
}

const requiredWalletSecurityMarkers = [
  'Refusing to sign: ',
  'node changed the approved recipient or amount',
  'Local wallet password is incorrect, or the encrypted vault is incomplete',
  'Node returned a transaction ID that does not match the signed transaction',
];
const packedMainSource = fs.readFileSync(packedMain, 'utf8');
for (const marker of requiredWalletSecurityMarkers) {
  if (!packedMainSource.includes(marker)) {
    fail(`packaged wallet security marker is missing: ${marker}`);
  }
}
const evidence = {
  schema: 'wepo-packaged-desktop-content-v1',
  verified_at: new Date().toISOString(),
  unpacked_root: unpackedRoot,
  authenticode_checked: false,
  executable_sha256: fileSha256(executablePath),
  frontend_hashes: hashes,
  wallet_security_markers: requiredWalletSecurityMarkers,
  icon_frame_sha256: verifyIconResources(),
};

console.log('PASS packaged desktop content verified');
console.log(JSON.stringify(evidence, null, 2));
if (evidencePath) {
  fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
  });
  console.log(`Evidence: ${evidencePath}`);
}
