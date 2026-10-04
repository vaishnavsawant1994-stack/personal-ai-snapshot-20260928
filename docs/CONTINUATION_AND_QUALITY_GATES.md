# Vishnu continuation and quality gates

Updated: 2026-10-04

## Source and deployment record

For this workstream, the active source repository is `vaishnavsawant1994-stack/personal-ai-snapshot-20260928`: the inspected Railway services use it as their source. The repository is explicitly a dated snapshot, so this records the current working source without claiming it contains the complete historical canonical lineage.

| Role | Railway service | Source ref at inspection | Domain | Storage |
|---|---|---|---|---|
| Stable hosted runtime | `personal-ai-runtime` in project `personal-ai-runtime` | `main`, deployed commit `2e74e8a45cd9543b7578bb879df39a90d407737e` | [personal-ai-runtime-production.up.railway.app](https://personal-ai-runtime-production.up.railway.app) | Separate 500 MB persistent volume at `/data` |
| Active UI preview | `personal-ai-mobile-preview` in project `personal-ai-secondary-preview` | `ui/approved-pages-implementation-20261003`, deployed commit `8d034d6510fef3e5a253c6aa7ac838dea6fcfd40`, deployment `ce889f82-54c1-4279-9576-07550a4d77d2` | [personal-ai-mobile-preview-production.up.railway.app](https://personal-ai-mobile-preview-production.up.railway.app) | Separate 500 MB persistent volume at `/data` |
| Earlier qualification service | `personal-ai-iphone-qualification` | `ui/compact-neural-header-home-20260930`, deployed commit `36eeb003647dc8f1e72673e6d3bfaf55ebef1155` | [personal-ai-iphone-qualification-production.up.railway.app](https://personal-ai-iphone-qualification-production.up.railway.app) | Separate 500 MB persistent volume at `/data` |

The stable runtime and UI preview are separate installations, each with its own volume. At inspection the stable service was online, and the preview deployment succeeded. No custom domain is connected; these are Railway-managed HTTPS service domains. The documented preview SHA is the deployment inspected before this record-only follow-up commit.

## Operating model

The selected operating model is **single owner**. Owner enrollment, password, passkey, recovery code, and exact-owner Google sign-in match that use. There is no supported public registration or demonstrated tenant isolation. Do not advertise or deploy this snapshot as a multi-user SaaS without a separate identity, tenancy, authorization, and data-isolation project.

## Storage and recovery gate

The deployed services each have persistent `/data` volumes. Repository backup code creates authenticated AES-256-GCM archives and has isolated restore/integrity tests.

This does not yet prove an independent production backup: the application backup directory is under the data root, and the inspected Railway environments expose no separate bucket. A backup kept only on the same volume does not protect against loss of that volume. The current recovery tests qualify code behavior, not a restore from a real hosted backup. Keep production-data-safety status **unverified** until an encrypted copy is stored separately and restored into an isolated target on the hosting platform. Do not test restore over the live owner data directory.

## Responsive coverage

The active preview candidate's Playwright suite exercises portrait phone widths from 320 to 430 px, tablet and desktop widths through 1920 px, a short landscape phone, dialog drag, keyboard focus/submission, and module/navigation interactions. This update adds 1024×768, 1366×768, and 1920×1080, checks reduced-motion behavior, and tests a 640 CSS-pixel zoom-equivalent reflow.

Automated browser checks are not physical-device evidence. iPhone/Android touch, keyboard, voice, and accessibility checks on real devices remain pending. Do not claim full design parity until the real-device review is recorded on the exact promoted SHA.

## Performance evidence observed

Railway metrics for the active preview before this update showed about 117 MB average memory and 217 MB maximum over 24 hours. HTTP telemetry showed about 85.7k requests, 88 4xx responses, and 24 5xx responses. The busiest latency buckets were influenced by polling/test traffic; endpoint metrics included a small number of samples for runtime-state and one 54 ms bucket for `POST /iphone/api/voice/turn`.

The latest prior preview deployment reached the Uvicorn startup-complete and `/health` 200 log at about 27 seconds after deployment creation. This is deploy-to-health time, not isolated Python initialization time. Production main had a single 17 ms `/health` latency bucket and no observed voice-turn samples.

These numbers do not qualify live model generation, physical microphone/speaker voice, or a real tool execution: provider, hardware, and authenticated turn data were not exercised in this measurement. Record those separately before setting performance targets.

## Workflow tiers

| Tier | Workflows | Use |
|---|---|---|
| Required pull-request suite | CI, Reliability and Security, P3 iPhone PWA for relevant paths, PWA mobile visual preview for relevant paths, Android/iOS simulator or emulator, Package Validation | Deterministic source, security, UI, and platform regression checks |
| Scheduled/manual reliability | Reliability and Security schedule/manual run; Long Duration Reliability | Full qualification and longer soak; not a substitute for live production load tests |
| Physical/live specialized gates | Android Real Device, iPhone Physical Device, V7/V9 Production Evidence, iOS TestFlight Distribution | Run only with the named hardware, provider credentials, or signing setup |
| Release gate | Signed Release | Distribution builds and signatures; not an ordinary PR check |

CI owns the single required full `pytest -q` PR run. Reliability and Security retains dependency auditing, focused P7–P10 checks, performance assertions, isolated backup/restore tests, and short soak checks on PRs; it runs its duplicate full suite only for scheduled/manual qualification.

## Promotion rule

Keep the stable runtime on its current commit while the UI candidate runs its full checks and receives real-device review. A green CI run or a successful preview deployment alone does not authorize calling the candidate production-ready. Promote only the exact reviewed SHA, then update this record with the resulting deployment, domain, storage, backup/restore evidence, and performance measurements.
