# Durable Work Execution

Vishnu's canonical Work model remains the strategic source of work identity. Durable execution adds side-table history for attempts, leases, events, failures, and repository workspaces without replacing P10 compatibility or changing existing `WorkOrder` payload shape.

## Safety invariants

- A WorkOrder may have many attempts, but attempts are never rewritten into one another.
- At most one live lease may own a WorkOrder.
- Lease ownership is fenced by worker identity, lease token, and runtime epoch.
- An expired lease is not proof of failure. It transitions the prior attempt and WorkOrder to `recovery_required`.
- `unknown_effect` is never automatically retried.
- Explicit retries create a new attempt with `parent_attempt_id` pointing to the prior attempt.
- Execution success advances Work to verification; it does not by itself prove completion.
- Code workspaces store portable repository/revision references, never machine-local absolute paths.

## Failure classes

Known transient/network/upstream/rate-limit failures may be eligible for bounded automatic retry. Permission, policy, validation, budget, timeout, dirty-workspace, and unknown failures require explicit retry. Unknown effects require reconciliation before any retry.
