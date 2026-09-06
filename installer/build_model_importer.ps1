$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputDirectory = Join-Path $repo "dist"
$output = Join-Path $outputDirectory "LAKIS_Model_Importer.exe"
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$icon = Join-Path $repo "resources\LAKIS_windows_compatible.ico"

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $compiler /nologo /target:winexe ("/out:" + $output) ("/win32icon:" + $icon) `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    (Join-Path $PSScriptRoot "LAKIS_Model_Importer.cs")
if ($LASTEXITCODE) { throw "Model importer compilation failed" }

Write-Output "MODEL_IMPORTER=$output"
Write-Output "SHA256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash)"
