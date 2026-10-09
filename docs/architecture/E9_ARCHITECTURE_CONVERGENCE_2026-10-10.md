# E9 Persistent-Agent Architecture Convergence

Date: 2026-10-10
Repository: `vaishnavsawant1994-stack/vishnu`
Tracking issue: #109
Implementation PR: #111

## Status

E9 is the convergence tranche following the qualified E1–E8 architecture. It does not replace the proven E1–E8 safety boundaries. It connects them so normal reasoning, tools, Work, Evidence, Evolution, software-body adoption, automation, providers/extensions and cross-host continuity share one explicit authority model.

## E9A — planner and tool contracts

The simple conversational planner now supports bounded execution metadata: step ids, earlier-step dependencies, success criteria, verification metadata, safe retry metadata, per-step timeout and execution budgets. Prohibited tools are excluded from planning.

Planning metadata is never authorization. Runtime authorization remains in ToolRegistry, permissions, approvals, E8 host continuation authority and governed execution.

Tools may declare bounded input/output schemas and/or validators. Validation occurs before permission/risk evaluation and again at the exact handler boundary; outputs are validated before verification/receipt completion. Legacy tools remain compatible.

## E9B — live Body and private Self

`IdentityRuntime` loads `config/vishnu-body.yaml`, the active Body lineage and the latest private Self. A bounded identity envelope is supplied to planning and final reasoning as behavior/relationship context.

Self can shape communication and relationship continuity. Self cannot grant permissions, capabilities, approval, merge, deploy, Body activation, security-policy changes or continuation authority.

The first exact running revision may bootstrap an empty Body lineage. Later revisions are never auto-activated by a model or by startup.

### Normal trusted release activation

For an already-initialized installation, an owner/operator-approved release can activate the exact running revision at deploy time with both variables:

```text
VISHNU_TRUSTED_RELEASE_REVISION=<exact-running-git-sha>
VISHNU_TRUSTED_RELEASE_ACTIVATE=1
```

Activation occurs only when the supplied release revision exactly equals the running revision. A mismatched or absent revision fails closed. This path represents external release authority; it is not available to Self, Evolution candidates or model output.

Owner surfaces:

- `GET /api/identity/status`
- `GET /api/identity/body` (read-only)
- `GET /api/identity/self`
- `PUT /api/identity/self` (behavior-only validated Self)

There is intentionally no convenience Body-activation endpoint.

## E9C — continuous Evidence and governed co-evolution

Canonical Evidence now receives bounded runtime signals for owner feedback/corrections, verification failure, workflow friction/failure, recovery, security events, repeated intervention and skill assessment.

Owner surfaces:

- `GET /api/evidence`
- `GET /api/evidence/{id}`
- `POST /api/evidence/feedback`
- `POST /api/evidence/correction`

Evidence deletion is intentionally not exposed.

`ContinuousEvolutionRuntime` can run the existing E5 `CO_EVOLVE` recommendation cycle on a bounded cadence. Default cadence is daily and cannot be configured below one hour or above seven days. It may ingest Evidence and synthesize/curate recommendations. It cannot approve, hand off, merge, deploy or activate a Body.

## E9D — canonical Work execution convergence

The old P10 document/runtime remains as a compatibility orchestration surface, while canonical Work owns durable dispatch identity, attempts, leases and recovery state.

Runtime mode is `canonical_authority`. Startup backfill is promoted to that mode before old durable P10 documents are projected.

For governed P10 work:

1. canonical WorkOrder dependency readiness is checked;
2. a canonical attempt and lease are claimed;
3. the qualified P10/P6 compatibility executor performs the existing governed action;
4. approvals/resources park the same causal attempt and release its lease;
5. owner approval resumes the same attempt with a fresh lease;
6. verified completion records canonical Evidence, then preserves the existing Evidence→Claim gate required by the deterministic completion judge;
7. unknown/interrupted outcomes become `RECOVERY_REQUIRED`, never blind retry;
8. deterministic completion remains proof-driven and client/model completion flags remain non-authoritative.

Automation definitions and their proven budget/approval executor remain intact. Both multi-step workflow runs and legacy scheduled automations now receive deterministic canonical Work occurrence identities, so global Work can represent them without adding a second automation executor.

## E9E — provider and extension conformance

Provider capability contracts normalize reasoning/tool/repository/review/deployment/storage/notification capabilities. Capability declarations are descriptive and never authorization.

`tests/conformance/` now covers provider, extension, Work, automation and trusted-release contracts.

Extension manifests can declare capabilities and requested permission/data/network/filesystem/background scopes. Installation or discovery grants nothing. Only the owner can grant a permission, and only if the extension declared it. A changed manifest hash invalidates previous grants and requires re-review.

## E9F — cleanup and certification

The E9 CI workflow contains a dedicated `E9 architecture convergence gate` before release qualification and the full repository suite.

Final merge requirements:

1. exact PR head passes CI;
2. exact PR head passes Reliability and Security;
3. exact PR head passes Package Validation on supported runners;
4. exact PR head passes P3 iPhone PWA qualification;
5. old PRs #97 and #98 are closed as superseded only after their functionality is present and qualified in #111;
6. PR #111 merges only after the exact head is green;
7. push-triggered CI on the exact final `main` merge commit passes;
8. issue #109 is closed only after post-merge qualification.

Historical implementation branches may then be removed. Branch deletion is repository hygiene and does not alter runtime authority or qualification.

## Governed Body contract

E9 advances `config/vishnu-body.yaml` to Body version 2 and records current contract generations for canonical Work, Evidence, Evolution, Continuity and extensions. Software source, tests, schemas, migrations, policy and conformance tests remain part of the governed Body identified by the exact Git revision.

## Final invariant

Vishnu may observe itself, learn from evidence, recommend changes and implement owner-approved changes in isolated software workspaces. It may not grant itself the authority to adopt those changes.

The model is replaceable. The UI is replaceable. A host is replaceable. Vishnu continuity is the governed combination of Body lineage, private Self, durable memory, canonical Work, Evidence, owner authority and fenced continuation state.
