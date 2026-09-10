$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
$output = if ($env:LAKIS_INSTALLER_OUTPUT) { $env:LAKIS_INSTALLER_OUTPUT } else { Join-Path $workspace "dist\LAKIS_Setup.exe" }
$stage = Join-Path $workspace ".safe-installer-build"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$icon = Join-Path $repo "resources\LAKIS_windows_compatible.ico"
New-Item -ItemType Directory -Force -Path $stage,(Split-Path $output) | Out-Null

$packageVersion = (Get-Content -LiteralPath (Join-Path $repo "VERSION") -Raw).Trim()
$assemblyParts = @(($packageVersion -replace '[^0-9.]', '').Trim('.').Split('.') | Select-Object -First 4)
while ($assemblyParts.Count -lt 4) { $assemblyParts += "0" }
$assemblyVersion = $assemblyParts -join "."
$assemblyInfo = Join-Path $stage "LAKIS.AssemblyInfo.cs"
@"
using System.Reflection;
[assembly: AssemblyCompany("LAKIS Studio")]
[assembly: AssemblyProduct("LAKIS Studio")]
[assembly: AssemblyCopyright("Copyright © 2026 Luke Jeong")]
[assembly: AssemblyTrademark("LAKIS")]
[assembly: AssemblyVersion("$assemblyVersion")]
[assembly: AssemblyFileVersion("$assemblyVersion")]
[assembly: AssemblyInformationalVersion("$packageVersion")]
"@ | Set-Content -LiteralPath $assemblyInfo -Encoding UTF8

