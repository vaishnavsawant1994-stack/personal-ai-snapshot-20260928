# Global Canonical Work Awareness — Implementation Prompt

You are implementing the next Vishnu product tranche in `vaishnavsawant1994-stack/vishnu`.

## Objective

Make Home, Today, and Vishnu's visible living/status surface reflect the same canonical Project Work state already used by Work Plan, Live Work, Activity, 3D Status, and 3D Project Structure.

The implementation must be production-safe, read-only at the global surface, responsive on desktop/mobile, and must preserve every existing execution, permission, approval, reauthentication, verification, recovery, and ToolRegistry invariant.

## Non-negotiable architecture

Canonical execution remains:

`Goal -> WorkPlan -> WorkOrders -> P10/P6 -> AgentExecutor -> ToolRegistry -> verification/evidence -> review/completion`

Global awareness is only:

`canonical Project Work -> owner-scoped read-only projection -> Home / Today / living status`

The global layer must never become an execution authority.

## Backend

Create a read-only `GlobalWorkService` and `GET /iphone/api/work/summary` endpoint.

The endpoint must:
- require the existing owner device authentication
- read Project records from `ProjectStore`
- read Project-bound plan records from the existing Work bridge
- read authoritative P10 task state from `AdvancedAutonomy.plan(...)`
- read canonical WorkOrder metadata from `AdvancedAutonomy.work_plan(...)`
- aggregate per-project state and global counts
- include active, verifying, recovering, waiting approval, blocked/recovery, ready, completed, total WorkOrder counts
- include project name/id, plan id/version/readiness/state/replan count
- include WorkOrder id/task id/title/objective/worker type/requested tool/status/ready state
- expose a deterministic living state and detail string
- prioritize waiting approval, then blocked/recovery, then verifying/running, then ready, then idle
- never enumerate evidence bodies for this Home/Today summary
- never expose POST/PATCH/DELETE routes
- never execute, approve, retry, recover, pause, resume, cancel, verify, or mutate anything

Wire this router into `server/cloud_app.py`.

## PWA

Add `pwa/global-work-awareness.js` and load it only after:
1. `home-chat-redesign-core.js`
2. `projects-work-runtime.js`
3. `projects-work-visualization-runtime.js`

The adapter must call only `GET /iphone/api/work/summary`.

### Home

Insert a compact canonical Work pulse before Recent Projects.

Show:
- highest-priority global state
- copy such as Vishnu is working / Needs Approval / Needs Attention / Verifying / Ready
- active count
- waiting approval count
- blocked/recovery count
- ready count
- up to three highest-priority WorkOrders
- Project name and worker role

Clicking a WorkOrder must deep-link to the existing Project `Live work` tab with `openProject(projectId, 'live')`.

Do not start work from Home.

### Today

Add a `Vishnu work` section without replacing existing Tasks, Meetings, or Plans.

Show current canonical WorkOrders that are:
- running
- verifying
- recovering/retrying
- waiting approval
- blocked/uncertain/recovery-required/failed
- ready to continue

Hide this section when the Today filter is Meetings.

Clicking an item opens existing Project Live Work. No mutation action is permitted.

### Living/status surface

Update the visible `stateLabel` and `status` copy from canonical Work only when foreground `stateName` is one of:
- idle
- active
- background

Never overwrite foreground conversation states such as:
- listening
- understanding
- thinking
- responding
- memory retrieval
- knowledge retrieval
- foreground approval
- error

Do not invent a second execution state machine.

## Offline/cache

Advance the PWA service-worker cache revision and precache `global-work-awareness.js`.

API responses remain network-only and must not be cached by the service worker.

## Tests

Add backend unit tests that prove:
- multiple Projects aggregate correctly
- WorkOrder metadata maps from canonical WorkPlans to P10 task state
- dependency-complete WAITING tasks become ready
- approval and recovery counts are correct
- living-state priority is deterministic
- projects without WorkPlans are not fabricated into Work state
- the service has no mutation methods

Add static PWA contract tests that prove:
- only the summary GET endpoint is used
- no execute/pause/resume/cancel/approve paths exist in the adapter
- Home, Today, and living status hooks exist
- the adapter only overlays living status for idle/active/background foreground state
- the loader order is correct
- the asset is offline-preloaded
- JavaScript syntax is valid

Add Playwright/Chromium qualification at 390x844 and 1440x1000 that proves:
- Home pulse renders canonical state/counts
- Today renders canonical WorkOrders
- status copy reflects canonical state while idle
- foreground thinking state is not overwritten
- WorkOrder click opens the existing Live Work tab
- no horizontal overflow on mobile
- no JavaScript page errors
- the global adapter makes zero non-GET requests

Run the existing Projects browser suites in the same workflow.

## Release gates

Do not merge unless the exact PR head passes:
- full `pytest -q`
- P3 iPhone PWA/security
- responsive design-system browser checks
- PWA mobile visual preview including the new global Work browser test
- Reliability and Security including P10 adversarial/durability and soak
- Package Validation on Ubuntu, macOS, and Windows

If Playwright installation fails because of an external CDN/location error, classify it as infrastructure, rerun only that failed job, and still require an actual green Chromium execution before merge.

## Definition of done

Done means:
- Home truthfully shows what Vishnu is doing across Projects
- Today includes real WorkOrders without replacing user tasks/meetings/plans
- the living/status surface reflects background Work only when no foreground turn owns the status
- every global item links to canonical Live Work
- the global layer cannot execute or approve anything
- the backend summary is owner-scoped and GET-only
- mobile and desktop Chromium tests pass
- the exact candidate passes the repository-wide release gates
- the PR is merged into `main` only after qualification
