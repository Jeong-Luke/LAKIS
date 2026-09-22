param(
    [Parameter(Mandatory=$true)][string]$Version,
    [string]$EvidenceDirectory = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = $Version.TrimStart("v")
$evidence = if ($EvidenceDirectory) {
    [IO.Path]::GetFullPath($EvidenceDirectory)
} else {
    Join-Path $repo ("release_audits\v" + $version)
}
if (-not (Test-Path -LiteralPath $evidence -PathType Container)) {
    throw "THREE_PARTY_AUDIT_MISSING: $evidence"
}
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("lakis-audit-fingerprint-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "New-ReleaseAuditFingerprint.ps1") -OutputPath $tmp | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "THREE_PARTY_AUDIT_FINGERPRINT_FAILED" }
    $current = Get-Content -Raw -Encoding UTF8 -LiteralPath $tmp | ConvertFrom-Json
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
if ([string]$current.version -ne $version) {
    throw "THREE_PARTY_AUDIT_VERSION_MISMATCH: candidate=$($current.version) requested=$version"
}

$required = @("gpt","deepseek","codex")
foreach ($auditor in $required) {
    $path = Join-Path $evidence ($auditor + ".json")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "THREE_PARTY_AUDIT_MISSING: $auditor"
    }
    $record = Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json
    $requiredFields = @("schema","auditor","version","fingerprint_sha256","status","blockers","findings")
    foreach ($field in $requiredFields) {
        if ($record.PSObject.Properties.Name -notcontains $field) {
            throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor missing $field"
        }
    }
    if ($record.schema -ne 1 -or [string]$record.auditor -ne $auditor) {
        throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor"
    }
    if ($record.blockers -is [string] -or $record.findings -is [string]) {
        throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor blockers/findings must be arrays"
    }
    if ([string]$record.version -ne $version) {
        throw "THREE_PARTY_AUDIT_VERSION_MISMATCH: $auditor=$($record.version)"
    }
    if ([string]$record.fingerprint_sha256 -ne [string]$current.fingerprint_sha256) {
        throw "THREE_PARTY_AUDIT_STALE: $auditor fingerprint does not match current candidate"
    }
    $status = ([string]$record.status).ToUpperInvariant()
    if ($status -in @("TOKEN_LIMITED","RATE_LIMITED","UNKNOWN_SUBMISSION_OUTCOME")) {
        throw "THREE_PARTY_AUDIT_INCOMPLETE: $auditor status=$status; report to user, continue other audits, and rerun this primary audit later"
    }
    if ($status -ne "PASS") {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor status=$status"
    }
    if ($record.blockers -and @($record.blockers).Count -gt 0) {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor has open blockers"
    }
    if ($record.findings -and @($record.findings).Count -gt 0) {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor PASS record still has open findings"
    }
}
Write-Output ("THREE_PARTY_AUDIT_GATE_OK version={0} fingerprint={1}" -f $version,$current.fingerprint_sha256)
