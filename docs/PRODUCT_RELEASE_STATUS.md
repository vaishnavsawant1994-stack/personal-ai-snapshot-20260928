# Vishnu whole-product release status

This document tracks the release program that starts after the qualified Work Orchestration freeze.

## Qualified foundation

- Work Orchestration: **PASS / FROZEN** at `29eb0dde3c55f3dfa402bb673716dafac70582c3`.
- Work Orchestration qualification does **not** imply whole-product production readiness.
- Stale pre-orchestration stacked PRs were closed rather than merged onto the qualified mainline. Still-valid requirements must be rebuilt or revalidated on current `main`.

## Whole-product gate policy

`readiness/product_release.py` is the canonical release decision gate. The final release candidate is one exact Git SHA. Every required product gate must be PASS with durable evidence tied to that RC SHA, except the frozen Work Orchestration gate, which remains tied to its separately qualified baseline.

A missing physical device, production credential, signing identity, deployment, DNS configuration, owner acceptance record or post-deploy rollback proof is a **HOLD**, never an assumed PASS.

## Current release-program census

| Area | Current status | Repository capability / next evidence |
| --- | --- | --- |
| Work Orchestration | PASS / frozen | Qualified through PR #95 at `29eb0dde…` |
| Stale PR cleanup | PASS for old stack cleanup | Old pre-orchestration stacked PRs closed; current-main UI work is requalified separately |
| Final Chat / Chat Details UI | IN QUALIFICATION | Current-main PR #61 must pass full Chromium, P3, responsive, CI, security and package gates on one exact head before merge |
| API authority / security | HOLD | Existing security foundations and Reliability & Security CI must be extended/censused at whole-product owner API boundary |
| Persistence / backup / restore | HOLD | `recovery/backup.py` provides integrity-aware backup primitives; production dataset-loss/restore/integrity evidence still required |
| Authentication / accounts | HOLD | Production OAuth/session/device/revocation/reauth flows require hosted qualification with real credentials |
| Physical iPhone | HOLD | `ios-physical-device.yml` is fail-closed scaffolding; real-device final-RC evidence required |
| Native desktop | HOLD | Packaging exists; final real install/upgrade/uninstall and credential-vault evidence required |
| Signing / notarization | HOLD | Release workflow requires Windows Authenticode and Apple Developer ID/notarization credentials; final downloaded-artifact evidence required |
| Signed manifest | IMPLEMENTED / awaiting PR qualification | Schema v2 binds source SHA, channel, platform, architecture, package type, size and SHA-256 under Ed25519 |
| Updater | IMPLEMENTED / awaiting PR qualification | Identity matching, downgrade rejection, safe ZIP staging, transactional installation and health-check rollback covered by regression tests |
| Rollback | IMPLEMENTED / awaiting PR qualification | Failed post-update health restores prior install; final native/package rollback evidence still required |
| Cloud topology | HOLD | Final Railway production service/storage/domain/secrets/backups/health/rollback topology must be frozen and evidenced |
| Domain / networking | HOLD | DNS/TLS/CORS/CSP/OAuth callbacks/PWA endpoints require final domain evidence |
| Observability | HOLD | Existing health/readiness/audit surfaces require final production operations census |
| Provider failover | HOLD | Final configured provider timeout/quota/credential/outage/fallback qualification required |
| Voice E2E | HOLD | Simulator/browser coverage is insufficient; real microphone/network/headset/permission final-RC evidence required |
| Connector E2E | HOLD | Production connector credentials, expiry/revocation/destination/recovery evidence required |
| Production-like soak | HOLD | Existing long-duration workflows must run against the pinned final RC with release-representative infrastructure |
| Final RC | HOLD | Cut only after product code freeze; rerun all permanent gates on the exact SHA |
| Owner acceptance | HOLD | Manual production-like product-surface checklist must be recorded pass/fail |
| Production deployment | HOLD | Back up, deploy pinned RC, verify exact version/SHA, clean-device auth, harmless verified WorkOrder, restart persistence |
| Post-deploy rollback | HOLD | Prior production artifact and tested rollback instructions must be available and verified |

## Production-ready declaration

Vishnu may be declared production-ready only when `python -m readiness.product_release <evidence.json> --expected-rc-sha <sha> --strict` returns success for the pinned final RC and the evidence includes real external acceptance where required.
