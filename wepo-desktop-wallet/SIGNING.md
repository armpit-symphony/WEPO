# Windows Release Signing

`npm run pack` creates an unpacked **development** build. It may be unsigned and
must never be distributed as a release.

`npm run dist` and `npm run dist-win` are fail-closed release commands. They now:

1. verify that the canonical web wallet is the configured client;
2. require the approved certificate thumbprint and an available private signing
   credential before invoking `electron-builder`;
3. build the NSIS installer and ZIP;
4. require valid, timestamped Authenticode signatures on both the packaged
   wallet executable and the installer;
5. require every signer thumbprint to equal the explicitly approved thumbprint;
6. recheck every embedded PE icon frame byte-for-byte and the byte-identical
   frontend bundle; and
7. write `dist/release-verification.json` with artifact hashes and signer
   evidence.

## Required credential

Use a trusted production code-signing certificate or managed signing credential
approved for the WEPO publisher. A self-signed development certificate does not
satisfy release acceptance.

Set the following only in the current secured build environment or CI secret
store:

```powershell
$env:WEPO_WINDOWS_SIGNER_THUMBPRINT = "<40-character approved certificate thumbprint>"
$env:CSC_LINK = "C:\secure-path\wepo-release-signing.pfx"
$env:CSC_KEY_PASSWORD = "<secret supplied by the CI secret store>"
npm run dist-win
```

`WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` are also supported. `CSC_LINK` may be
an existing PFX path, base64 PFX content, or an HTTPS credential URL supported
by `electron-builder`. If the certificate and private key are installed in the
Windows CurrentUser or LocalMachine personal certificate store, `CSC_LINK` may
be omitted; the expected thumbprint is still mandatory and post-build
verification still rejects the wrong certificate.

Never commit a PFX, password, base64 credential, signing token, or private key.
The thumbprint is public certificate metadata and is required to prevent a
different locally available certificate from being accepted accidentally. It is
the conventional SHA-1 certificate identifier; artifact integrity is recorded
separately with SHA-256.

## Commands

```powershell
# Preflight only; creates no release artifact.
npm run signing-preflight

# Full fail-closed Windows release.
npm run dist-win

# Recheck already-built artifacts.
npm run verify-windows-release

# Recheck an unpacked development package without signing claims.
npm run verify-packaged-desktop
```

The release verifier requires a trusted timestamp on every signed executable so
the signature remains verifiable after the leaf certificate expires. A builder
log line mentioning `signtool.exe` is not evidence of signing; only
`Get-AuthenticodeSignature` status `Valid`, the approved signer thumbprint, and
the generated verification evidence satisfy this gate.
