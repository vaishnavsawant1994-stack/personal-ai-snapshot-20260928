# Work Orchestration Release Qualification

This qualification is scoped to the canonical Vishnu Work Orchestration subsystem.
It records whether one exact commit is qualified for the Work Orchestration program;
it is not a deployment action and it is not a declaration that the entire Vishnu
product is production-ready.

## Exact-head requirements

A Work Orchestration release candidate is `QUALIFIED` only when all of the following
refer to the same exact 40-character Git commit SHA:

- canonical Work consistency gate
- canonical Work scale/performance gate
- canonical Work final scenario gate
- full repository pytest suite
- P3 iPhone PWA integration/security gate
- Reliability and Security gate
- P10 adversarial/durability qualification
- P10 performance qualification
- P10 soak qualification
- package validation on Ubuntu, macOS, and Windows
- the final Work qualification report and every required scenario

Missing, false, stale, malformed, or SHA-mismatched evidence produces `HOLD`.

## Authority boundary

This layer is qualification metadata only. It cannot execute tools, approve owner
actions, recover uncertain effects, verify claims, deploy software, promote a release,
or bypass any existing authority. P10/P6 remains execution authority; ApprovalManager,
RecoveryAuthority, EvidenceStore, DomainClaimGate, deterministic review, Completion
Judge, GovernedMemory, and the core event bus retain their established responsibilities.

## Product production readiness is separate

A Work Orchestration `QUALIFIED` result does **not** imply that Vishnu as a complete
product is production-ready. Product release readiness remains controlled by the
existing `readiness/gate.py` evidence, including physical-device and distribution
requirements such as real iPhone checks, signing/notarization, release manifests,
updater/rollback qualification, and other product-level gates.
