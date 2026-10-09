from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WORK_ORCHESTRATION_BASELINE = "29eb0dde3c55f3dfa402bb673716dafac70582c3"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_ALLOWED_STATUS = {"PASS", "HOLD", "FAIL"}

REQUIRED_GATES = {
    "work_orchestration": "Frozen Work Orchestration qualification (#92-#95)",
    "api_authority_security": "Owner API authority census, isolation, permissions, secrets and adversarial security",
    "persistence_backup_restore": "Production persistence plus backup/loss/restore/integrity qualification",
    "authentication_accounts": "Production OAuth/session/device/revocation/reauthentication/account flows",
    "final_ui_browser": "Final desktop/mobile browser reconciliation against approved UI contracts",
    "physical_iphone": "Real iPhone sign-in/PWA/keyboard/microphone/files/network/push/deep-link/approval acceptance",
    "native_desktop": "Real desktop install/uninstall/upgrade/permissions/credential-vault qualification",
    "signed_artifacts": "Windows signing and macOS Developer ID/notarization verification",
    "signed_release_manifest": "Schema-v2 Ed25519 manifest bound to artifact hash/platform/architecture/channel/source SHA",
    "updater": "Current-to-next, interruption/corruption/offline/permission/architecture/signature/health update qualification",
    "rollback": "Automatic/manual rollback preserving owner data and compatible state",
    "cloud_topology": "Frozen production services/storage/TLS/secrets/OAuth/CAPTCHA/backup/health/rollback topology",
    "domain_networking": "Production DNS/HTTPS/redirect/CORS/CSP/API/PWA/OAuth callback qualification",
    "observability": "Health/readiness/logging/audit/version/storage/provider/workflow degraded-state operations",
    "provider_failover": "Configured model-provider timeout/quota/credential/outage/disable/fallback qualification",
    "voice_e2e": "Microphone/transcription/reasoning/streaming/playback/interruption/network/headset/denial qualification",
    "connector_e2e": "Production connector read/write/denial/expiry/reauth/destination/revocation/recovery qualification",
    "production_soak": "Long production-like conversations/Memory/Projects/Work/approvals/restarts/failures/storage soak",
    "full_repository_rc": "Full CI/P3/Work gates/security/native/browser/backup/update/rollback qualification on one exact RC",
    "owner_acceptance": "Recorded owner pass/fail acceptance across the final product surface",
    "production_deployment": "Pinned RC deployed and verified from a clean device with persistent-state restart check",
    "post_deploy_rollback": "Prior production artifact and rollback path verified available after deploy",
}


def _gate_result(name: str, value: object, *, rc_sha: str) -> dict:
    if not isinstance(value, dict):
        return {"status": "HOLD", "reason": "missing structured gate evidence", "evidence": []}
    status = str(value.get("status", "HOLD")).upper()
    if status not in _ALLOWED_STATUS:
        return {"status": "FAIL", "reason": f"invalid status {status!r}", "evidence": []}
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence = [str(item).strip() for item in evidence if str(item).strip()]
    qualified_sha = str(value.get("qualified_sha", "")).lower()
    expected_sha = WORK_ORCHESTRATION_BASELINE if name == "work_orchestration" else rc_sha

    reason = str(value.get("reason", "")).strip()
    if status == "PASS":
        if qualified_sha != expected_sha:
            status = "FAIL"
            reason = f"PASS evidence is not tied to expected SHA {expected_sha}"
        elif not evidence:
            status = "FAIL"
            reason = "PASS requires at least one durable evidence reference"
    return {
        "status": status,
        "qualified_sha": qualified_sha or None,
        "reason": reason or None,
        "evidence": evidence,
    }


def evaluate(evidence: dict, *, expected_rc_sha: str | None = None) -> dict:
    if not isinstance(evidence, dict) or evidence.get("schema") != 1:
        return {"production_ready": False, "status": "FAIL", "errors": ["product release evidence schema 1 is required"]}

    baseline = str(evidence.get("work_orchestration_baseline", "")).lower()
    rc_sha = str(evidence.get("rc_sha", "")).lower()
    errors: list[str] = []
    if baseline != WORK_ORCHESTRATION_BASELINE:
        errors.append("work orchestration baseline does not match the frozen qualified SHA")
    if not _SHA_RE.fullmatch(rc_sha):
        errors.append("rc_sha must be one exact 40-character Git SHA")
    if expected_rc_sha is not None and rc_sha != expected_rc_sha.lower():
        errors.append("rc_sha does not match the expected release-candidate SHA")

    raw_gates = evidence.get("gates")
    if not isinstance(raw_gates, dict):
        raw_gates = {}
    gates = {
        name: _gate_result(name, raw_gates.get(name), rc_sha=rc_sha)
        for name in REQUIRED_GATES
    }
    missing = [name for name, result in gates.items() if result["status"] == "HOLD"]
    failed = [name for name, result in gates.items() if result["status"] == "FAIL"]
    production_ready = not errors and not missing and not failed
    status = "PASS" if production_ready else ("FAIL" if errors or failed else "HOLD")
    return {
        "production_ready": production_ready,
        "status": status,
        "work_orchestration_baseline": WORK_ORCHESTRATION_BASELINE,
        "rc_sha": rc_sha or None,
        "errors": errors,
        "missing": missing,
        "failed": failed,
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence")
    parser.add_argument("--expected-rc-sha")
    parser.add_argument("--json-output")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    result = evaluate(evidence, expected_rc_sha=args.expected_rc_sha)
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json_output:
        Path(args.json_output).write_text(text + "\n", encoding="utf-8")
    return 0 if (not args.strict or result["production_ready"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
