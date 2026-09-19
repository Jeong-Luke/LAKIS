$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$out = Join-Path $repo "dist\rc-patcher"
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$icon = Join-Path $repo "resources\LAKIS_windows_compatible.ico"
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $compiler /nologo /target:winexe ("/out:"+(Join-Path $out "LAKIS_RC_Patcher.exe")) ("/win32icon:"+$icon) ("/resource:"+(Join-Path $PSScriptRoot "rc_patch.py")+",LAKIS.RCPatchEngine") /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot "LAKIS_RC_Patcher.cs")
if ($LASTEXITCODE) { throw "RC Patcher compilation failed" }
Write-Output "PATCHER=$(Join-Path $out 'LAKIS_RC_Patcher.exe')"
Write-Output "SHA256=$((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $out 'LAKIS_RC_Patcher.exe')).Hash)"
