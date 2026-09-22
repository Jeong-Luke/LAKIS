param(
    [string]$OutputPath = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$textExtensions = @(".py",".js",".css",".html",".json",".md",".txt",".csv",".yml",".yaml",".toml",".ps1",".cs",".svg")
$includeFiles = @(
    ".github\workflows\publish-installer.yml",
    ".github\workflows\prepare-private-rc.yml",
    "VERSION",
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "ERROR_CODES.md",
    "RELEASE_REGRESSION_CHECKLIST.md",
    "THREE_PARTY_AUDIT_POLICY.md"
)
$includeRoots = @("installer","resources","src","workflows","third_party_licenses")
$script:records = @()

function Get-CanonicalHash([string]$Path) {
    $ext = [IO.Path]::GetExtension($Path).ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        if ($textExtensions -contains $ext -or [string]::IsNullOrEmpty($ext)) {
            $text = [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)
            $text = $text.Replace(([char]13 + [char]10),[string][char]10).Replace([string][char]13,[string][char]10)
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
            return @("text-lf",([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-",""))
        }
        $stream = [IO.File]::OpenRead($Path)
        try { return @("binary",([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-","")) }
        finally { $stream.Dispose() }
    } finally { $sha.Dispose() }
}

function Add-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $rel = [IO.Path]::GetFullPath($Path).Substring($repo.Length).TrimStart("\").Replace("\","/")
    if ($rel -match '(^|/)(__pycache__|dist|build|runs|state|release_audits)(/|$)' -or
        $rel -match '(?i)(\.pyc$|\.bak$|\.tmp$|\.old$)') { return }
    $h = Get-CanonicalHash $Path
    $script:records += [pscustomobject]@{ path=$rel; mode=$h[0]; sha256=$h[1] }
}

foreach ($rel in $includeFiles) { Add-File (Join-Path $repo $rel) }
foreach ($dir in $includeRoots) {
    $base = Join-Path $repo $dir
    if (-not (Test-Path -LiteralPath $base -PathType Container)) { continue }
    Get-ChildItem -LiteralPath $base -File -Recurse | Sort-Object FullName | ForEach-Object { Add-File $_.FullName }
}
$records = @($script:records | Sort-Object path -Unique)
$sep = [string][char]9
$nl = [string][char]10
$canonical = ($records | ForEach-Object { $_.path + $sep + $_.mode + $sep + $_.sha256 }) -join $nl
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $fingerprint = ([BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($canonical)))).Replace("-","")
} finally { $sha.Dispose() }

$result = [ordered]@{
    schema = 1
    version = (Get-Content -Raw -LiteralPath (Join-Path $repo "VERSION")).Trim()
    base_commit = (& git -C $repo rev-parse HEAD).Trim()
    fingerprint_sha256 = $fingerprint
    file_count = $records.Count
}
$json = $result | ConvertTo-Json -Depth 4
if ($OutputPath) {
    $full = [IO.Path]::GetFullPath($OutputPath)
    [IO.Directory]::CreateDirectory((Split-Path -Parent $full)) | Out-Null
    [IO.File]::WriteAllText($full,$json+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
}
Write-Output $json
