param(
    [Parameter(Mandatory = $true)][string]$BaseRuntimeRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Version = "8.0.0"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$base = (Resolve-Path -LiteralPath $BaseRuntimeRoot).Path
$output = [IO.Path]::GetFullPath($OutputRoot)
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (Test-Path -LiteralPath $output) { throw "OutputRoot already exists: $output" }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must be major.minor.patch." }
foreach ($relative in @("ComfyUI\main.py", "python_embeded\python.exe", "RUNTIME_SHA256SUMS.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $base $relative) -PathType Leaf)) {
        throw "Base runtime is incomplete: $relative"
    }
}
if (-not (Test-Path -LiteralPath $csc -PathType Leaf)) { throw "C# compiler not found: $csc" }

$revision = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[a-fA-F0-9]{40}$') { throw "Committed source revision required." }
$dirty = & git -C $repo status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $dirty) { throw "Tracked source must be committed before candidate creation." }

$baseManifest = Join-Path $base "RUNTIME_SHA256SUMS.json"
$baseManifestHash = (Get-FileHash -LiteralPath $baseManifest -Algorithm SHA256).Hash
$temp = Join-Path ([IO.Path]::GetTempPath()) ("lakis-runtime-candidate-" + [guid]::NewGuid().ToString("N"))
$snapshot = Join-Path $temp "source"

function Copy-Tree([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
}

function Copy-SourceTree([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -File -Recurse | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' -and
        $_.Name -notin @('process_audit.jsonl','external_ui_bridge_audit.jsonl','release-integrity.json')
    } | ForEach-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\')
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}

try {
    New-Item -ItemType Directory -Path $snapshot -Force | Out-Null
    $archive = Join-Path $temp "source.zip"
    & git -c core.autocrlf=false -C $repo archive --format=zip -o $archive $revision
    if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
    Expand-Archive -LiteralPath $archive -DestinationPath $snapshot

    Copy-Tree $base $output
    foreach ($protected in @("ComfyUI\models", "ComfyUI\input", "ComfyUI\output", "ComfyUI\temp", "ComfyUI\user")) {
        $path = Join-Path $output $protected
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }

    Copy-SourceTree (Join-Path $snapshot "src\external_ui") (Join-Path $output "ComfyUI\LAKIS\external_ui")
    Copy-Item -LiteralPath (Join-Path $snapshot "resources\STOP_AUTOMATION") -Destination (Join-Path $output "ComfyUI\LAKIS\STOP_AUTOMATION") -Force
    Copy-Item -LiteralPath (Join-Path $snapshot "src\runtime\sync_runtime_workflow.py") -Destination (Join-Path $output "ComfyUI\LAKIS\sync_runtime_workflow.py") -Force
    Copy-SourceTree (Join-Path $snapshot "workflows") (Join-Path $output "ComfyUI\LAKIS\workflows")

    $packages = Get-Content -LiteralPath (Join-Path $snapshot "resources\PRODUCTION_NODE_PACKAGES.txt") |
        ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') }
    foreach ($package in $packages) {
        if ($package -notmatch '^[A-Za-z0-9_-]+$') { throw "Invalid production package: $package" }
        Copy-SourceTree (Join-Path $snapshot "src\custom_nodes\$package") (Join-Path $output "ComfyUI\custom_nodes\$package")
    }

    Copy-Item -LiteralPath (Join-Path $snapshot "LICENSE.md") -Destination $output -Force
    Copy-Item -LiteralPath (Join-Path $snapshot "THIRD_PARTY_NOTICES.md") -Destination $output -Force
    Copy-SourceTree (Join-Path $snapshot "third_party_licenses") (Join-Path $output "third_party_licenses")
    [IO.File]::WriteAllText((Join-Path $output "VERSION"), $Version, [Text.UTF8Encoding]::new($false))

    $icon = Join-Path $snapshot "resources\LAKIS_windows_compatible.ico"
    $splash1 = Join-Path $snapshot "resources\splash\lakis-splash-01.png"
    $splash2 = Join-Path $snapshot "resources\splash\lakis-splash-02.png"
    $core = Join-Path $output "Microsoft.Web.WebView2.Core.dll"
    $forms = Join-Path $output "Microsoft.Web.WebView2.WinForms.dll"
    $installer = Join-Path $snapshot "installer"
    & $csc /nologo /target:winexe ("/out:" + (Join-Path $output "LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $installer "SplashArtwork.cs") (Join-Path $installer "LAKIS_Launcher.cs")
    if ($LASTEXITCODE) { throw "Launcher compilation failed." }
    & $csc /nologo /target:winexe ("/out:" + (Join-Path $output "LAKIS_Updater.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $installer "SplashArtwork.cs") (Join-Path $installer "LAKIS_Updater.cs")
    if ($LASTEXITCODE) { throw "Updater compilation failed." }
    Copy-Item -LiteralPath (Join-Path $output "LAKIS_Updater.exe") -Destination (Join-Path $output "LAKIS_Patcher.exe") -Force
    & $csc /nologo /target:winexe ("/out:" + (Join-Path $output "LAKIS_Desktop.exe")) ("/win32icon:" + $icon) ("/win32manifest:" + (Join-Path $installer "LAKIS_Desktop.manifest")) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/reference:" + $core) ("/reference:" + $forms) (Join-Path $installer "LAKIS_Desktop.cs")
    if ($LASTEXITCODE) { throw "Desktop compilation failed." }
    & $csc /nologo /target:winexe ("/out:" + (Join-Path $output "LAKIS_Model_Importer.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $installer "LAKIS_Model_Importer.cs")
    if ($LASTEXITCODE) { throw "Model importer compilation failed." }
    & $csc /nologo /target:winexe ("/out:" + (Join-Path $output "Uninstall_LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $installer "SplashArtwork.cs") (Join-Path $installer "LAKIS_Uninstaller.cs")
    if ($LASTEXITCODE) { throw "Uninstaller compilation failed." }

    $buildInfo = [ordered]@{
        schema = 1; product = 'LAKIS'; version = $Version; status = 'runtime-candidate'
        created_at = [DateTimeOffset]::Now.ToString('o'); source_revision = $revision
        base_runtime = $base; base_manifest_sha256 = $baseManifestHash
        comfyui = '0.37.0'; python = '3.13.14'; pytorch = '2.13.0+cu130'; cuda = '13.0'
    }
    [IO.File]::WriteAllText((Join-Path $output "BUILD_INFO.json"), (($buildInfo | ConvertTo-Json -Depth 5) + "`n"), [Text.UTF8Encoding]::new($false))

    $manifest = [ordered]@{ schema = 1; product = 'LAKIS'; version = $Version; source_revision = $revision; files = @() }
    $manifest.files = @(Get-ChildItem -LiteralPath $output -File -Recurse | Where-Object { $_.Name -ne 'RUNTIME_SHA256SUMS.json' } | Sort-Object FullName | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($output.Length).TrimStart('\').Replace('\','/'); size = [int64]$_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    [IO.File]::WriteAllText((Join-Path $output "RUNTIME_SHA256SUMS.json"), (($manifest | ConvertTo-Json -Depth 6) + "`n"), [Text.UTF8Encoding]::new($false))
    Write-Output "RUNTIME_CANDIDATE=$output"
    Write-Output "SOURCE_REVISION=$revision"
    Write-Output "FILES=$($manifest.files.Count)"
    Write-Output "MANIFEST_SHA256=$((Get-FileHash -LiteralPath (Join-Path $output 'RUNTIME_SHA256SUMS.json') -Algorithm SHA256).Hash)"
}
catch {
    if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
