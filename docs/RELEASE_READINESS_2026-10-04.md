# Release readiness and operating model

Review date: 2026-10-04  
Decision: qualify a single-owner hosted release before promoting the preview UI to production.

## Source of truth and deployment identity

This repository is the operational source of truth for new code and current Railway deployments. The historical source repository named by the import commits remains unresolved; this operational designation does not claim that the original Git history is complete.

| Environment | Railway project / service | Branch and deployed commit | Region / storage | Domain |
|---|---|---|---|---|
| Stable runtime | `personal-ai-runtime` / `personal-ai-runtime` | `main` · `2e74e8a45cd9543b7578bb879df39a90d407737e` | iad, one replica, 500 MB volume mounted at `/data` | [personal-ai-runtime-production.up.railway.app](https://personal-ai-runtime-production.up.railway.app) |
| Qualification service | `personal-ai-runtime` / `personal-ai-iphone-qualification` | `ui/compact-neural-header-home-20260930` · `36eeb003647dc8f1e72673e6d3bfaf55ebef1155` | iad, one replica, separate 500 MB volume mounted at `/data` | No public URL recorded |
| UI preview | `personal-ai-secondary-preview` / `personal-ai-mobile-preview` | `ui/approved-pages-implementation-20261003` · `0ea5ccd2bc0ce5f4434c78c38c59a84e354103fe` | iad, one replica, separate 500 MB volume mounted at `/data` | [personal-ai-mobile-preview-production.up.railway.app](https://personal-ai-mobile-preview-production.up.railway.app) |

The stable deployment was reported SUCCESS by Railway on 2026-09-29. Its deployed commit is behind current `main`, which currently contains later documentation-only work. Railway also reports the qualification service deployment `d07ff6d8-12b3-4e7e-ad61-131bbacab78f` SUCCESS on 2026-09-30 at `36eeb003647dc8f1e72673e6d3bfaf55ebef1155`. The preview deployment `042aef30-8b37-43ad-b5f4-991d9a5933d1` was SUCCESS on 2026-10-04 at the exact UI candidate above. Stable and qualification services share the stable project but use separate volumes; preview is in a separate project. Neither public domain is custom.

## Product scope and architecture

The current operating decision is **single owner**. The repository combines a Python desktop application (PyQt6), local FastAPI control surface, mobile-oriented web/PWA UI, companion application areas, and packaging workflows. The hosted Railway service is a single application process backed by SQLite on a persistent `/data` volume. Model routing supports local OpenAI-compatible and OpenRouter-style providers; tools use risk levels and explicit autonomy modes. The product includes conversation and memory records, tasks, knowledge ingestion/search, workflow execution, device scopes, audit/recovery, and voice interfaces.

This deployment is not evidence of a multi-tenant service. Do not add public sign-up or claim user-to-user isolation without implementing separate tenant identity, authorization, storage isolation, migration, and abuse controls. SQLite remains a reasonable fit for one owner and a single active service replica; it is not the immediate scaling bottleneck shown by current telemetry.

## Branch protection and CI

An active GitHub repository ruleset, **Protect main — pull request and core checks**, applies to the default branch. It requires pull requests, up-to-date branches, and the GitHub Actions checks `test` and `security`; it blocks deletion and force-pushes and has no bypass actors. Both checks are bound to the GitHub Actions integration. Required reviews are zero because this is currently a single-owner repository; adding reviewers is appropriate if ownership expands.

The two checks provide a small global merge gate. Android emulator instrumentation and iOS simulator builds run on companion-code changes or by manual dispatch; physical Android/iPhone runs, provider-backed tests, long soak runs, TestFlight, and signed releases remain manual or specialized gates. PWA and P3 visual checks remain path-filtered. The PR #29 responsive workflow and platform/package checks passed on the preceding candidate head; its documentation update is being rerun against the final PR head. The ruleset's check contexts were corrected from stale names (`CI / test` and `Reliability and Security / security`) to the actual GitHub Actions contexts (`test` and `security`) and source-restricted to GitHub Actions. Confirm the final head shows both required checks as successful before merge. Do not require a path-filtered workflow globally unless an always-running summary check guarantees a status for every PR. The static PWA Playwright workflow intercepts `/iphone/api/...` and returns fixtures; it verifies frontend behavior, not production authentication, API integration, or durable records.

## Data durability and recovery

Railway confirms that volume backups cover SQLite files and offers daily (6-day retention), weekly (27-day), and monthly (89-day) schedules. Railway’s current documentation also says backups restore only into the same project/environment, wiping a volume deletes backups, and manual backups are limited to half the volume capacity. These snapshots are useful but are not an off-platform recovery copy.

**Observed:** the preview service’s Backups page showed no backups and stated that creating backups or enabling PITR is available only on Pro. The preview workspace was on a trial/free allowance. Railway inventory confirms the stable workspace contains both the runtime and qualification services, each with its own 500 MB `/data` volume; the connected Railway API does not expose backup inventory or schedule controls. The stable workspace is accessible through the Railway API, but its backup schedules have not been verified in either service’s Backups page. Do not claim that backups are enabled for production or qualification data.

**Required before production data is called safe:**
1. Inspect the stable service’s Backups page under its owning Railway account and enable a suitable schedule if the plan permits.
2. Check actual SQLite file size and free volume headroom before creating a manual snapshot.
3. Create an encrypted application-level export outside the Railway project, with the decryption key held separately from the archive.
4. Perform an isolated restore to a separate volume/service; check SQLite integrity, expected record counts, encryption-key recovery, and app startup before accepting the restored copy.
5. Record backup timestamps, retention, off-project location, key recovery, restore evidence, and recovery-point/recovery-time objectives.

Never test restore by overwriting the live `/data` volume.

## UI and device qualification

The preview candidate already contains the merged reference repair, interaction polish, whole-project surfaces, movable dialogs, and mobile dialog layout/touch-drag work. Test the deployed SHA above; do not start another overlapping popup branch.

The mock-driven browser workflow now covers 320×568, 390×844, and 430×932 phone sizes; 768×1024 tablet portrait; 1024×768 tablet landscape; 1366×768 desktop; and 1920×1080 wide desktop. It checks horizontal overflow, canvas visibility/repaint, message clipping, composer/navigation overlap, visible Tab focus, reduced-motion CSS, and a 195×422 CSS viewport as a 200%-zoom-equivalent regression; it saves screenshots at representative sizes. The expanded PWA run `37205925930` passed on repository test head `b56eb95c48903f92542b80d47d82f6e313f3ef4e`. This is local mocked-PWA coverage: it does not load the deployed preview, exercise authenticated APIs or durable records, simulate native browser zoom precisely, or establish physical-device parity. Continue to review exact candidate screenshots and interactions on target devices.

**Still required:** actual preview login and CRUD/reload/persistence checks; real iPhone and iPad review; available Android phone/tablet review; native Windows, macOS, and Linux package install/upgrade checks. An attempt to open the preview domain in the cloud browser returned `net::ERR_BLOCKED_BY_CLIENT`, so no live authenticated browser flow was completed. PWA/browser operation can span those platforms, but it does not establish that every native package works. Signing/notarization and store distribution are separate release activities.

## Performance evidence

Railway infrastructure metrics are not model latency. On 2026-10-04 the stable service had 1 HTTP latency bucket in the prior 24 hours: p50 7 ms, p90 17 ms, p95/p99 67 ms. CPU averaged approximately 0.0015 vCPU and memory approximately 0.191 GB over 1,441 samples. The UI preview showed 17 buckets: worst bucket p50 12 ms, p90 73 ms, p95 101 ms, p99 3,663 ms; CPU averaged approximately 0.0069 vCPU and memory approximately 0.124 GB over 1,441 samples. Traffic includes polling and qualification activity; these figures do not measure a user’s full AI response.

No qualified sample set was available for cold startup, model-backed text turns, microphone capture/transcription, voice generation/playback, or tool operations. Before claiming production performance, record p50/p95, sample count, region, service commit, device/OS/hardware, model/provider, network, and whether measurements include queueing and streaming. Run provider-backed and physical-audio tests as deliberate qualification runs with an explicit cost budget.

## PR and security work still open

- The preview UI PR chain is stacked through #15–#19; #19 remains a draft at the deployed candidate SHA. Reconcile the chain to one clear path after device review. Compare older overlapping open UI PRs before closing any as superseded.
- PR #2 is a broad draft security change and explicitly says a qualification stage is incomplete. Review its exact head against current `main`; split it into independently reviewable owner-scope, recovery, and supply-chain changes. Green CI is necessary, not a production security sign-off.
- PR #9 adds installation identity and automation gating but its operational notes include both Railway and Render while current deployments are two Railway projects. Verify its identity boundary against the actual one-owner Railway topology before merging.
- Keep Windows/macOS signing credentials, Apple notarization, store signing, and release keys out of ordinary PR tests; exercise signed distribution only when native releases are planned.

## Release decision

Do not promote the UI candidate to stable production yet. First verify the stable account’s backup state and complete an off-project encrypted backup plus isolated restore drill. Then perform authenticated tests against the deployed preview API/database, review the exact candidate on target devices, and reconcile the UI PR stack. A production promotion must name the exact candidate SHA, preserve rollback to the stable deployment, and verify records after deployment.
