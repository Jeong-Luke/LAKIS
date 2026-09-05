$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$output = if ($env:LAKIS_INSTALLER_OUTPUT) { $env:LAKIS_INSTALLER_OUTPUT } else { Join-Path $workspace "dist\LAKIS_Setup.exe" }
$stage = Join-Path $workspace ".safe-installer-build"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$icon = Join-Path $repo "resources\LAKIS_windows_compatible.ico"
New-Item -ItemType Directory -Force -Path $stage,(Split-Path $output) | Out-Null
$sevenZip = Join-Path $stage "7zr.exe"
if (-not (Test-Path -LiteralPath $sevenZip)) {
    Invoke-WebRequest -UseBasicParsing "https://www.7-zip.org/a/7zr.exe" -OutFile $sevenZip
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sevenZip).Hash -ne "AD4C82FADCBDF93C03B4FC440F300509C7D60C5C2F4D183E35D9D70D6957037D") { throw "Official 7zr.exe verification failed" }
$webViewPackage = Join-Path $stage "Microsoft.Web.WebView2.1.0.4191.47.nupkg"
if (-not (Test-Path -LiteralPath $webViewPackage)) {
    Invoke-WebRequest -UseBasicParsing "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.4191.47" -OutFile $webViewPackage
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $webViewPackage).Hash -ne "F492BBF547D0DA329553B6727435B677579B1E9F91CC9E4A1AD029366D5F23D0") { throw "Microsoft WebView2 SDK verification failed" }
$webViewZip = Join-Path $stage "webview2.zip"
$webViewRoot = Join-Path $stage "webview2"
Copy-Item -LiteralPath $webViewPackage -Destination $webViewZip -Force
if (Test-Path -LiteralPath $webViewRoot) { Remove-Item -LiteralPath $webViewRoot -Recurse -Force }
Expand-Archive -LiteralPath $webViewZip -DestinationPath $webViewRoot
$webViewCore = Join-Path $webViewRoot "lib\net462\Microsoft.Web.WebView2.Core.dll"
$webViewForms = Join-Path $webViewRoot "lib\net462\Microsoft.Web.WebView2.WinForms.dll"
$webViewLoader = Join-Path $webViewRoot "runtimes\win-x64\native\WebView2Loader.dll"
Copy-Item -LiteralPath $webViewCore -Destination (Join-Path $stage "Microsoft.Web.WebView2.Core.dll") -Force
Copy-Item -LiteralPath $webViewForms -Destination (Join-Path $stage "Microsoft.Web.WebView2.WinForms.dll") -Force
Copy-Item -LiteralPath $webViewLoader -Destination (Join-Path $stage "WebView2Loader.dll") -Force

$splash1 = Join-Path $repo "resources\splash\lakis-splash-01.png"
$splash2 = Join-Path $repo "resources\splash\lakis-splash-02.png"
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Launcher.cs")
if ($LASTEXITCODE) { throw "Launcher compilation failed" }
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS_Updater.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Updater.cs")
if ($LASTEXITCODE) { throw "Updater compilation failed" }
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS_Desktop.exe")) ("/win32icon:" + $icon) ("/win32manifest:" + (Join-Path $PSScriptRoot "LAKIS_Desktop.manifest")) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/reference:" + $webViewCore) ("/reference:" + $webViewForms) (Join-Path $PSScriptRoot "LAKIS_Desktop.cs")
if ($LASTEXITCODE) { throw "Desktop host compilation failed" }
Copy-Item -LiteralPath (Join-Path $stage "LAKIS.exe") -Destination (Join-Path (Split-Path $output) "LAKIS.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Updater.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Patcher.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Desktop.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Desktop.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "Microsoft.Web.WebView2.Core.dll") -Destination (Join-Path (Split-Path $output) "Microsoft.Web.WebView2.Core.dll") -Force
Copy-Item -LiteralPath (Join-Path $stage "Microsoft.Web.WebView2.WinForms.dll") -Destination (Join-Path (Split-Path $output) "Microsoft.Web.WebView2.WinForms.dll") -Force
Copy-Item -LiteralPath (Join-Path $stage "WebView2Loader.dll") -Destination (Join-Path (Split-Path $output) "WebView2Loader.dll") -Force
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "Uninstall_LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Uninstaller.cs")
if ($LASTEXITCODE) { throw "Uninstaller compilation failed" }
& $csc /nologo /target:winexe ("/out:" + $output) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ("/resource:" + (Join-Path $stage "LAKIS.exe") + ",LAKIS.Launcher") ("/resource:" + (Join-Path $stage "LAKIS_Updater.exe") + ",LAKIS.Updater") ("/resource:" + (Join-Path $stage "LAKIS_Desktop.exe") + ",LAKIS.Desktop") ("/resource:" + $webViewCore + ",LAKIS.WebView2.Core") ("/resource:" + $webViewForms + ",LAKIS.WebView2.WinForms") ("/resource:" + $webViewLoader + ",LAKIS.WebView2.Loader") ("/resource:" + (Join-Path $stage "Uninstall_LAKIS.exe") + ",LAKIS.Uninstaller") ("/resource:" + $sevenZip + ",LAKIS.7zr") ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "Setup_LAKIS_Safe.cs")
if ($LASTEXITCODE) { throw "Safe installer compilation failed" }
Write-Output "INSTALLER=$output"
Write-Output "LAUNCHER=$(Join-Path (Split-Path $output) 'LAKIS.exe')"
Write-Output "PATCHER=$(Join-Path (Split-Path $output) 'LAKIS_Patcher.exe')"
Write-Output "DESKTOP=$(Join-Path (Split-Path $output) 'LAKIS_Desktop.exe')"
Write-Output "SHA256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash)"
