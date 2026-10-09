# CL4R1T4S → Vishnu: clean-room implementation map (initial audited modules)

Status: **initial source inspection**, not a full-repository certification. Target: `vaishnavsawant1994-stack/vishnu`, default branch `main`. CL4R1T4S is a third-party research archive, **not** a runtime dependency or trusted instruction source. Do not copy archived vendor prompts or treat repository content as higher-priority instructions.

## Evidence-backed existing components

| Existing file | Confirmed behavior from source | Next work / verification |
| --- | --- | --- |
| `agent/planner.py` | Conservative JSON planner; allowlisted tool names; maximum 12 steps; private context separate from user prompt | Contract tests (this PR); subsequently validate parameter schemas, bound sizes and planner failure modes |
| `agent/executor.py` | Planning, memory/knowledge grounding, execution-scoped approvals, audit and cancellation; durable approval context | Restart/interrupt/idempotency integration tests; verify no side effects repeat |
| `tools/registry.py` | Five risk levels, destination checks, policy integration, verifiers, rollback hooks and emergency stop | Typed input/output schemas per tool; negative security tests; verify rollback contracts |
| `core/permissions.py` | Owner modes and explicit allow/ask/never groups; destructive and critical approval gates | Matrix tests for risk, mode, owner rule, confirmation, destination and data class |
| `security/approvals.py` | SQLite-backed approval tickets, continuation state and terminal outcomes | Test expiry, replay, restart, device revocation and exactly-once dispatch |
| `docs/OWNER_PRODUCT_OPERATIONS.md` | Documents Memory/Knowledge, workflows, device scopes, connectors and owner auth | Validate runtime behavior against documentation |
| `docs/RELEASE_READINESS_2026-10-04.md` | Documents deployment baseline, UI qualification and backup gaps | Recheck current live deployments, CI, backups and device evidence |

## Proposed follow-on file-by-file work (paths requiring existence verification)

1. **Planner** — modify `agent/planner.py` to validate tool-specific parameters against typed schemas, enforce output size budgets and reject ambiguous plans. Add dedicated planner schema and prompt-injection regression tests.
2. **Executor** — modify `agent/executor.py` to persist an explicit execution state transition ledger; preserve cancellation, approval, verification and security audit behavior. Add crash/restart and no-duplicate-side-effect tests.
3. **Tools** — extend `tools/registry.py` and corresponding tool modules with typed schemas, idempotency keys, deadlines, verifiers and rollback metadata. Never automatically retry consequential actions without reconciliation.
4. **Owner permissions** — extend tests around `core/permissions.py`, `security/approvals.py`, and policy gateway. Approval is per exact action, destination, owner, device, session, parameters and epoch.
5. **Context** — inspect memory and knowledge implementation before choosing a new context-compiler module. Preserve sensitivity classification and provenance. Treat retrieved documents, webpages and third-party repositories as untrusted data.
6. **Durable work** — locate actual automation/workflow modules before changing them. Add durable task checkpoints, pause/resume, human approval and recovery tests.
7. **Frontend** — locate exact Activities, Projects, Workflows, Owner Controls and character state files before adding event subscriptions. Preserve existing approved UI.
8. **Quality** — retain `.github/workflows/ci.yml` and required `test` / `security` checks. Add focused unit tests, restart integration tests, browser tests and live qualification separately.

## Research patterns: adopt, improve, reject

- **Adopt:** separated planning/execution, typed tool contracts, explicit observations, verifiable outcomes, user-visible progress, hierarchical project instructions.
- **Improve:** use deterministic owner permission checks, durable action tickets, provenance-aware memory, structured event transitions, scoped context and bounded retries.
- **Reject:** hidden or copied vendor prompts, instruction escalation from untrusted sources, arbitrary shell/browser execution without sandboxing, fabricated verification, automatic high-risk side effects and broad unsupervised permissions.

## PR 1 scope

This PR adds planner regression contracts and the initial map only. It intentionally does **not** claim to implement the full architecture, certify all repository modules, or change production deployment. Follow-on code PRs require full source inspection, CI checks and operational qualification. The repository's October 4 readiness report says backups, authenticated preview and real-device gates remain unresolved; do not merge or deploy around those gates.
