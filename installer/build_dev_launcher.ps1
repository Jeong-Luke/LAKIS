$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$output = Join-Path $workspace "dist"
$stage = Join-Path $workspace ".dev-launcher-build"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$runtime = Join-Path $workspace ".safe-installer-build"
$sourceIcon = Join-Path $repo "resources\LAKIS_windows_compatible.ico"
$devIcon = Join-Path $repo "resources\LAKIS_DEV_red.ico"

New-Item -ItemType Directory -Force -Path $stage,$output | Out-Null
& $csc /nologo /target:exe ("/out:" + (Join-Path $stage "CreateDevIcon.exe")) `
    /reference:System.Drawing.dll (Join-Path $PSScriptRoot "CreateDevIcon.cs")
if ($LASTEXITCODE) { throw "DEV icon tool compilation failed" }
& (Join-Path $stage "CreateDevIcon.exe") $sourceIcon $devIcon
if ($LASTEXITCODE) { throw "DEV icon generation failed" }

$webViewCore = Join-Path $runtime "Microsoft.Web.WebView2.Core.dll"
$webViewForms = Join-Path $runtime "Microsoft.Web.WebView2.WinForms.dll"
foreach ($dependency in $webViewCore,$webViewForms) {
    if (-not (Test-Path -LiteralPath $dependency)) { throw "Missing build dependency: $dependency" }
}

& $csc /nologo /define:LAKIS_DEV /target:winexe `
    ("/out:" + (Join-Path $output "LAKIS_DEV.exe")) ("/win32icon:" + $devIcon) `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    ("/resource:" + (Join-Path $repo "resources\splash\lakis-splash-01.png") + ",LAKIS.Splash1") `
    ("/resource:" + (Join-Path $repo "resources\splash\lakis-splash-02.png") + ",LAKIS.Splash2") `
    (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Launcher.cs")
if ($LASTEXITCODE) { throw "DEV launcher compilation failed" }

& $csc /nologo /define:LAKIS_DEV /target:winexe `
    ("/out:" + (Join-Path $output "LAKIS_DEV_Desktop.exe")) ("/win32icon:" + $devIcon) `
    ("/win32manifest:" + (Join-Path $PSScriptRoot "LAKIS_Desktop.manifest")) `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    ("/reference:" + $webViewCore) ("/reference:" + $webViewForms) `
    (Join-Path $PSScriptRoot "LAKIS_Desktop.cs")
if ($LASTEXITCODE) { throw "DEV desktop host compilation failed" }

Write-Output ("DEV_LAUNCHER=" + (Join-Path $output "LAKIS_DEV.exe"))
Write-Output ("DEV_DESKTOP=" + (Join-Path $output "LAKIS_DEV_Desktop.exe"))
Write-Output ("DEV_ICON=" + $devIcon)