function Invoke-LakisCodeSign([string[]]$Paths) {
    $releaseBuild = $env:LAKIS_RELEASE_BUILD -eq "1"
    $allowUnsignedRelease = $env:LAKIS_ALLOW_UNSIGNED_RELEASE -eq "1"
    $thumbprint = [string]$env:LAKIS_SIGNING_THUMBPRINT
    $timestampServer = [string]$env:LAKIS_TIMESTAMP_URL
    if (-not $thumbprint) {
        if ($releaseBuild -and -not $allowUnsignedRelease) {
            throw "Unsigned release requires explicit LAKIS_ALLOW_UNSIGNED_RELEASE=1 acknowledgement."
        }
        if ($releaseBuild) {
            Write-Warning "Unsigned release explicitly acknowledged; Defender scan and published SHA-256 are required."
        } else {
            Write-Warning "Unsigned development build: LAKIS_SIGNING_THUMBPRINT is not set."
        }
        return
    }
    if (-not $timestampServer) {
        throw "Signed build requires an RFC 3161 timestamp URL in LAKIS_TIMESTAMP_URL."
    }
    $certificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Thumbprint -eq ($thumbprint -replace ' ', '').ToUpperInvariant() } |
        Select-Object -First 1
    if (-not $certificate) { throw "Requested code-signing certificate was not found in Cert:\CurrentUser\My." }
    foreach ($path in $Paths) {
        $signature = Set-AuthenticodeSignature -LiteralPath $path -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer $timestampServer
        if ($signature.Status -ne "Valid") { throw "Authenticode signing failed for ${path}: $($signature.StatusMessage)" }
    }
}
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
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") $assemblyInfo (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Launcher.cs")
if ($LASTEXITCODE) { throw "Launcher compilation failed" }
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS_Updater.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") $assemblyInfo (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Updater.cs")
if ($LASTEXITCODE) { throw "Updater compilation failed" }
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS_Desktop.exe")) ("/win32icon:" + $icon) ("/win32manifest:" + (Join-Path $PSScriptRoot "LAKIS_Desktop.manifest")) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/reference:" + $webViewCore) ("/reference:" + $webViewForms) $assemblyInfo (Join-Path $PSScriptRoot "LAKIS_Desktop.cs")
if ($LASTEXITCODE) { throw "Desktop host compilation failed" }
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "LAKIS_Model_Importer.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll $assemblyInfo (Join-Path $PSScriptRoot "LAKIS_Model_Importer.cs")
if ($LASTEXITCODE) { throw "Model importer compilation failed" }
Copy-Item -LiteralPath (Join-Path $stage "LAKIS.exe") -Destination (Join-Path (Split-Path $output) "LAKIS.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Updater.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Patcher.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Updater.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Updater.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Desktop.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Desktop.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Model_Importer.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Model_Importer.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "Microsoft.Web.WebView2.Core.dll") -Destination (Join-Path (Split-Path $output) "Microsoft.Web.WebView2.Core.dll") -Force
Copy-Item -LiteralPath (Join-Path $stage "Microsoft.Web.WebView2.WinForms.dll") -Destination (Join-Path (Split-Path $output) "Microsoft.Web.WebView2.WinForms.dll") -Force
Copy-Item -LiteralPath (Join-Path $stage "WebView2Loader.dll") -Destination (Join-Path (Split-Path $output) "WebView2Loader.dll") -Force
& $csc /nologo /target:winexe ("/out:" + (Join-Path $stage "Uninstall_LAKIS.exe")) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") $assemblyInfo (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "LAKIS_Uninstaller.cs")
if ($LASTEXITCODE) { throw "Uninstaller compilation failed" }
Invoke-LakisCodeSign @(
    (Join-Path $stage "LAKIS.exe"),
    (Join-Path $stage "LAKIS_Updater.exe"),
    (Join-Path $stage "LAKIS_Desktop.exe"),
    (Join-Path $stage "LAKIS_Model_Importer.exe"),
    (Join-Path $stage "Uninstall_LAKIS.exe")
)
Copy-Item -LiteralPath (Join-Path $stage "LAKIS.exe") -Destination (Join-Path (Split-Path $output) "LAKIS.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Updater.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Patcher.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Updater.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Updater.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Desktop.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Desktop.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "LAKIS_Model_Importer.exe") -Destination (Join-Path (Split-Path $output) "LAKIS_Model_Importer.exe") -Force
Copy-Item -LiteralPath (Join-Path $stage "Uninstall_LAKIS.exe") -Destination (Join-Path (Split-Path $output) "Uninstall_LAKIS.exe") -Force
& $csc /nologo /target:winexe ("/out:" + $output) ("/win32icon:" + $icon) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ("/resource:" + (Join-Path $stage "LAKIS.exe") + ",LAKIS.Launcher") ("/resource:" + (Join-Path $stage "LAKIS_Updater.exe") + ",LAKIS.Updater") ("/resource:" + (Join-Path $stage "LAKIS_Desktop.exe") + ",LAKIS.Desktop") ("/resource:" + (Join-Path $stage "LAKIS_Model_Importer.exe") + ",LAKIS.ModelImporter") ("/resource:" + $icon + ",LAKIS.Icon") ("/resource:" + $webViewCore + ",LAKIS.WebView2.Core") ("/resource:" + $webViewForms + ",LAKIS.WebView2.WinForms") ("/resource:" + $webViewLoader + ",LAKIS.WebView2.Loader") ("/resource:" + (Join-Path $stage "Uninstall_LAKIS.exe") + ",LAKIS.Uninstaller") ("/resource:" + $sevenZip + ",LAKIS.7zr") ("/resource:" + $splash1 + ",LAKIS.Splash1") ("/resource:" + $splash2 + ",LAKIS.Splash2") $assemblyInfo (Join-Path $PSScriptRoot "SplashArtwork.cs") (Join-Path $PSScriptRoot "Setup_LAKIS_Safe.cs")
if ($LASTEXITCODE) { throw "Safe installer compilation failed" }
Invoke-LakisCodeSign @($output)
Write-Output "INSTALLER=$output"
Write-Output "LAUNCHER=$(Join-Path (Split-Path $output) 'LAKIS.exe')"
Write-Output "PATCHER=$(Join-Path (Split-Path $output) 'LAKIS_Patcher.exe')"
Write-Output "UPDATER=$(Join-Path (Split-Path $output) 'LAKIS_Updater.exe')"
Write-Output "DESKTOP=$(Join-Path (Split-Path $output) 'LAKIS_Desktop.exe')"
Write-Output "MODEL_IMPORTER=$(Join-Path (Split-Path $output) 'LAKIS_Model_Importer.exe')"
Write-Output "UNINSTALLER=$(Join-Path (Split-Path $output) 'Uninstall_LAKIS.exe')"
Write-Output "SHA256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash)"
