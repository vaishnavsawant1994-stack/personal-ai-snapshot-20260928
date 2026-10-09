# Global Work Awareness

Global Work Awareness is the read-only product projection that lets Home, Today, and Vishnu's visible status reflect canonical Project Work across all active Projects.

## Source of truth

The endpoint is `GET /iphone/api/work/summary`.

It projects existing Project-bound P10 plans and canonical WorkPlans. It does not create goals or plans, execute WorkOrders, approve actions, retry work, verify claims, or recover operations.

Execution authority remains unchanged:

`Project Work API -> existing P10/P6 runtime -> AgentExecutor -> ToolRegistry -> verification/evidence`

The global surface is only:

`canonical Project Work -> read-only summary -> Home / Today / living status`

## Product behavior

Home shows the highest-priority current state plus active, approval, blocked, and ready counts. Current WorkOrders deep-link into the existing Project Live Work tab.

Today adds a Vishnu Work section containing active, approval, blocked/recovery, and ready WorkOrders while preserving existing owner tasks, meetings, and plans.

The living status may update visible copy only while the foreground conversation state is idle, active, or background. Listening, understanding, thinking, responding, memory/knowledge retrieval, approval, and error states owned by the foreground turn are not overwritten.

## Priority

Global attention is ordered as:

1. waiting approval
2. blocked / uncertain / failed / recovery required
3. verifying / recovering / retrying / running
4. ready
5. completed history

## Security invariants

- owner device authentication is required for the summary endpoint
- the endpoint is GET-only
- no trusted-session mutation authority is added
- the PWA adapter issues GET requests only
- the adapter cannot approve, execute, pause, resume, cancel, retry, recover, or verify
- Live Work remains the canonical drill-down surface

## Qualification

Required gates include backend aggregation tests, JS syntax checks, PWA contract tests, Chromium mobile/desktop qualification, existing Projects browser tests, full pytest, security/reliability qualification, and packaging validation.
