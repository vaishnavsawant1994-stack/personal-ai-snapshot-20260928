# Release readiness and operating model

Review date: 2026-10-04  
Decision: qualify a single-owner hosted release before promoting the preview UI to production.

## Source of truth and deployment identity

This repository is the operational source of truth for new code and current Railway deployments. The historical source repository named by the import commits remains unresolved; this operational designation does not claim that the original Git history is complete.

| Environment | Railway project / service | Branch and deployed commit | Region / storage | Domain |
|---|---|---|---|---|
| Stable | `personal-ai-runtime` / `personal-ai-runtime` | `main` · `2e74e8a45cd9543b7578bb879df39a90d407737e` | iad, one replica, 500 MB volume mounted at `/data` | [personal-ai-runtime-production.up.railway.app](https://personal-ai-runtime-production.up.railway.app) |
| UI preview | `personal-ai-secondary-preview` / `personal-ai-mobile-preview` | `ui/approved-pages-implementation-20261003` · `0ea5ccd2bc0ce5f4434c78c38c59a84e354103fe` | iad, one replica, separate 500 MB volume mounted at `/data` | [personal-ai-mobile-preview-production.up.railway.app](https://personal-ai-mobile-preview-production.up.railway.app) |

The stable deployment was reported SUCCESS by Railway on 2026-09-29. Its deployed commit is behind current `main`, which currently contains one later documentation-only commit. The preview deployment `042aef30-8b37-43ad-b5f4-991d9a5933d1` was SUCCESS on 2026-10-04 at the exact UI candidate above. Neither domain is a custom domain.

## Product scope and architecture

The current operating decision is **single owner**. The repository combines a Python desktop application (PyQt6), local FastAPI control surface, mobile-oriented web/PWA UI, companion application areas, and packaging workflows. The hosted Railway service is a single application process backed by SQLite on a persistent `/data` volume. Model routing supports local OpenAI-compatible and OpenRouter-style providers; tools use risk levels and explicit autonomy modes. The product includes conversation and memory records, tasks, knowledge ingestion/search, workflow execution, device scopes, audit/recovery, and voice interfaces.

This deployment is not evidence of a multi-tenant service. Do not add public sign-up or claim user-to-user isolation without implementing separate tenant identity, authorization, storage isolation, migration, and abuse controls. SQLite remains a reasonable fit for one owner and a single active service replica; it is not the immediate scaling bottleneck shown by current telemetry.

## Branch protection and CI

An active GitHub repository ruleset, **Protect main — pull request and core checks**, now applies to the default branch. It requires pull requests, up-to-date branches, and the GitHub Actions checks `CI / test` and `Reliability and Security / security`; it blocks deletion and force-pushes and has no bypass actors. Required reviews are zero because this is currently a single-owner repository; adding reviewers is appropriate if ownership expands.

The two checks provide a small global merge gate. Path-filtered browser/PWA checks, P3 visual checks, Android/iOS, physical hardware, provider-backed tests, soak runs, and signing workflows remain specialized gates. Do not require a path-filtered workflow globally unless an always-running summary check guarantees a status for every PR. The static PWA Playwright workflow intercepts `/iphone/api/...` and returns fixtures; it verifies frontend behavior, not production authentication, API integration, or durable records.

## Data durability and recovery

Railway confirms that volume backups cover SQLite files and offers daily (6-day retention), weekly (27-day), and monthly (89-day) schedules. Railway’s current documentation also says backups restore only into the same project/environment, wiping a volume deletes backups, and manual backups are limited to half the volume capacity. These snapshots are useful but are not an off-platform recovery copy.

**Observed:** the preview service’s Backups page showed no backups and stated that creating backups or enabling PITR is available only on Pro. The preview workspace was on a trial/free allowance. The connected Railway API does not expose backup inventory or schedule controls. The stable service is in a separate Railway account; its backup schedule has not been verified from that account’s service UI. Do not claim that production backups are enabled.

**Required before production data is called safe:**
1. Inspect the stable service’s Backups page under its owning Railway account and enable a suitable schedule if the plan permits.
2. Check actual SQLite file size and free volume headroom before creating a manual snapshot.
3. Create an encrypted application-level export outside the Railway project, with the decryption key held separately from the archive.
4. Perform an isolated restore to a separate volume/service; check SQLite integrity, expected record counts, encryption-key recovery, and app startup before accepting the restored copy.
5. Record backup timestamps, retention, off-project location, key recovery, restore evidence, and recovery-point/recovery-time objectives.

Never test restore by overwriting the live `/data` volume.

## UI and device qualification

The preview candidate already contains the merged reference repair, interaction polish, whole-project surfaces, movable dialogs, and mobile dialog layout/touch-drag work. Test the deployed SHA above; do not start another overlapping popup branch.

The mock-driven browser workflow is useful for rapid visual regressions. It is not an authenticated live-app test. Current automated viewport coverage is not sufficient to claim responsive correctness for every desktop/tablet/phone size or native platform. Expand browser checks to a small phone, standard phone, tablet portrait and landscape, desktop, and wide desktop; test keyboard-only use, 200% zoom, focus return, reduced motion, dialog boundaries, and error/empty/loading states. Capture screenshots at the same exact candidate SHA.

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
