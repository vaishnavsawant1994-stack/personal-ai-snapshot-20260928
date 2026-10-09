# Evolution Handoff Boundary

An Evolution recommendation does not execute. E6 adds one narrow transition: a human owner may approve a `RECOMMENDED` non-protected candidate for implementation work.

The handoff requires Evolution and canonical Work to share one SQLite transaction connection. A single `BEGIN IMMEDIATE` transaction records the owner decision, creates a dedicated Goal/Plan/WorkOrder, writes the immutable handoff, records a Work event, and marks the candidate handed-off. Any failure rolls back the entire transition.

Handoffs are immutable at the database layer: UPDATE and DELETE are rejected by triggers.

The generated WorkOrder receives no self-granted capabilities. It carries the candidate's approved resource scope, test plan, Evidence references, base Body revision, and explicit requirements for separate owner approval before merge, deployment, or Body activation.

E6 does not provide merge, deploy, repository mutation, or Body-activation APIs. Those are separate later authority boundaries.
