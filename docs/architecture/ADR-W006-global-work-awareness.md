# ADR-W006 — Global Work Awareness Is Read-Only

Status: Proposed

## Decision

Home, Today, and Vishnu's visible background status will consume a single owner-scoped read-only canonical Work summary. They will not become a second orchestration or execution surface.

The summary is produced by `GlobalWorkService` from Project-bound canonical Work/P10 state and exposed through `GET /iphone/api/work/summary`.

## Why

Vishnu already has qualified execution, approval, verification, recovery, and Project Work paths. Recreating any of those behaviors in Home or Today would introduce state drift and unsafe duplicate authority.

## Consequences

- Home/Today can truthfully show active, verifying, approval, blocked/recovery, ready, and completed Work state.
- WorkOrder rows deep-link to existing Project Live Work.
- Foreground conversation status remains authoritative while the user is actively interacting.
- The summary endpoint requires owner device authentication but no mutation-capable trusted-session authority.
- Evidence bodies are not enumerated by the global summary.
- Any future global controls must call the existing governed Project Work endpoints rather than adding authority to this service.
