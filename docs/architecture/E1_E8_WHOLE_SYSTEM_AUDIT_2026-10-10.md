# E1–E8 Whole-System Qualification Audit

Date: 2026-10-10
Audited repository: `vaishnavsawant1994-stack/vishnu`
Audited base: `main` @ `6bb4fc6bdc9e3ab2ae8de7f2049ddf29af7d0d99`
Scope: E1 Identity/Body/Self through E8 cross-host continuation, plus stale PR/branch inventory and remaining convergence gaps.

## Executive result

**Status: QUALIFIED FOR CURRENT MERGED FUNCTIONALITY, NOT YET FULLY ARCHITECTURE-CONVERGED.**

The E1–E8 merge chain is real, integrated into `main`, and the exact merge commit passed the push-triggered full CI suite. The E8 PR head also passed CI, Reliability/Security, Package Validation and P3/iPhone qualification before merge.

No defect found in this audit requires rolling back E1–E8. However, several gaps remain before Vishnu should be described as having one fully converged persistent-agent execution architecture.

## Release evidence

- `main` merge commit: `6bb4fc6bdc9e3ab2ae8de7f2049ddf29af7d0d99` (PR #108).
- Exact E8 head merged by PR #108: `a103b07e559a47d2d0814a95a01385bee3b985a3`.
- Exact E8 head passed: CI, Reliability and Security, Package Validation, P3 iPhone PWA.
- Post-merge `main` push CI run `37987545620` passed compile, Work consistency/performance/final gates, E5, E6, E7, E8, Work release qualification and the full repository pytest suite.

## E1–E8 runtime status

| Stage | Audit result | Runtime finding |
| --- | --- | --- |
| E1 Body + Self | **PARTIAL INTEGRATION** | `IdentityStore`, Body manifest model, Self history and lineage are present. E7/E8 use Body lineage. But normal reasoning does not load `config/vishnu-body.yaml`, establish a baseline active Body revision, load latest Self, or inject `IdentityContextEnvelope` into planner/final-response context. |
| E2 Durable Work | **QUALIFIED SUBSTRATE / PARTIAL AUTHORITY** | Attempts, leases, recovery, workspaces and dispatcher exist. `P10WorkBridge` uses `DurableWorkStore`, but remains explicitly `observe_only`. Canonical Work is authoritative for E6/E7 evolution work, not yet the general P10/automation execution plane. |
| E3 Durable effects | **INTEGRATED** | `EffectAwareDurableAgentExecutor` is the common agent executor and adds governed receipts/evidence around the existing approval executor. E8 continuation authority is enforced at the side-effect boundary and approval resumption. |
| E4 Central Evidence | **INTEGRATED CORE / PARTIAL SOURCE WIRING** | Canonical Evidence v3, lifecycle, redaction, deduplication, cursors/runs and source adapters exist. Effect evidence is live. Feedback/work/recovery/security/skill source adapters are not yet comprehensively event-wired as a continuous ingestion service. |
| E5 Read-only evolution | **INTEGRATED, MANUAL CYCLE** | `EvolutionService` is runtime-wired, defaulting to CO_EVOLVE. Candidate synthesis/curation remains non-executing. The normal runtime does not schedule `run_cycle()` continuously; owner API scan is the primary trigger. |
| E6 Owner handoff | **INTEGRATED** | Owner-approved candidates create canonical Goal/Plan/WorkOrder plus immutable handoff. Generated Work receives no self-granted capabilities and later adoption remains separate. |
| E7 Code-body evolution | **INTEGRATED / OPT-IN** | Isolated local Git workspaces, protected-diff policy, exact revision verification, external review and separate owner adoption/activation are implemented. Repository mutation remains disabled unless explicitly configured. |
| E8 Cross-host continuity | **INTEGRATED** | Single-host continuation authority, fencing, one-time authenticated transfer, target-key rewrap, non-restorable security authority, replay ledger and stopped-runtime import are wired. Both ordinary effects and E7 code-body mutation respect the host authority fence. |

## High-priority integration gaps

### G1 — Identity exists but is not yet the live reasoning identity

The runtime creates `IdentityStore` but ordinary planner/final response context still uses the static string `You are Vishnu` plus memory/knowledge. The Body manifest and latest Self profile are not composed into the provider-neutral reasoning context.

Required E9 work:
1. Resolve exact running Git revision at runtime.
2. Load and validate `config/vishnu-body.yaml`.
3. Bootstrap the first trusted running revision into Body lineage without allowing later arbitrary self-activation.
4. Detect running-revision vs active-Body mismatch and fail closed for Body-governed operations.
5. Load latest private Self profile.
6. Compose a bounded `IdentityContextEnvelope` and pass it to planner/final-response reasoning as trusted application context, never as execution authority.
7. Add owner-safe Identity read/update API for Self only; Body activation remains governed separately.

### G2 — Legacy/simple planner did not receive the structured contract hardening

`agent/planner.py` on `main` is still the old minimal contract: max 12 steps, tool allowlist and parameter-object validation. It does not retain bounded execution budgets, dependency IDs, verification metadata, retry metadata, timeouts, success criteria, or explicit prohibited-tool filtering.

Old PR #97 contains useful, already-green implementation work but is based on a pre-E1–E8 `main`; it must not be merged directly.

Required E9 work: transplant/re-review the useful planner contract onto current `main`, add current-regression tests, and keep authorization in `ToolRegistry`/approvals rather than the planner.

### G3 — Typed tool input/output contracts never landed

`Tool` on current `main` has verifier/rollback/risk/permission metadata but no typed input/output validator contract. Old PR #98 added optional fail-closed validators and passed its own CI/security/package matrix, but predates E1–E8.

Required E9 work:
1. Rebase the contract concept onto current `ToolRegistry`.
2. Validate input before permission/risk evaluation and again at dispatch if preparation can mutate parameters.
3. Validate output before verification/receipt completion.
4. Preserve all E3/E8 effect-ledger and continuation-fence semantics.
5. Add conformance tests for legacy tools, typed tools and malformed provider/plugin tools.

### G4 — Canonical Work is not yet the single execution authority

`P10WorkBridge.mode = "observe_only"`; global Work UI explicitly reports `execution_authority = "existing_p10_p6_runtime"`. Automation also retains its own workflow/run persistence and directly invokes the agent turn runtime.

This is acceptable compatibility mode and is covered by current tests, but it means E2 is not yet the universal Work dispatcher described by the long-term architecture.

Required E9 migration:
1. Introduce an opt-in shadow dispatcher over selected P10 tasks.
2. Prove parity for dependencies, approvals, budgets, completion evidence and recovery.
3. Move one safe worker class at a time to canonical Work authority.
4. Route scheduled automation occurrences into deterministic WorkOrder identities while retaining existing automation definitions/UI.
5. Retire `observe_only` only after dual-run comparison and rollback qualification.

### G5 — Evidence-to-evolution loop is not continuous yet

The E4 source adapters exist, but the runtime does not yet have a bounded background ingestion/synthesis cadence for corrections, repeated intervention, workflow friction, recovery/security signals and skill assessment. E5 `CO_EVOLVE` is therefore an enabled capability, not a continuously operating loop.

Required E9 work:
- Add event adapters that create canonical Evidence only.
- Add bounded daily/owner-configurable synthesis cadence.
- Never allow scheduled evolution to approve, hand off, merge, deploy or activate.
- Preserve failed-scan cursor semantics and redaction.

## Medium-priority convergence gaps

### G6 — Provider/extension conformance layer is absent

The original architecture target included provider contracts and `tests/conformance/`; `tests/conformance/` and the proposed `extensions/` contract package are not present on `main`.

Required E9 work:
- Formalize provider capability contracts around existing model/tool/repository/review/deployment implementations without replacing working adapters.
- Add conformance tests for capability reporting, authorization separation, idempotency/verification declarations and failure normalization.
- Add extension manifests/permissions only when extension installation is exposed; installing an extension must never grant permissions automatically.

### G7 — Operator visibility is uneven across canonical stores

Work has strong project/global read-only surfaces through the existing PWA/cloud APIs, and Evolution/Continuity have owner APIs. There is no equivalent first-class owner API surface dedicated to canonical Evidence lifecycle and Identity/Self inspection.

Required E9 work: add owner-authenticated read surfaces and narrowly-scoped Self editing; do not expose arbitrary Evidence deletion or Body activation through convenience endpoints.

## Pull-request cleanup

### Closed during this audit

- PR #103 — stale E5 branch superseded by the qualified E5 implementation that later merged through the E1–E8 chain.
- PR #104 — stale E6 branch superseded by the qualified E6 implementation that later merged through the E1–E8 chain.

### Still open intentionally until E9 supersedes them

- PR #97 — CL4R1T4S planner-contract hardening. Requirement remains valid; branch is stale.
- PR #98 — typed tool input/output contracts. Requirement remains valid; branch is stale.

Neither #97 nor #98 should be merged directly into current `main`. Their useful changes should be transplanted into current E9 branches and then these PRs should be closed as superseded.

## Branch cleanup inventory

The repository still contains historical Enoch implementation branches after merge. These should be deleted after this audit/E9 work no longer needs them for comparison:

- `agent/enoch-persistence-e0-e1-20261009`
- `agent/enoch-work-e2-20261009`
- `agent/enoch-effects-e3-20261009`
- `agent/enoch-evidence-e4-20261009`
- `agent/enoch-evolution-e5-20261010`
- `agent/enoch-handoff-e6-20261010`
- `agent/enoch-code-body-e7-20261010`
- `agent/enoch-continuity-e8-20261010`

Abandoned/alternate branches that should also be removed once no longer needed:

- `agent/enoch-body-e7-20261009`
- `agent/enoch-evolution-e5-20261009`
- `agent/enoch-evolution-e6-handoff-20261009`
- `agent/enoch-continuity-e8-backup-20261010`
- `agent/claritas-planner-contract-20261009` after #97 is superseded
- `agent/typed-tool-contracts-20261009` after #98 is superseded

## E9 convergence sequence

1. **E9A — planner + typed tool contracts**: transplant #97/#98 concepts onto current `main`; current E1–E8 regression matrix must remain green.
2. **E9B — live Identity context**: Body baseline registration, mismatch detection, Self loading/context composition, owner-safe Identity API.
3. **E9C — Evidence/Evolution continuous wiring**: source event adapters + bounded synthesis cadence; no execution authority.
4. **E9D — canonical Work convergence**: P10 shadow execution, parity evidence, staged authority migration, automation occurrence → WorkOrder mapping.
5. **E9E — provider/extension conformance**: formal contracts and `tests/conformance/` over existing implementations.
6. **E9F — final cleanup/qualification**: close #97/#98 as superseded, delete stale branches, run full CI/security/package/PWA matrix, verify exact `main` post-merge CI, and publish a final architecture-converged release note.

## Final audit verdict

E1–E8 should remain merged. The current product has meaningful persistent-agent guarantees: durable Work primitives, governed effects, central Evidence, owner-governed evolution, isolated code-body implementation and fenced cross-host continuity.

But the phrase **"fully converged persistent-agent architecture"** should be reserved until E9A–E9F are complete, because normal reasoning identity, the legacy planner/tool contract path, general Work execution authority, continuous evidence/evolution wiring and provider/extension conformance are not yet unified under the new architecture.
