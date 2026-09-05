param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$dist = Join-Path $workspace "dist"
$tag = "v$Version"
$releaseBase = "https://github.com/$Repository/releases/download/$tag"
$rawBase = "https://raw.githubusercontent.com/$Repository/$tag"

$files = [System.Collections.Generic.List[object]]::new()
function Add-UpdateFile([string]$InstallPath, [string]$SourcePath, [string]$Url) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Update source is missing: $SourcePath"
    }
    $files.Add([ordered]@{
        path = $InstallPath.Replace('\', '/')
        url = $Url
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePath).Hash
    })
}

foreach ($name in @(
    "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Desktop.exe",
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
$runtimeName = "LAKIS_runtime_api_v7.1.json"
Add-UpdateFile "ComfyUI/LAKIS/workflows/$runtimeName" `
    (Join-Path $repo "workflows\$runtimeName") "$rawBase/workflows/$runtimeName"

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
