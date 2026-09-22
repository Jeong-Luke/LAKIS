param(
    [string]$DistDirectory = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dist = if ([string]::IsNullOrWhiteSpace($DistDirectory)) {
    Join-Path $repo "dist"
} else {
    [System.IO.Path]::GetFullPath($DistDirectory)
}

if (-not (Test-Path -LiteralPath $dist -PathType Container)) {
    throw "Public artifact directory is missing: $dist"
}

$forbiddenPathPattern = '(?i)(LAKIS_DEV|DEKIS|LUKIS|LAKIS_LUKE|DEV_VERSION|LUKE_VERSION|LAKIS_DEV_red|LUKIS_Desktop|Start_LUKIS_Mobile)'
$badFiles = @(Get-ChildItem -LiteralPath $dist -Recurse -File | Where-Object {
    $_.FullName.Substring($dist.Length) -match $forbiddenPathPattern
})
if ($badFiles.Count) {
    throw "Public artifact directory contains private/development files: $($badFiles.FullName -join ', ')"
}
$requiredBinaries = @(
    "LAKIS.exe",
    "LAKIS_Patcher.exe",
    "LAKIS_Updater.exe",
    "LAKIS_Desktop.exe",
    "LAKIS_Model_Importer.exe",
    "Uninstall_LAKIS.exe",
    "LAKIS_Setup.exe"
)
$strictTokens = @(
    "DEKIS",
    "LUKIS",
    "LAKIS Studio DEV",
    "LUKIS Studio",
    "LAKIS_DEV_Desktop.exe",
    "LUKIS_Desktop.exe",
    "Start_LUKIS_Mobile.cmd",
    "DEV_VERSION",
    "LUKE_VERSION",
    ".lakis-dev",
    ".lukis"
)

function Assert-NoTokens([string]$Path, [string[]]$Tokens) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
    $evenLength = $bytes.Length - ($bytes.Length % 2)
    $unicodeEven = if ($evenLength -gt 0) {
        [System.Text.Encoding]::Unicode.GetString($bytes, 0, $evenLength)
    } else { "" }
    $oddCount = [Math]::Max(0, $bytes.Length - 1)
    $oddCount -= ($oddCount % 2)
    $unicodeOdd = if ($oddCount -gt 0) {
        [System.Text.Encoding]::Unicode.GetString($bytes, 1, $oddCount)
    } else { "" }
    $hits = @($Tokens | Where-Object {
        $ascii.Contains($_) -or $unicodeEven.Contains($_) -or $unicodeOdd.Contains($_)
    })
    if ($hits.Count) {
        throw "Public binary contains private/development product strings: $Path -> $($hits -join ', ')"
    }
}

foreach ($name in $requiredBinaries) {
    $path = Join-Path $dist $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required public binary is missing: $path"
    }
}
$scanBinaries = @(Get-ChildItem -LiteralPath $dist -File -Filter "*.exe" | Sort-Object FullName)
foreach ($binary in $scanBinaries) {
    Assert-NoTokens $binary.FullName $strictTokens
}

Write-Output "PUBLIC_PRODUCT_BOUNDARY_OK binaries=$($scanBinaries.Count)"
