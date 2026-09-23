# LAKIS Three-Party Audit Release Policy

For every public LAKIS release, "3자 감사" means three independent primary audits:

- GPT audit
- DeepSeek Scout audit
- Codex audit

## Release rule

A public release requires all three primary audit records to PASS for the exact same candidate fingerprint and release version, except for the explicit owner-approved GPT outage exception below. The Private RC full-chain and final artifact approval remain required in either mode.

The pre-public Private RC full-chain may use the tester-only bootstrap and loopback server documented under `tools/rc_patcher`. Its checks must be named honestly: "tester bootstrap from v7.4.5" is separate from the production-identical candidate Launcher/Updater path. The shipped v7.4.5 updater is not credited with private-manifest support. A check that cannot execute is recorded as skipped/blocked, never asserted PASS.

Any executable/runtime/build/installer/updater/workflow/release-gate change that changes the candidate fingerprint invalidates every previous audit PASS. All required primary audits (three normally, two under an approved exception) must then be repeated against the new fingerprint. Each record must describe its actual reviewed scope and limitations; an excerpt-only review must not be described as an exhaustive whole-source review. Mutable audit evidence, FEATURE_STATUS_MATRIX.md, NEXT_RELEASE.md, and final release-note/report updates are intentionally outside the fingerprint so recording completed audits does not invalidate the audited candidate.

## Token/resource shortage rule

For audits, the owner has removed local token/cost budget caps. Do not truncate
the selected audit material to fit a Scout budget. Provider context/output
limits and transport timeouts still apply and must be recorded honestly.
Select output capacity for the audit rather than inheriting the ordinary
Scout output cap. This does not change non-audit Scout defaults or authorize
automatic retries or model fallback.

DeepSeek or Codex token exhaustion, context exhaustion, rate limit, or unknown submission outcome is never a PASS.

When one of those conditions occurs:

1. Report the exact auditor, status, and known usage to the user.
2. Do not retry automatically.
3. Continue with the other available audits so work does not stop.
4. Mark the missing primary audit incomplete.
5. Public release remains blocked until the missing primary auditor later completes and returns PASS for the same current fingerprint.

A substitute or secondary audit may provide extra evidence, but it does not silently replace the missing primary auditor.

## Owner-approved GPT outage exception

When GPT is demonstrably unavailable, the owner may explicitly authorize a
DeepSeek + Codex two-party audit for one exact candidate fingerprint. This is
never inferred. Store `owner-two-party-exception.json` with the exact version
and fingerprint, `owner_approved: true`, `reason: GPT_SERVICE_UNAVAILABLE`, and
`required_auditors: [deepseek, codex]`. Both remaining auditors must PASS with
empty blockers and findings for that same fingerprint. A stale or malformed
exception blocks release, and it cannot excuse a missing DeepSeek or Codex
record.

The exception records a local owner instruction; it is not a GPT PASS. Preserve
prior audit records in an archive, record the owner's instruction and audit
scope, and report GPT as unavailable. The exception expires when the candidate
fingerprint changes. It never waives Private RC, artifact hashes, user-data
protection, or final publication approval.

Historical GPT records may remain present. Their presence does not establish
current availability or count as a PASS. A known GPT failure or open finding
for the exact current fingerprint still blocks the outage exception.

## Evidence records

Store release audit records under release_audits/v<version>/:

- gpt.json
- deepseek.json
- codex.json

Each record uses:

- schema: 1
- auditor: gpt | deepseek | codex
- version
- fingerprint_sha256
- status: PASS | FAIL | TOKEN_LIMITED | RATE_LIMITED | UNKNOWN_SUBMISSION_OUTCOME | ERROR
- blockers: []
- findings: []
- optional usage and notes

For a `PASS` record, both `blockers` and `findings` must be empty. Non-blocking observations belong in `notes`, not `findings`.

installer/Test-ThreePartyAuditGate.ps1 verifies the records against the current release-surface fingerprint.

## Final release gate

candidate freeze -> required audits (GPT + DeepSeek + Codex, or owner-approved DeepSeek + Codex during GPT outage) PASS on the same fingerprint -> build the Private RC artifact set exactly once -> product-boundary checks -> Private RC full-chain PASS on those exact bytes -> explicit owner approval bound to the same fingerprint and artifact-set SHA -> publish those exact bytes without rebuilding -> public tag/release/manifest activation.

`.github/workflows/prepare-private-rc.yml` owns the one-time RC build and preserves it as a GitHub Actions artifact. The tester-only loopback route exercises those exact bytes before publication without changing public defaults. `.github/workflows/publish-installer.yml` is manual-only, downloads the explicitly selected RC run, rechecks the three-party and release-approval gates, verifies both the recorded source commit and release tag against the approved candidate ref, and must never rebuild the approved binaries.

`candidate_ref` remains the exact commit used for the RC build and tag. Approval
records created after testing live at a separate immutable `approval_ref`; the
publisher checks out only those records in a separate directory. They must
still match the candidate fingerprint and exact artifact-set SHA, including
`private-rc-build.json`. Recording approval never requires rebuilding the
candidate or pretending the later evidence commit built the original binaries.
