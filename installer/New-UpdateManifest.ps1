param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS",
    [string]$DistDirectory = "",
    [string]$OutputPath = "",
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
    "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll"
)) {
    Add-UpdateFile $name (Join-Path $dist $name) "$releaseBase/$name"
}

# Legal notices are application-owned release files. Existing installations
# must receive the same notices as clean installs.
foreach ($name in @("LICENSE.md", "THIRD_PARTY_NOTICES.md")) {
    Add-UpdateFile $name (Join-Path $repo $name) "$rawBase/$name"
}
$licenceRoot = Join-Path $repo "third_party_licenses"
Get-ChildItem -LiteralPath $licenceRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($licenceRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "third_party_licenses/$relative" $_.FullName "$rawBase/third_party_licenses/$relative"
    }

# Never put a model path in the update manifest. Updaters shipped with 7.2.2
# and 7.2.3 correctly protect the whole ComfyUI/models tree and would reject
# the update before the new patcher could replace them. The UI downloads
# the permissively licensed RealESRGAN default on selection and verifies its
# pinned SHA-256 instead.

# The entire external UI is an atomic runtime component. Selecting individual
# files caused workflow_bridge.py to remain on an older release.
$externalRoot = Join-Path $repo "src\external_ui"
Get-ChildItem -LiteralPath $externalRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($externalRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/LAKIS/external_ui/$relative" $_.FullName "$rawBase/src/external_ui/$relative"
    }

# Ship the DSINE-free lighting stub to existing users as well as clean
# installs. The directory is LAKIS-owned; cached third-party weights and all
# other user/custom-node data remain untouched.
$lightControlRoot = Join-Path $repo "src\custom_nodes\ComfyUI-LAKIS-Light-Control"
Get-ChildItem -LiteralPath $lightControlRoot -File -Recurse |
    Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
        $_.Extension -ne '.pyc' -and
        $_.Name -ne 'TEST_NOTES.txt'
    } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($lightControlRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/$relative" $_.FullName `
            "$rawBase/src/custom_nodes/ComfyUI-LAKIS-Light-Control/$relative"
    }

# LAKIS_SCOPE is an independent LAKIS-owned custom node. Existing users need
# the complete package; user models and third-party custom nodes are untouched.
$scopeRoot = Join-Path $repo "src\custom_nodes\ComfyUI-LAKIS-Fast-Refiner"
Get-ChildItem -LiteralPath $scopeRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($scopeRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Fast-Refiner/$relative" $_.FullName `
            "$rawBase/src/custom_nodes/ComfyUI-LAKIS-Fast-Refiner/$relative"
    }

# Keep the packaged camera-to-prompt bridge workflow synchronized without
# touching any user workflow files.
$cameraBridgeRoot = Join-Path $repo "src\custom_nodes\ComfyUI-KR-Camera-PromptStudio-Bridge"
$cameraBridgeMatches = @(Get-ChildItem -LiteralPath $cameraBridgeRoot -File -Filter "KR_Camera_Anima_*_ONOFF.json")
if ($cameraBridgeMatches.Count -ne 1) {
    throw "Expected exactly one packaged KR Camera Anima bridge workflow; found $($cameraBridgeMatches.Count)."
}
$cameraBridgeFile = $cameraBridgeMatches[0].Name
Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-KR-Camera-PromptStudio-Bridge/$cameraBridgeFile" `
    $cameraBridgeMatches[0].FullName `
    "$rawBase/src/custom_nodes/ComfyUI-KR-Camera-PromptStudio-Bridge/$cameraBridgeFile"

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

$releaseNotesBase64 = "7IOI66Gc7Jq0IOyXheyKpOy8gOydvCDsspjrpqwg67Cp7IudKExBS0lTX1NDT1BFKSDstpTqsIAKTEFLSVNfU0NPUEXripQg7LKY66asIOqzvOygleydhCDstZzsoIHtmZTtlZjsl6wg6riw7KG0IOuwqeyLnShVbHRpbWF0ZSBTRCBVcHNjYWxlKeqzvCDsnKDsgqztlZwg7ZKI7KeI7J2EIOycoOyngO2VmOuptOyEnCDsspjrpqwg7Iuc6rCE7J2EIOy1nOuMgCAzMCUg64uo7LaV7ZWp64uI64ukLiDsg53shLEg66qo65Oc7J2YIOyEuOu2gCDshKTsoJXsl5DshJwg65GQIOyymOumrCDrsKnsi50g7KSRIOybkO2VmOuKlCDrsKnsi53snYQg7ISg7YOd7ZWgIOyImCDsnojsnLzrqbAsIOq4sOuzuCDsspjrpqwg67Cp7Iud7J2AIOq4sOyhtCBVbHRpbWF0ZSBTRCBVcHNjYWxl66GcIOycoOyngOuQqeuLiOuLpC4KCuyymOumrCDsi5zqsITsnYAg6re4656Y7ZS97Lm065OcLCDtlbTsg4Hrj4QsIOyXheyKpOy8gOydvOufrCDrqqjrjbgg67CPIOydtOuvuOyngCDrs7XsnqHrj4Tsl5Ag65Sw6528IOuLrOudvOyniCDsiJgg7J6I7Iq164uI64ukLgoK7Jik66WYIOynhOuLqCDsoJXrs7Qg67CPIOyytO2BrO2PrOyduO2KuCDtmLjtmZjshLEg6rCc7ISgCkxvUkEg66ek64uI7KCAIOyCrOyaqSDtm4QgTEFLSVMg67O16reAIOyLnCDrqqnroZ0g7J6Q64+ZIOqwseyLoApMb1JBIOyEoO2DneywveydmCDqsoDsg4nCt+yLpOyLnOqwhCDtlYTthLDrp4HCt+ykkeuztSDsoJzsmbgg6riw64qlIOqwnOyEoA=="
$releaseNotes = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($releaseNotesBase64)).Replace("\n", [Environment]::NewLine)
$manifest = [ordered]@{
    version = $Version
    release_notes = $releaseNotes
    files = $files
    delete = @()
}
$output = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $repo "manifests\update-latest.json"
} else {
    [System.IO.Path]::GetFullPath($OutputPath)
}
$outputDirectory = Split-Path -Parent $output
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
Write-Output "MANIFEST=$output"
Write-Output "FILES=$($files.Count)"
