[CmdletBinding()]
param(
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-ReleaseVerification {
    param([Parameter(Mandatory = $true)][string]$Message)
    throw "WEPO Windows release verification failed: $Message"
}

function Normalize-Thumbprint {
    param([string]$Thumbprint)
    $value = if ($null -eq $Thumbprint) { "" } else { $Thumbprint }
    return (($value -replace "\s", "").ToUpperInvariant())
}

function Get-ReleaseRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$FullPath
    )
    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd("\\") + "\\"
    $resolvedPath = [System.IO.Path]::GetFullPath($FullPath)
    if (
        $resolvedPath.StartsWith(
            $rootPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return $resolvedPath.Substring($rootPath.Length)
    }
    return $resolvedPath
}

function Test-CodeSigningEku {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate
    )

    foreach ($extension in $Certificate.Extensions) {
        if ($extension -isnot [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            continue
        }
        foreach ($oid in $extension.EnhancedKeyUsages) {
            if ($oid.Value -eq "1.3.6.1.5.5.7.3.3") {
                return $true
            }
        }
    }
    return $false
}

function Assert-CertificatePolicy {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedThumbprint,
        [switch]$RequirePrivateKey
    )

    if ((Normalize-Thumbprint $Certificate.Thumbprint) -ne $ExpectedThumbprint) {
        Stop-ReleaseVerification (
            "configured certificate thumbprint does not match " +
            "WEPO_WINDOWS_SIGNER_THUMBPRINT"
        )
    }
    if ($Certificate.NotBefore -gt (Get-Date)) {
        Stop-ReleaseVerification "configured signing certificate is not valid yet"
    }
    if ($Certificate.NotAfter -le (Get-Date)) {
        Stop-ReleaseVerification "configured signing certificate is expired"
    }
    if (-not (Test-CodeSigningEku $Certificate)) {
        Stop-ReleaseVerification "configured certificate lacks the Code Signing EKU"
    }
    if ($RequirePrivateKey -and -not $Certificate.HasPrivateKey) {
        Stop-ReleaseVerification "configured certificate does not expose a private key"
    }
}

function Find-CertificateInStore {
    param([Parameter(Mandatory = $true)][string]$ExpectedThumbprint)

    foreach ($storePath in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
        if (-not (Test-Path -LiteralPath $storePath)) {
            continue
        }
        $certificate = Get-ChildItem -LiteralPath $storePath |
            Where-Object {
                (Normalize-Thumbprint $_.Thumbprint) -eq $ExpectedThumbprint
            } |
            Select-Object -First 1
        if ($null -ne $certificate) {
            return $certificate
        }
    }
    return $null
}

function Read-PfxCertificate {
    param(
        [Parameter(Mandatory = $true)][string]$Link,
        [string]$Password
    )

    $bytes = $null
    if (Test-Path -LiteralPath $Link) {
        $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Link))
    }
    elseif ($Link -match "^https?://") {
        # electron-builder supports remote certificate links. The post-build
        # Authenticode check is authoritative, so do not download secrets here.
        return $null
    }
    else {
        try {
            $bytes = [Convert]::FromBase64String($Link)
        }
        catch {
            Stop-ReleaseVerification (
                "CSC_LINK/WIN_CSC_LINK is neither an existing PFX path, an " +
                "HTTPS URL, nor valid base64"
            )
        }
    }

    if ($null -eq $bytes) {
        return $null
    }

    $flags = (
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet -bor
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
    )
    try {
        $effectivePassword = if ($null -eq $Password) { "" } else { $Password }
        return [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
            $bytes,
            $effectivePassword,
            $flags
        )
    }
    catch {
        Stop-ReleaseVerification "unable to open the configured PFX certificate"
    }
}

$expectedThumbprint = Normalize-Thumbprint $env:WEPO_WINDOWS_SIGNER_THUMBPRINT
if ($expectedThumbprint -notmatch "^[A-F0-9]{40}$") {
    Stop-ReleaseVerification (
        "WEPO_WINDOWS_SIGNER_THUMBPRINT must be the 40-character SHA-1 " +
        "thumbprint of the approved release certificate"
    )
}

$certificateLink = $env:WIN_CSC_LINK
if ([string]::IsNullOrWhiteSpace($certificateLink)) {
    $certificateLink = $env:CSC_LINK
}
$certificatePassword = $env:WIN_CSC_KEY_PASSWORD
if ([string]::IsNullOrWhiteSpace($certificatePassword)) {
    $certificatePassword = $env:CSC_KEY_PASSWORD
}

$configuredCertificate = $null
if (-not [string]::IsNullOrWhiteSpace($certificateLink)) {
    $configuredCertificate = Read-PfxCertificate `
        -Link $certificateLink `
        -Password $certificatePassword
}
else {
    $configuredCertificate = Find-CertificateInStore `
        -ExpectedThumbprint $expectedThumbprint
    if ($null -eq $configuredCertificate) {
        Stop-ReleaseVerification (
            "no matching certificate was found in CSC_LINK/WIN_CSC_LINK or " +
            "the Windows CurrentUser/LocalMachine personal stores"
        )
    }
}

if ($null -ne $configuredCertificate) {
    Assert-CertificatePolicy `
        -Certificate $configuredCertificate `
        -ExpectedThumbprint $expectedThumbprint `
        -RequirePrivateKey
}

