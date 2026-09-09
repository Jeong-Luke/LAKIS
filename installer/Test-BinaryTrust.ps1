param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactDirectory,
    [switch]$RequireSigned,
    [switch]$RunDefenderScan
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$executables = @(Get-ChildItem -LiteralPath $root -Filter "*.exe" -File)
if (-not $executables) { throw "No executable artifacts were found in $root" }

foreach ($file in $executables) {
    $version = $file.VersionInfo
    if ([string]::IsNullOrWhiteSpace($version.ProductName) -or
        [string]::IsNullOrWhiteSpace($version.CompanyName) -or
        [string]::IsNullOrWhiteSpace($version.FileVersion)) {
        throw "Required Windows version metadata is missing: $($file.Name)"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($RequireSigned -and $signature.Status -ne "Valid") {
        throw "Release artifact is not validly Authenticode-signed: $($file.Name) ($($signature.Status))"
    }
    Write-Output "BINARY_TRUST name=$($file.Name) signature=$($signature.Status) version=$($version.FileVersion) sha256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash)"
}

if ($RunDefenderScan) {
    $platformRoot = Join-Path $env:ProgramData "Microsoft\Windows Defender\Platform"
    $mpCmdRun = Get-ChildItem -LiteralPath $platformRoot -Filter "MpCmdRun.exe" -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $mpCmdRun) { throw "Microsoft Defender command-line scanner was not found." }
    & $mpCmdRun.FullName -Scan -ScanType 3 -File $root -DisableRemediation
    if ($LASTEXITCODE -ne 0) { throw "Microsoft Defender reported a problem or could not complete the scan (exit $LASTEXITCODE)." }
    Write-Output "DEFENDER_SCAN_OK path=$root"
}

