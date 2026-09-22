param(
    [string]$DistDirectory = "",
    [string]$OutputPath = "",
    [string]$RepairPackPath = "",
    [switch]$UseWorkingTree
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dist = if ($DistDirectory) { [IO.Path]::GetFullPath($DistDirectory) } else { Join-Path $repo "dist" }
if (-not (Test-Path -LiteralPath $dist -PathType Container)) { throw "Missing dist directory: $dist" }

$output = if ($OutputPath) { [IO.Path]::GetFullPath($OutputPath) } else { Join-Path $dist "release-layout.json" }
$pack = if ($RepairPackPath) { [IO.Path]::GetFullPath($RepairPackPath) } else { Join-Path $dist "LAKIS_RepairPack.zip" }
$version = (Get-Content -Raw -LiteralPath (Join-Path $repo "VERSION")).Trim()
if ([string]::IsNullOrWhiteSpace($version)) { throw "VERSION is empty." }

$temp = Join-Path ([IO.Path]::GetTempPath()) ("lakis-layout-" + [guid]::NewGuid().ToString("N"))
$snapshot = Join-Path $temp "source"
$payload = Join-Path $temp "payload"
New-Item -ItemType Directory -Force $snapshot,$payload | Out-Null

try {
    $source = $snapshot
    if ($UseWorkingTree) {
        $source = $repo
    } else {
        $archive = Join-Path $temp "source.zip"
        & git -C $repo archive --format=zip -o $archive HEAD -- VERSION LICENSE.md THIRD_PARTY_NOTICES.md third_party_licenses resources src workflows
        if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
        Expand-Archive -LiteralPath $archive -DestinationPath $snapshot
    }

    function Copy-ManagedFile([string]$InstallPath, [string]$SourcePath) {
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
            throw "Missing managed source: $SourcePath"
        }
        $target = Join-Path $payload ($InstallPath.Replace("/", "\"))
        New-Item -ItemType Directory -Force (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $SourcePath -Destination $target -Force
    }

    $rootAssets = @(
        "LAKIS.exe",
        "LAKIS_Patcher.exe",
        "LAKIS_Updater.exe",
        "LAKIS_Desktop.exe",
        "LAKIS_Model_Importer.exe",
        "Uninstall_LAKIS.exe",
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebView2Loader.dll"
    )
    foreach ($name in $rootAssets) {
        Copy-ManagedFile $name (Join-Path $dist $name)
    }

    foreach ($name in @("VERSION","LICENSE.md","THIRD_PARTY_NOTICES.md")) {
        Copy-ManagedFile $name (Join-Path $source $name)
    }

    $licenseRoot = Join-Path $source "third_party_licenses"
    Get-ChildItem -LiteralPath $licenseRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($licenseRoot.Length).TrimStart("\").Replace("\","/")
        Copy-ManagedFile "third_party_licenses/$relative" $_.FullName
    }

    $externalRoot = Join-Path $source "src\external_ui"
    Get-ChildItem -LiteralPath $externalRoot -File -Recurse | Where-Object {
        $_.Name -ne "release-integrity.json" -and
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
        $_.Extension -ne ".pyc"
    } | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($externalRoot.Length).TrimStart("\").Replace("\","/")
        Copy-ManagedFile "ComfyUI/LAKIS/external_ui/$relative" $_.FullName
    }

    Copy-ManagedFile "ComfyUI/LAKIS/STOP_AUTOMATION" (Join-Path $source "resources\STOP_AUTOMATION")
    Copy-ManagedFile "ComfyUI/LAKIS/sync_runtime_workflow.py" (Join-Path $source "src\runtime\sync_runtime_workflow.py")

    foreach ($name in @(
        "LAKIS_runtime_api_v7.4.json",
        "LAKIS_runtime_visual_v7.4.json",
        "LAKIS_custom_v7.4_editable.json"
    )) {
        Copy-ManagedFile "ComfyUI/LAKIS/workflows/$name" (Join-Path $source "workflows\$name")
    }

    $packageNames = @(
        Get-Content -LiteralPath (Join-Path $source "resources\PRODUCTION_NODE_PACKAGES.txt") |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") }
    )
    foreach ($package in $packageNames) {
        if ($package -notmatch '^[A-Za-z0-9_-]+$') { throw "Invalid package name: $package" }
        $packageRoot = Join-Path $source "src\custom_nodes\$package"
        Get-ChildItem -LiteralPath $packageRoot -File -Recurse | Where-Object {
            $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
            $_.Extension -ne ".pyc" -and
            $_.Name -ne "startup_workflow.json"
        } | Sort-Object FullName | ForEach-Object {
            $relative = $_.FullName.Substring($packageRoot.Length).TrimStart("\").Replace("\","/")
            Copy-ManagedFile "ComfyUI/custom_nodes/$package/$relative" $_.FullName
        }
    }

    $protectedPattern = '^(?i)ComfyUI/(models|user|input|output)/'
    $files = @(
        Get-ChildItem -LiteralPath $payload -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($payload.Length).TrimStart("\").Replace("\","/")
            if ($relative -match $protectedPattern) {
                throw "User-owned path entered release layout: $relative"
            }
            if ($relative -match '(?i)^ComfyUI/user/' -or
                ($relative -match '(?i)(^|/)LAKIS_custom_.*_editable\.json$' -and
                 $relative -ne "ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json")) {
                throw "User-editable workflow entered release layout: $relative"
            }
            [ordered]@{
                path = $relative
                size = [int64]$_.Length
            }
        }
    )

    $retired = @(
        "ComfyUI/LAKIS/external_ui/light-control-prototype.css",
        "ComfyUI/LAKIS/external_ui/lightmap-knob-mockup.js",
        "ComfyUI/LAKIS/workflows/LAKIS_DETAIL_runtime_api_v7.3.json",
        "ComfyUI/LAKIS/workflows/LAKIS_custom_v7.3_editable.json",
        "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.1.json",
        "ComfyUI/LAKIS/workflows/LAKIS_runtime_visual_v7.3.json",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/INSTALL_REQUIREMENTS.bat",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/LICENSE",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/NOTICE.md",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/requirements.txt",
        "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/web/lakis_light_control.js"
    )

    $layout = [ordered]@{
        schema = 1
        product = "LAKIS"
        version = $version
        files = $files
        retired = $retired
    }

    New-Item -ItemType Directory -Force (Split-Path -Parent $output),(Split-Path -Parent $pack) | Out-Null
    [IO.File]::WriteAllText(
        $output,
        (($layout | ConvertTo-Json -Depth 6) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )

    if (Test-Path -LiteralPath $pack) { Remove-Item -LiteralPath $pack -Force }
    Compress-Archive -Path (Join-Path $payload "*") -DestinationPath $pack -CompressionLevel Optimal

    Write-Output "RELEASE_LAYOUT=$output"
    Write-Output "REPAIR_PACK=$pack"
    Write-Output "FILES=$($files.Count)"
}
finally {
    if (Test-Path -LiteralPath $temp) {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
