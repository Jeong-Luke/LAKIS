param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS",
    [string]$DistDirectory = "",
    [switch]$UseLocalWorkingTreeHashes
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$dist = if ([string]::IsNullOrWhiteSpace($DistDirectory)) {
    Join-Path $workspace "dist"
} else {
    [System.IO.Path]::GetFullPath($DistDirectory)
}
$tag = "v$Version"
$releaseBase = "https://github.com/$Repository/releases/download/$tag"
$rawBase = "https://raw.githubusercontent.com/$Repository/$tag"

$files = [System.Collections.Generic.List[object]]::new()
function Add-UpdateFile([string]$InstallPath, [string]$SourcePath, [string]$Url) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Update source is missing: $SourcePath"
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePath).Hash
    # GitHub serves repository text with the line endings stored in Git. A
    # Windows working tree can contain CRLF bytes for the same LF-tagged file,
    # so release manifests must hash the published bytes by default.
    if (-not $UseLocalWorkingTreeHashes -and $Url.StartsWith($rawBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("lakis-tag-hash-" + [guid]::NewGuid().ToString("N"))
        try {
            Invoke-WebRequest -UseBasicParsing -Headers @{ "User-Agent" = "LAKIS-Manifest/$Version" } `
                -Uri ($Url + "?manifest=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -OutFile $temporary
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash
        }
        finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
    }
    $files.Add([ordered]@{
        path = $InstallPath.Replace('\', '/')
        url = $Url
        sha256 = $hash
    })
}

foreach ($name in @(
    "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Desktop.exe", "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll"
)) {
    Add-UpdateFile $name (Join-Path $dist $name) "$releaseBase/$name"
}

# The entire external UI is an atomic runtime component. Selecting individual
# files caused workflow_bridge.py to remain on an older release.
$externalRoot = Join-Path $repo "src\external_ui"
Get-ChildItem -LiteralPath $externalRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($externalRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/LAKIS_DEV/external_ui/$relative" $_.FullName "$rawBase/src/external_ui/$relative"
    }

# This is application-owned and safe to update. The editable workflow under
# ComfyUI/user is deliberately excluded because it contains user changes.
foreach ($runtimeName in @(
    "LAKIS_runtime_api_v7.1.json",
    "LAKIS_runtime_visual_v7.1.json",
    "LAKIS_custom_v7.1_editable.json"
)) {
    Add-UpdateFile "ComfyUI/LAKIS/workflows/$runtimeName" `
        (Join-Path $repo "workflows\$runtimeName") "$rawBase/workflows/$runtimeName"
}

$manifest = [ordered]@{
    version = $Version
    release_notes = "LAKIS $Version 업데이트"
    files = $files
    delete = @()
}
$output = Join-Path $repo "manifests\update-latest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
Write-Output "MANIFEST=$output"
Write-Output "FILES=$($files.Count)"
