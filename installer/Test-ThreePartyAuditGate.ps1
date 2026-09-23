param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = $Version.TrimStart("v")
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
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
$exceptionPath = Join-Path $evidence "owner-two-party-exception.json"
$twoParty = $false
if (Test-Path -LiteralPath $exceptionPath -PathType Leaf) {
    $exception = Get-Content -Raw -Encoding UTF8 -LiteralPath $exceptionPath | ConvertFrom-Json
    $validAuditors = $exception.required_auditors
    if ($exception -isnot [pscustomobject] -or
        ($exception.schema -isnot [int] -and $exception.schema -isnot [long]) -or $exception.schema -ne 1 -or
        $exception.type -isnot [string] -or $exception.type -cne "owner_approved_two_party_exception" -or
        $exception.version -isnot [string] -or $exception.version -cne $version -or
        $exception.fingerprint_sha256 -isnot [string] -or $exception.fingerprint_sha256 -cne [string]$current.fingerprint_sha256 -or
        $exception.owner_approved -isnot [bool] -or $exception.owner_approved -ne $true -or
        $exception.reason -isnot [string] -or $exception.reason -cne "GPT_SERVICE_UNAVAILABLE" -or
        $validAuditors -isnot [System.Array] -or
        $validAuditors.Count -ne 2 -or
        @($validAuditors | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
        @($validAuditors | Where-Object { $_ -ceq "deepseek" }).Count -ne 1 -or
        @($validAuditors | Where-Object { $_ -ceq "codex" }).Count -ne 1) {
        throw "TWO_PARTY_AUDIT_EXCEPTION_INVALID"
    }
    $required = @("deepseek","codex")
    $twoParty = $true
    # Preserve historical GPT evidence without treating it as a current PASS.
    # An outage exception cannot hide a known failure on this exact revision.
    $gptPath = Join-Path $evidence "gpt.json"
    if (Test-Path -LiteralPath $gptPath -PathType Leaf) {
        $gpt = Get-Content -Raw -Encoding UTF8 -LiteralPath $gptPath | ConvertFrom-Json
        if ($gpt -isnot [pscustomobject] -or $gpt.fingerprint_sha256 -isnot [string] -or
            $gpt.status -isnot [string]) { throw "TWO_PARTY_AUDIT_INVALID_GPT_HISTORY" }
        if ($gpt.fingerprint_sha256 -ceq [string]$current.fingerprint_sha256 -and
            ($gpt.status -cne "PASS" -or $gpt.blockers -isnot [System.Array] -or
             $gpt.findings -isnot [System.Array] -or $gpt.blockers.Count -gt 0 -or $gpt.findings.Count -gt 0)) {
            throw "TWO_PARTY_AUDIT_KNOWN_GPT_FAILURE"
        }
    }
}
foreach ($auditor in $required) {
    $path = Join-Path $evidence ($auditor + ".json")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "THREE_PARTY_AUDIT_MISSING: $auditor"
    }
    $record = Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json
    if ($record -isnot [pscustomobject]) {
        throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor must be an object"
    }
    $requiredFields = @("schema","auditor","version","fingerprint_sha256","status","blockers","findings")
    foreach ($field in $requiredFields) {
        if ($record.PSObject.Properties.Name -notcontains $field) {
            throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor missing $field"
        }
    }
    if (($record.schema -isnot [int] -and $record.schema -isnot [long]) -or $record.schema -ne 1 -or
        $record.auditor -isnot [string] -or $record.auditor -cne $auditor -or
        $record.version -isnot [string] -or
        $record.fingerprint_sha256 -isnot [string] -or
        $record.status -isnot [string]) {
        throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor"
    }
    if ($record.blockers -isnot [System.Array] -or $record.findings -isnot [System.Array]) {
        throw "THREE_PARTY_AUDIT_INVALID_RECORD: $auditor blockers/findings must be arrays"
    }
    if ($record.version -cne $version) {
        throw "THREE_PARTY_AUDIT_VERSION_MISMATCH: $auditor=$($record.version)"
    }
    if ($record.fingerprint_sha256 -cne [string]$current.fingerprint_sha256) {
        throw "THREE_PARTY_AUDIT_STALE: $auditor fingerprint does not match current candidate"
    }
    $status = $record.status
    if ($status -in @("TOKEN_LIMITED","RATE_LIMITED","UNKNOWN_SUBMISSION_OUTCOME")) {
        throw "THREE_PARTY_AUDIT_INCOMPLETE: $auditor status=$status; report to user, continue other audits, and rerun this primary audit later"
    }
    if ($status -cne "PASS") {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor status=$status"
    }
    if ($record.blockers.Count -gt 0) {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor has open blockers"
    }
    if ($record.findings.Count -gt 0) {
        throw "THREE_PARTY_AUDIT_BLOCKED: $auditor PASS record still has open findings"
    }
}
if ($twoParty) {
    Write-Output ("OWNER_APPROVED_TWO_PARTY_AUDIT_GATE_OK version={0} fingerprint={1} gpt=UNAVAILABLE" -f $version,$current.fingerprint_sha256)
} else {
    Write-Output ("THREE_PARTY_AUDIT_GATE_OK version={0} fingerprint={1}" -f $version,$current.fingerprint_sha256)
}
