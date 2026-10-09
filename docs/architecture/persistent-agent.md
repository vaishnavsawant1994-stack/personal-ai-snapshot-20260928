# Vishnu Persistent-Agent Contract

Status: E0 architecture freeze

## Identity boundary

Vishnu is not identified by a particular LLM, host, UI, device, process, or provider. Persistent continuity is carried by the combination of:

- private Self and owner relationship state;
- durable memory;
- authorized software-body lineage;
- durable Work and approval state;
- verified Evidence and receipts;
- governed evolution history; and
- continuation authority.

A model, runtime, server, device or surface may change without creating a new Vishnu when those continuity contracts are preserved.

## Canonical subsystem ownership

Existing Vishnu systems remain authoritative. The Enoch-informed work must extend them rather than create parallel control planes:

- `future_intelligence/work_orchestration` owns durable Work;
- `evidence` owns observations, receipts, claims and verification;
- `memory` owns memory and knowledge continuity;
- `automation` owns schedules and recurring triggers;
- `core/permissions.py` plus approval runtime own authority;
- `identity` owns Body/Self lineage;
- future `evolution` may propose changes but cannot execute tools directly;
- future `continuity` owns cross-runtime checkpointing and fencing.

## Authority invariant

Private identity, memory, prompts, models, providers, extensions and evolution candidates are not permission sources. Consequential authority comes only from Vishnu's permission and approval systems.

## Evolution invariant

Vishnu may observe operation, retain evidence, synthesize improvement candidates and implement an owner-approved candidate through canonical Work. It may not grant itself permission to merge, deploy, activate a new body revision, or weaken the authority boundary governing that change.

## Compatibility rule

All Enoch-informed migrations are additive until legacy/P10 compatibility paths have been separately qualified and explicitly retired. Foundation work must not silently replace existing persistent state.
