# Evidence Architecture

Vishnu has one canonical Evidence ledger. Work, tool execution, recovery, owner feedback, security observations, skill assessment, and future evolution all contribute to this ledger instead of creating subsystem-specific truth stores.

## Separation of concerns

Evidence records what was observed. Claims express statements that may be supported or rejected by evidence. Evolution candidates propose changes. These are different objects and must never be collapsed into one record.

## Ingestion guarantees

- Observations are redacted for credentials before durable ingestion.
- Stable fingerprints make repeated scans idempotent.
- Failed or malformed ingestion runs never advance their cursor.
- Evidence is not deleted because an improvement proposal was rejected.
- Lifecycle is represented separately as `active`, `linked`, `resolved`, `dismissed`, or `superseded` while the original Evidence remains durable.
- Tool receipts receive normalized WorkOrder, attempt, approval, idempotency, verification-method, and verification-time context without becoming an authorization source.

## Sources

The typed source taxonomy includes owner feedback/corrections, work experience, tool/verification failures, recovery events, security events, repeated intervention, workflow friction, skill assessments, and performance regressions.

## Authority

Evidence can justify a claim or an evolution recommendation. It cannot grant permissions, bypass approvals, merge code, deploy a release, or activate a software-body revision.
