# LAKIS Three-Party Audit Release Policy

For every public LAKIS release, "3자 감사" means three independent primary audits:

- GPT audit
- DeepSeek Scout audit
- Codex audit

## Release rule

A public release is blocked unless all three primary audit records are PASS for the exact same candidate fingerprint and release version, and the Private RC full-chain also passes.

Any executable/runtime/build/installer/updater/workflow/release-gate change that changes the candidate fingerprint invalidates every previous audit PASS. All three primary audits must then be repeated against the new fingerprint. Mutable audit evidence, FEATURE_STATUS_MATRIX.md, NEXT_RELEASE.md, and final release-note/report updates are intentionally outside the fingerprint so recording completed audits does not invalidate the audited candidate.

## Token/resource shortage rule

DeepSeek or Codex token exhaustion, context exhaustion, rate limit, or unknown submission outcome is never a PASS.

When one of those conditions occurs:

1. Report the exact auditor, status, and known usage to the user.
2. Do not retry automatically.
3. Continue with the other available audits so work does not stop.
4. Mark the missing primary audit incomplete.
5. Public release remains blocked until the missing primary auditor later completes and returns PASS for the same current fingerprint.

A substitute or secondary audit may provide extra evidence, but it does not silently replace the missing primary auditor.

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

candidate freeze -> GPT audit -> DeepSeek audit -> Codex audit -> all three PASS on same fingerprint -> build the Private RC artifact set exactly once -> product-boundary checks -> Private RC full-chain PASS on those exact bytes -> explicit owner approval bound to the same fingerprint and artifact-set SHA -> publish those exact bytes without rebuilding -> public tag/release/manifest activation.

`.github/workflows/prepare-private-rc.yml` owns the one-time RC build and preserves it as a GitHub Actions artifact. `.github/workflows/publish-installer.yml` is manual-only, downloads the explicitly selected RC run, rechecks the three-party and release-approval gates, verifies the release tag points at the approved candidate ref, and must never rebuild the approved binaries.
