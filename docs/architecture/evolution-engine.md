# Governed Evolution Engine

Vishnu evolution is an Evidence-driven recommendation system, not unrestricted self-modification.

## E5 boundary

E5 supports `OFF` and `CO_EVOLVE`. `AUTO_EVOLVE` is reserved but disabled. The service may synthesize, deduplicate, redact, curate, recommend, defer, restrict, or reject candidates. It has no executor, tool registry, repository provider, deployment provider, merge API, Work handoff, or Body activation authority.

## Pipeline

`Evidence -> CandidateDraft -> EvolutionCandidate -> deterministic curator -> recommended / deferred / restricted`

Evidence and candidates remain separate durable objects. Rejecting a candidate does not delete its supporting Evidence.

## Protected scope

Candidates are restricted when they affect owner authority, permissions, approval enforcement, security/vault code, continuation authority/fencing, evolution's own safety boundary, release workflows, automatic merge/deploy behavior, Evidence deletion, or Body activation.

## Authority rule

A recommended candidate is only a recommendation. Later stages may add an owner-approved immutable handoff into canonical Work, but recommendation alone can never execute, merge, deploy, or activate a software-body revision.
