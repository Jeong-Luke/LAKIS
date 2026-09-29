param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [Parameter(Mandatory = $true)][string]$TargetRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedManifestSha256,
    [string]$ExpectedVersion = "8.0.0",
    [ValidateSet("", "after-stage", "after-backup", "after-promote", "corrupt-after-promote")]
    [string]$TestInterruptAfter = ""
)

$ErrorActionPreference = "Stop"

function Invoke-SafeCopy([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Runtime copy failed ($LASTEXITCODE): $Source -> $Destination" }
}

function Copy-ProtectedDirectory([string]$Source, [string]$Destination) {
    $sourceItem = Get-Item -LiteralPath $Source -Force
    if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        if ($sourceItem.LinkType -ne "Junction" -or -not $sourceItem.Target) {
            throw "Unsupported protected-directory reparse point: $Source"
        }
        New-Item -ItemType Junction -Path $Destination -Target ([string]$sourceItem.Target) | Out-Null
        return
    }

    $sourcePath = [IO.Path]::GetFullPath($Source).TrimEnd('\') + '\'
    $links = @(Get-ChildItem -LiteralPath $Source -Force -Recurse | Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    })
    foreach ($link in $links) {
        if ($link.LinkType -ne "Junction" -or -not $link.Target) {
            throw "Unsupported protected-data reparse point: $($link.FullName)"
        }
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination /E /XJ /XJD /XJF /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Protected data copy failed ($LASTEXITCODE): $Source -> $Destination" }

    foreach ($link in $links) {
        $relative = $link.FullName.Substring($sourcePath.Length)
        $linkDestination = Join-Path $Destination $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $linkDestination) -Force | Out-Null
        New-Item -ItemType Junction -Path $linkDestination -Target ([string]$link.Target) | Out-Null
    }
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

function Test-ProtectedPath([string]$Relative, [string[]]$ProtectedPrefixes, [string[]]$ProtectedFiles) {
    $normalized = $Relative.Replace('\','/').TrimStart('/')
    if ($ProtectedFiles -contains $normalized) { return $true }
    foreach ($prefix in $ProtectedPrefixes) {
        if ($normalized.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Assert-RuntimeManifest(
    [string]$Root,
    [string]$Version,
    [string[]]$ProtectedPrefixes,
    [string[]]$ProtectedFiles,
    [string]$ExpectedManifestHash,
    [switch]$AllowProtectedOverrides
) {
    Assert-Runtime $Root $Version
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $manifestPath = Join-Path $Root "RUNTIME_SHA256SUMS.json"
    $manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
    if ($manifestHash -ne $ExpectedManifestHash) { throw "Runtime manifest identity hash mismatch." }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.product -ne "LAKIS" -or $manifest.version -ne $Version) {
        throw "Runtime manifest identity is invalid."
    }
    if (-not $manifest.files -or $manifest.files.Count -lt 1) { throw "Runtime manifest contains no files." }

    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or
            $relative.Contains('..') -or $relative.Contains(':')) {
            throw "Unsafe runtime manifest path: $relative"
        }
        $normalized = $relative.Replace('\','/').TrimStart('/')
        if (-not $seen.Add($normalized)) { throw "Duplicate runtime manifest path: $normalized" }
        if ($AllowProtectedOverrides -and (Test-ProtectedPath $normalized $ProtectedPrefixes $ProtectedFiles)) { continue }

        $filePath = [IO.Path]::GetFullPath((Join-Path $Root $normalized.Replace('/','\')))
        if (-not $filePath.StartsWith($rootPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Runtime manifest path escapes root: $normalized"
        }
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "Runtime manifest file is missing: $normalized" }
        $cursor = $filePath
        while ($cursor.StartsWith($rootPath, [StringComparison]::OrdinalIgnoreCase)) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Runtime manifest path contains a reparse point: $normalized"
            }
            $parentPath = Split-Path -Parent $cursor
            if ($parentPath.TrimEnd('\') -eq $Root.TrimEnd('\')) { break }
            $cursor = $parentPath
        }
        $file = Get-Item -LiteralPath $filePath
        if ([int64]$file.Length -ne [int64]$entry.size) { throw "Runtime manifest size mismatch: $normalized" }
        $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash
        if ($actualHash -ne [string]$entry.sha256) { throw "Runtime manifest hash mismatch: $normalized" }
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force -Recurse) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { continue }
        $relative = $item.FullName.Substring($rootPath.Length).Replace('\','/')
        if ($AllowProtectedOverrides -and (Test-ProtectedPath $relative $ProtectedPrefixes $ProtectedFiles)) { continue }
        throw "Runtime contains an untrusted reparse point: $relative"
    }
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force) {
        $relative = $file.FullName.Substring($rootPath.Length).Replace('\','/')
        if ($relative -eq "RUNTIME_SHA256SUMS.json" -or $seen.Contains($relative)) { continue }
        if ($AllowProtectedOverrides -and (Test-ProtectedPath $relative $ProtectedPrefixes $ProtectedFiles)) { continue }
        throw "Runtime contains a file not listed in the manifest: $relative"
    }
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
$ExpectedManifestSha256 = $ExpectedManifestSha256.ToUpperInvariant()
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
$protectedPrefixes = @($protectedDirectories | ForEach-Object { $_.TrimEnd('/') + '/' })
$journal = @{
    schema = 1; expected_version = $ExpectedVersion; candidate = $candidate; target = $target
    stage = $stage; backup = $backup; phase = "starting"; started_at = (Get-Date).ToString("o")
}

try {
    # Validate the source tree before robocopy can encounter any untrusted
    # reparse point or unlisted payload.
    Assert-RuntimeManifest $candidate $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256

    # A crash after promotion leaves both the verified new target and the old
    # backup. Treat that state as a resumable completion, never as permission
    # to replace or delete either tree again.
    $targetVersionPath = Join-Path $target "VERSION"
    if ((Test-Path -LiteralPath $targetVersionPath -PathType Leaf) -and
        ((Get-Content -LiteralPath $targetVersionPath -Raw).Trim() -eq $ExpectedVersion) -and
        (Test-Path -LiteralPath $backup -PathType Container)) {
        Assert-RuntimeManifest $target $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256 -AllowProtectedOverrides
        $journal.phase = "complete"
        $journal.recovered_from = "promoted"
        $journal.completed_at = (Get-Date).ToString("o")
        Write-Journal $journalPath $journal
        return [pscustomobject]@{ status="PASS"; version=$ExpectedVersion; target=$target; backup=$backup; journal=$journalPath }
    }
    if (Test-Path -LiteralPath $stage) {
        try {
            Assert-RuntimeManifest $stage $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256 -AllowProtectedOverrides
        }
        catch {
            $quarantine = "$stage.invalid-$([guid]::NewGuid().ToString('N'))"
            Move-Item -LiteralPath $stage -Destination $quarantine
            $journal.discarded_stage = $quarantine
        }
    }
    if (-not (Test-Path -LiteralPath $stage)) {
        Invoke-SafeCopy $candidate $stage
        Assert-RuntimeManifest $stage $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256
    }
    Assert-RuntimeManifest $stage $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256 -AllowProtectedOverrides
    $journal.phase = "staged"
    Write-Journal $journalPath $journal
    if ($TestInterruptAfter -eq "after-stage") { throw "TEST_INTERRUPT_after-stage" }

    $targetExists = Test-Path -LiteralPath $target -PathType Container
    $backupExists = Test-Path -LiteralPath $backup -PathType Container
    $preservationSource = if ($targetExists) { $target } elseif ($backupExists) { $backup } else { $null }
    if ($targetExists) { Assert-UnlockedRuntime $target $protectedPrefixes }
    if ($preservationSource) {
        foreach ($relative in $protectedDirectories) {
            $source = Join-Path $preservationSource $relative
            if (-not (Test-Path -LiteralPath $source)) { continue }
            $destination = Join-Path $stage $relative
            if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
            Copy-ProtectedDirectory $source $destination
        }
        foreach ($relative in $protectedFiles) {
            $source = Join-Path $preservationSource $relative
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
            $sourceItem = Get-Item -LiteralPath $source -Force
            if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Protected settings file must not be a reparse point: $relative"
            }
            $destination = Join-Path $stage $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
        Assert-RuntimeManifest $stage $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256 -AllowProtectedOverrides
    }
    if ($targetExists) {
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
    if ($TestInterruptAfter -eq "corrupt-after-promote") {
        Set-Content -LiteralPath (Join-Path $target "runtime-required.bin") -Value "TEST_CORRUPTION" -Encoding ascii
    }

    Assert-RuntimeManifest $target $ExpectedVersion $protectedPrefixes $protectedFiles $ExpectedManifestSha256 -AllowProtectedOverrides
    $journal.phase = "complete"
    $journal.completed_at = (Get-Date).ToString("o")
    Write-Journal $journalPath $journal
    [pscustomobject]@{ status="PASS"; version=$ExpectedVersion; target=$target; backup=$backup; journal=$journalPath }
}
catch {
    $failure = $_
    if ($journal.phase -eq "promoted" -and $failure.Exception.Message -notlike "*TEST_INTERRUPT_after-promote*" -and
        (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $backup)) {
        try {
            $failedTarget = "$target.failed-$([guid]::NewGuid().ToString('N'))"
            Move-Item -LiteralPath $target -Destination $failedTarget
            Move-Item -LiteralPath $backup -Destination $target
            $journal.rollback = "PASS"
            $journal.failed_target = $failedTarget
        }
        catch {
            $journal.rollback = "FAILED: $($_.Exception.Message)"
        }
    }
    $journal.phase = "interrupted"
    $journal.error = $failure.Exception.Message
    Write-Journal $journalPath $journal
    throw $failure
}