if ($PreflightOnly) {
    Write-Output (
        "PASS Windows signing preflight for expected certificate " +
        $expectedThumbprint
    )
    exit 0
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $desktopRoot
$distRoot = Join-Path $desktopRoot "dist"
$unpackedExecutable = Join-Path $distRoot "win-unpacked\WEPO Wallet.exe"
$iconPath = Join-Path $desktopRoot "assets\icon.ico"
$sourceFrontend = Join-Path $repoRoot "frontend\build"
$packedFrontend = Join-Path $distRoot "win-unpacked\resources\frontend"

foreach ($requiredPath in @(
    $unpackedExecutable,
    $iconPath,
    (Join-Path $sourceFrontend "index.html"),
    (Join-Path $packedFrontend "index.html")
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        Stop-ReleaseVerification "required release file is missing: $requiredPath"
    }
}

$installerExecutables = @(
    Get-ChildItem -LiteralPath $distRoot -File -Filter "*.exe"
)
$zipArtifacts = @(
    Get-ChildItem -LiteralPath $distRoot -File -Filter "*.zip"
)
if ($installerExecutables.Count -lt 1) {
    Stop-ReleaseVerification "the NSIS installer executable is missing"
}
if ($zipArtifacts.Count -lt 1) {
    Stop-ReleaseVerification "the Windows ZIP artifact is missing"
}

$signedExecutables = @($unpackedExecutable) + @(
    $installerExecutables | ForEach-Object { $_.FullName }
)
$artifactEvidence = @()
foreach ($executable in $signedExecutables) {
    $signature = Get-AuthenticodeSignature -LiteralPath $executable
    if ($signature.Status -ne "Valid") {
        Stop-ReleaseVerification (
            "$executable has Authenticode status $($signature.Status)"
        )
    }
    if ($null -eq $signature.SignerCertificate) {
        Stop-ReleaseVerification "$executable has no signer certificate"
    }
    Assert-CertificatePolicy `
        -Certificate $signature.SignerCertificate `
        -ExpectedThumbprint $expectedThumbprint
    if ($null -eq $signature.TimeStamperCertificate) {
        Stop-ReleaseVerification "$executable has no trusted timestamp"
    }

    $artifactEvidence += [ordered]@{
        path = Get-ReleaseRelativePath `
            -Root $desktopRoot `
            -FullPath $executable
        sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
        signer_subject = $signature.SignerCertificate.Subject
        signer_thumbprint = Normalize-Thumbprint $signature.SignerCertificate.Thumbprint
        signer_not_after = $signature.SignerCertificate.NotAfter.ToUniversalTime().ToString("o")
        timestamp_subject = $signature.TimeStamperCertificate.Subject
    }
}

$sourceIndex = Join-Path $sourceFrontend "index.html"
$packedIndex = Join-Path $packedFrontend "index.html"
$sourceMain = @(
    Get-ChildItem -LiteralPath (Join-Path $sourceFrontend "static\js") `
        -File -Filter "main.*.js"
)
$packedMain = @(
    Get-ChildItem -LiteralPath (Join-Path $packedFrontend "static\js") `
        -File -Filter "main.*.js"
)
if ($sourceMain.Count -ne 1 -or $packedMain.Count -ne 1) {
    Stop-ReleaseVerification "expected exactly one canonical main JavaScript bundle"
}

$frontendHashes = [ordered]@{
    source_index = (Get-FileHash -LiteralPath $sourceIndex -Algorithm SHA256).Hash
    packed_index = (Get-FileHash -LiteralPath $packedIndex -Algorithm SHA256).Hash
    source_main = (Get-FileHash -LiteralPath $sourceMain[0].FullName -Algorithm SHA256).Hash
    packed_main = (Get-FileHash -LiteralPath $packedMain[0].FullName -Algorithm SHA256).Hash
}
if ($frontendHashes.source_index -ne $frontendHashes.packed_index) {
    Stop-ReleaseVerification "packaged index.html differs from the canonical build"
}
if ($frontendHashes.source_main -ne $frontendHashes.packed_main) {
    Stop-ReleaseVerification "packaged main JavaScript differs from the canonical build"
}

$packageVerifier = Join-Path $PSScriptRoot "verify-packaged-desktop.js"
& node $packageVerifier
if ($LASTEXITCODE -ne 0) {
    Stop-ReleaseVerification "packaged desktop content verification failed"
}

foreach ($zipArtifact in $zipArtifacts) {
    $artifactEvidence += [ordered]@{
        path = Get-ReleaseRelativePath `
            -Root $desktopRoot `
            -FullPath $zipArtifact.FullName
        sha256 = (Get-FileHash -LiteralPath $zipArtifact.FullName -Algorithm SHA256).Hash
        signer_subject = $null
        signer_thumbprint = $null
        signer_not_after = $null
        timestamp_subject = $null
    }
}

$verificationEvidence = [ordered]@{
    schema = "wepo-windows-release-verification-v1"
    verified_at = (Get-Date).ToUniversalTime().ToString("o")
    expected_signer_thumbprint = $expectedThumbprint
    frontend_hashes = $frontendHashes
    embedded_icon_matches = $true
    artifacts = $artifactEvidence
}
$evidencePath = Join-Path $distRoot "release-verification.json"
$verificationEvidence |
    ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $evidencePath -Encoding UTF8

Write-Output "PASS signed Windows release verified"
Write-Output "Evidence: $evidencePath"
