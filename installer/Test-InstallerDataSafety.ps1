param(
    [string]$InstallerPath = ""
)

$ErrorActionPreference = "Stop"
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$source = Join-Path $PSScriptRoot "Setup_LAKIS_Safe.cs"
$sharedArtwork = Join-Path $PSScriptRoot "SplashArtwork.cs"
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lakis-installer-safety-" + [guid]::NewGuid().ToString("N"))
$testInstaller = if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
    Join-Path $temporaryRoot "LAKIS_Setup_SafetyTest.exe"
} else {
    [System.IO.Path]::GetFullPath($InstallerPath)
}

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "INSTALLER DATA SAFETY FAILED: $Message" }
}

function Invoke-ProtectedInstall([string]$Target, [string]$SentinelName, [string]$SentinelValue) {
    $sentinel = Join-Path $Target $SentinelName
    [System.IO.File]::WriteAllText($sentinel, $SentinelValue, [System.Text.UTF8Encoding]::new($false))
    $process = Start-Process -FilePath $testInstaller -ArgumentList @("--headless", "--install-dir", $Target) -Wait -PassThru
    Require ($process.ExitCode -ne 0) "New install unexpectedly accepted protected folder '$Target'."
    Require (Test-Path -LiteralPath $sentinel -PathType Leaf) "Sentinel was deleted from '$Target'."
    Require ((Get-Content -Raw -LiteralPath $sentinel) -eq $SentinelValue) "Sentinel contents changed in '$Target'."
    Require (-not (Test-Path -LiteralPath (Join-Path $Target "network-install.log"))) "Rejected install still wrote into protected folder '$Target'."
}

try {
    New-Item -ItemType Directory -Force -Path $temporaryRoot | Out-Null
    if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
        & $compiler /nologo /target:exe ("/out:" + $testInstaller) `
            /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
            /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll $sharedArtwork $source
        Require ($LASTEXITCODE -eq 0) "Setup_LAKIS_Safe.cs did not compile."
    }
    else {
        Require (Test-Path -LiteralPath $testInstaller -PathType Leaf) "Built installer was not found: $testInstaller"
    }

    # Any non-empty destination must be rejected without removing user files.
    $nonEmpty = Join-Path $temporaryRoot "non-empty-user-folder"
    New-Item -ItemType Directory -Force -Path $nonEmpty | Out-Null
    Invoke-ProtectedInstall $nonEmpty "user-image.png" "do-not-delete-image"

    # A recognizable LAKIS installation must explicitly take the repair path.
    $installed = Join-Path $temporaryRoot "existing-lakis"
    New-Item -ItemType Directory -Force -Path (Join-Path $installed "ComfyUI\user\default\workflows") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $installed "python_embeded") | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $installed "VERSION"), "7.2.2")
    Invoke-ProtectedInstall $installed "ComfyUI\user\default\workflows\my-workflow.json" '{"user":"workflow"}'

    Write-Output "INSTALLER_DATA_SAFETY_OK protected_cases=2"
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
