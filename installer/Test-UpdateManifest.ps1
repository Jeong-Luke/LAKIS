param(
    [string]$ManifestPath = "",
    [string]$ExpectedVersion = "",
    [switch]$VerifyRemote,
    [ValidateRange(1, 10)][int]$Passes = 1,
    [string]$DraftReleaseTag = "",
    [string]$Repository = "Jeong-Luke/LAKIS"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $repo "manifests\update-latest.json"
}
$ManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json

if ($null -eq $manifest -or [string]::IsNullOrWhiteSpace([string]$manifest.version)) {
    throw "Manifest version is missing."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion) -and
    -not [string]::Equals([string]$manifest.version, $ExpectedVersion, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Manifest version '$($manifest.version)' does not match expected version '$ExpectedVersion'."
}
if ($null -eq $manifest.files -or $manifest.files.Count -eq 0) {
    throw "Manifest contains no update files."
}

$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lakis-update-preflight-" + [guid]::NewGuid().ToString("N"))
$draftReleasePrefix = if ([string]::IsNullOrWhiteSpace($DraftReleaseTag)) { "" } else {
    "https://github.com/$Repository/releases/download/$DraftReleaseTag/"
}
try {
    if ($VerifyRemote) { [System.IO.Directory]::CreateDirectory($temporaryRoot) | Out-Null }
    for ($index = 0; $index -lt $manifest.files.Count; $index++) {
        $item = $manifest.files[$index]
        $path = [string]$item.path
        $url = [string]$item.url
        $expectedHash = ([string]$item.sha256).ToUpperInvariant()
        if ([string]::IsNullOrWhiteSpace($path) -or [System.IO.Path]::IsPathRooted($path) -or $path.Replace('\', '/').Split('/') -contains '..') {
            throw "Unsafe or empty update path: $path"
        }
        if (-not $seen.Add($path)) { throw "Duplicate update path: $path" }
        if ($url -notmatch '^https://') { throw "Update URL must use HTTPS: $path" }
        if ($expectedHash -notmatch '^[0-9A-F]{64}$') { throw "Invalid SHA-256 value: $path" }
        if (-not $VerifyRemote) { continue }

        for ($pass = 1; $pass -le $Passes; $pass++) {
            $download = Join-Path $temporaryRoot ("{0:D2}-{1:D4}.bin" -f $pass, $index)
            if (-not [string]::IsNullOrWhiteSpace($draftReleasePrefix) -and
                $url.StartsWith($draftReleasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                # A draft release is intentionally not exposed through its public
                # browser_download_url. Download the exact staged asset through
                # authenticated gh instead, then hash those bytes before publish.
                $assetName = [System.Uri]::UnescapeDataString($url.Substring($draftReleasePrefix.Length))
                if ([string]::IsNullOrWhiteSpace($assetName) -or $assetName.Contains('/')) {
                    throw "Invalid draft release asset URL: $url"
                }
                $draftDirectory = Join-Path $temporaryRoot ("draft-{0:D2}-{1:D4}" -f $pass, $index)
                New-Item -ItemType Directory -Force -Path $draftDirectory | Out-Null
                $ghOutput = & gh release download $DraftReleaseTag --repo $Repository --pattern $assetName --dir $draftDirectory --clobber 2>&1
                if ($LASTEXITCODE -ne 0) {
                    throw "Draft release asset download failed: $assetName`n$($ghOutput -join [Environment]::NewLine)"
                }
                $draftDownload = Join-Path $draftDirectory $assetName
                if (-not (Test-Path -LiteralPath $draftDownload -PathType Leaf)) {
                    throw "Draft release asset was not downloaded: $assetName"
                }
                Move-Item -LiteralPath $draftDownload -Destination $download -Force
            }
            else {
                $separator = if ($url.Contains('?')) { '&' } else { '?' }
                $nonce = "{0}_{1}_{2}" -f [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(), $pass, [guid]::NewGuid().ToString("N")
                Invoke-WebRequest -UseBasicParsing -Headers @{
                    "User-Agent" = "LAKIS-Update-Preflight/$($manifest.version)"
                    "Cache-Control" = "no-cache, no-store, must-revalidate"
                    "Pragma" = "no-cache"
                } -Uri ($url + $separator + "preflight=" + $nonce) -OutFile $download
            }
            $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash.ToUpperInvariant()
            if ($actualHash -ne $expectedHash) {
                throw "Published file hash mismatch (pass $pass/$Passes): $path`nexpected=$expectedHash`nactual=$actualHash`nurl=$url"
            }
            Write-Output ("VERIFIED pass={0}/{1} file={2}/{3}: {4}" -f $pass, $Passes, ($index + 1), $manifest.files.Count, $path)
        }
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}

Write-Output "UPDATE_PREFLIGHT_OK version=$($manifest.version) files=$($manifest.files.Count) remote=$VerifyRemote passes=$Passes"
