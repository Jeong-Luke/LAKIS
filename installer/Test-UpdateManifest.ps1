param(
    [string]$ManifestPath = "",
    [string]$ExpectedVersion = "",
    [switch]$VerifyRemote
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

        $download = Join-Path $temporaryRoot ("{0:D4}.bin" -f $index)
        $separator = if ($url.Contains('?')) { '&' } else { '?' }
        Invoke-WebRequest -UseBasicParsing -Headers @{ "User-Agent" = "LAKIS-Update-Preflight/$($manifest.version)" } `
            -Uri ($url + $separator + "preflight=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -OutFile $download
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash.ToUpperInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "Published file hash mismatch: $path`nexpected=$expectedHash`nactual=$actualHash`nurl=$url"
        }
        Write-Output ("VERIFIED {0}/{1}: {2}" -f ($index + 1), $manifest.files.Count, $path)
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}

Write-Output "UPDATE_PREFLIGHT_OK version=$($manifest.version) files=$($manifest.files.Count) remote=$VerifyRemote"
