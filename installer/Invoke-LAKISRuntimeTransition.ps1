param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [Parameter(Mandatory = $true)][string]$TargetRoot,
    [string]$ExpectedVersion = "8.0.0",
    [ValidateSet("", "after-stage", "after-backup", "after-promote")]
    [string]$TestInterruptAfter = ""
)

$ErrorActionPreference = "Stop"

function Invoke-SafeCopy([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Runtime copy failed ($LASTEXITCODE): $Source -> $Destination" }
}

function Write-Journal([string]$Path, [hashtable]$State) {
    $temporary = "$Path.$PID.tmp"
    $State.updated_at = (Get-Date).ToString("o")
    $State | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-Runtime([string]$Root, [string]$Version) {
    foreach ($relative in @(
        "VERSION", "LAKIS.exe", "python_embeded\python.exe", "ComfyUI\main.py",
        "ComfyUI\LAKIS\external_ui\launch_lakis.py", "RUNTIME_SHA256SUMS.json"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $relative) -PathType Leaf)) {
            throw "Staged runtime is incomplete: $relative"
        }
    }
    $actual = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim()
    if ($actual -ne $Version) { throw "Unexpected runtime version '$actual'; expected '$Version'." }
}

function Assert-UnlockedRuntime([string]$Root, [string[]]$ProtectedPrefixes) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force) {
        $relative = $file.FullName.Substring($rootPath.Length).Replace('\','/')
        if ($ProtectedPrefixes | Where-Object { $relative.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }) { continue }
        try {
            $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
            $stream.Dispose()
        }
        catch {
            throw "Runtime file is in use: $relative"
        }
    }
}

$candidate = (Resolve-Path -LiteralPath $CandidateRoot).Path
$target = [IO.Path]::GetFullPath($TargetRoot).TrimEnd('\')
$parent = Split-Path -Parent $target
$name = Split-Path -Leaf $target
$stage = Join-Path $parent ".$name-8-stage"
$backup = Join-Path $parent ".$name-pre-8-backup"
$journalPath = Join-Path $parent ".$name-runtime-transition.json"

if ([IO.Path]::GetPathRoot($candidate) -ne [IO.Path]::GetPathRoot($target)) {
    throw "Candidate and target must be on the same volume for atomic promotion."
}
New-Item -ItemType Directory -Path $parent -Force | Out-Null

$protectedDirectories = @(".lakis", "ComfyUI/models", "ComfyUI/input", "ComfyUI/output", "ComfyUI/user")
$protectedFiles = @("LAKIS_OUTPUT_DIRECTORY.txt", "ComfyUI/extra_model_paths.yaml")
$protectedPrefixes = @($protectedDirectories | ForEach-Object { $_.TrimEnd('/') + '/' }) + $protectedFiles
$journal = @{
    schema = 1; expected_version = $ExpectedVersion; candidate = $candidate; target = $target
    stage = $stage; backup = $backup; phase = "starting"; started_at = (Get-Date).ToString("o")
}

try {
    # A crash after promotion leaves both the verified new target and the old
    # backup. Treat that state as a resumable completion, never as permission
    # to replace or delete either tree again.
    $targetVersionPath = Join-Path $target "VERSION"
    if ((Test-Path -LiteralPath $targetVersionPath -PathType Leaf) -and
        ((Get-Content -LiteralPath $targetVersionPath -Raw).Trim() -eq $ExpectedVersion) -and
        (Test-Path -LiteralPath $backup -PathType Container)) {
        Assert-Runtime $target $ExpectedVersion
        $journal.phase = "complete"
        $journal.recovered_from = "promoted"
        $journal.completed_at = (Get-Date).ToString("o")
        Write-Journal $journalPath $journal
        return [pscustomobject]@{ status="PASS"; version=$ExpectedVersion; target=$target; backup=$backup; journal=$journalPath }
    }
    if (-not (Test-Path -LiteralPath $stage)) {
        Invoke-SafeCopy $candidate $stage
    }
    Assert-Runtime $stage $ExpectedVersion
    $journal.phase = "staged"
    Write-Journal $journalPath $journal
    if ($TestInterruptAfter -eq "after-stage") { throw "TEST_INTERRUPT_after-stage" }

    if (Test-Path -LiteralPath $target) {
        Assert-UnlockedRuntime $target $protectedPrefixes
        foreach ($relative in $protectedDirectories) {
            $source = Join-Path $target $relative
            if (-not (Test-Path -LiteralPath $source)) { continue }
            $destination = Join-Path $stage $relative
            if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
            Invoke-SafeCopy $source $destination
        }
        foreach ($relative in $protectedFiles) {
            $source = Join-Path $target $relative
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
            $destination = Join-Path $stage $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
        if (Test-Path -LiteralPath $backup) { throw "A previous runtime backup already exists: $backup" }
        Move-Item -LiteralPath $target -Destination $backup
    }
    $journal.phase = "backup-created"
    Write-Journal $journalPath $journal
    if ($TestInterruptAfter -eq "after-backup") { throw "TEST_INTERRUPT_after-backup" }

    if (-not (Test-Path -LiteralPath $target)) {
        if (-not (Test-Path -LiteralPath $stage)) {
            if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $target }
            throw "Transition stage is missing; original runtime was restored."
        }
        Move-Item -LiteralPath $stage -Destination $target
    }
    $journal.phase = "promoted"
    Write-Journal $journalPath $journal
    if ($TestInterruptAfter -eq "after-promote") { throw "TEST_INTERRUPT_after-promote" }

    Assert-Runtime $target $ExpectedVersion
    $journal.phase = "complete"
    $journal.completed_at = (Get-Date).ToString("o")
    Write-Journal $journalPath $journal
    [pscustomobject]@{ status="PASS"; version=$ExpectedVersion; target=$target; backup=$backup; journal=$journalPath }
}
catch {
    $journal.phase = "interrupted"
    $journal.error = $_.Exception.Message
    Write-Journal $journalPath $journal
    throw
}
