from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from .claim_gate import ClaimGate, ClaimRequirement
from .models import Claim, ClaimState, Evidence, EvidenceProvenance, Receipt, VerificationState


class DomainClaimType(StrEnum):
    DEPLOYMENT_COMPLETED = "deployment_completed"
    GIT_COMMIT_PUSHED = "git_commit_pushed"
    PULL_REQUEST_MERGED = "pull_request_merged"
    EMAIL_SENT = "email_sent"
    CONTENT_PUBLISHED = "content_published"
    FILE_CREATED = "file_created"
    EXTERNAL_RECORD_CREATED = "external_record_created"


@dataclass(frozen=True)
class DomainClaimRequirement:
    claim_type: DomainClaimType
    generic: ClaimRequirement
    requires_receipt: bool = True
    required_expected_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainClaimDecision:
    claim_type: DomainClaimType
    passed: bool
    state: ClaimState
    reasons: tuple[str, ...]
    qualifying_evidence_ids: tuple[str, ...] = ()
    qualifying_receipt_ids: tuple[str, ...] = ()
    proof: Mapping[str, Any] | None = None


_DOMAIN_REQUIREMENTS: dict[DomainClaimType, DomainClaimRequirement] = {
    DomainClaimType.DEPLOYMENT_COMPLETED: DomainClaimRequirement(
        DomainClaimType.DEPLOYMENT_COMPLETED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("source_sha",),
    ),
    DomainClaimType.GIT_COMMIT_PUSHED: DomainClaimRequirement(
        DomainClaimType.GIT_COMMIT_PUSHED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("repository", "branch", "commit_sha"),
    ),
    DomainClaimType.PULL_REQUEST_MERGED: DomainClaimRequirement(
        DomainClaimType.PULL_REQUEST_MERGED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("repository", "pr_number", "base_branch"),
    ),
    DomainClaimType.EMAIL_SENT: DomainClaimRequirement(
        DomainClaimType.EMAIL_SENT,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("destination",),
    ),
    DomainClaimType.CONTENT_PUBLISHED: DomainClaimRequirement(
        DomainClaimType.CONTENT_PUBLISHED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("destination",),
    ),
    DomainClaimType.FILE_CREATED: DomainClaimRequirement(
        DomainClaimType.FILE_CREATED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        False,
        ("path",),
    ),
    DomainClaimType.EXTERNAL_RECORD_CREATED: DomainClaimRequirement(
        DomainClaimType.EXTERNAL_RECORD_CREATED,
        ClaimRequirement(minimum_verified_evidence=1, minimum_provenance=EvidenceProvenance.TOOL_VERIFIED),
        True,
        ("destination",),
    ),
}


def requirement_for(claim_type: DomainClaimType | str) -> DomainClaimRequirement:
    return _DOMAIN_REQUIREMENTS[DomainClaimType(str(claim_type))]


def _details(receipt: Receipt) -> dict[str, Any]:
    return dict(receipt.details or {})


def _first(details: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = details.get(key)
        if value not in (None, ""):
            return value
    return None


def _norm(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _lower(value: Any) -> str:
    return _norm(value).lower()


def _verified_receipts(receipts: Iterable[Receipt]) -> list[Receipt]:
    return [item for item in receipts if item.verified]


def _verified_evidence(evidence: Iterable[Evidence]) -> list[Evidence]:
    return [
        item
        for item in evidence
        if item.verification_state is VerificationState.VERIFIED
        and item.provenance.rank >= EvidenceProvenance.TOOL_VERIFIED.rank
    ]


def _evidence_of_type(evidence: Iterable[Evidence], allowed: Sequence[str]) -> list[Evidence]:
    allow = {str(value) for value in allowed}
    return [item for item in _verified_evidence(evidence) if item.source_type in allow]


def _missing_expected(expected: Mapping[str, Any], fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(field for field in fields if expected.get(field) in (None, ""))


def _remote_id(receipt: Receipt, details: Mapping[str, Any], *keys: str) -> str | None:
    value = receipt.remote_id or _first(details, *keys)
    return _norm(value) or None


class DomainClaimGate:
    """Deterministic proof rules for consequential claims.

    This extends the generic ClaimGate. It never executes tools, grants permission,
    consumes approvals, or resolves recovery state.
    """

    @classmethod
    def evaluate(
        cls,
        claim_type: DomainClaimType | str,
        claim: Claim,
        evidence: Iterable[Evidence],
        *,
        receipts: Iterable[Receipt] = (),
        expected: Mapping[str, Any] | None = None,
    ) -> DomainClaimDecision:
        resolved = DomainClaimType(str(claim_type))
        requirement = requirement_for(resolved)
        expected_data = dict(expected or {})
        evidence_items = list(evidence)
        receipt_items = list(receipts)

        if claim.state is ClaimState.REJECTED:
            return DomainClaimDecision(resolved, False, ClaimState.REJECTED, ("claim is rejected",))
        if claim.state is ClaimState.DISPUTED:
            return DomainClaimDecision(resolved, False, ClaimState.DISPUTED, ("claim is disputed",))

        conflicting = [
            item.id
            for item in evidence_items
            if item.verification_state in {VerificationState.REJECTED, VerificationState.DISPUTED}
        ]
        if conflicting:
            return DomainClaimDecision(
                resolved,
                False,
                ClaimState.DISPUTED,
                ("linked evidence is rejected or disputed",),
                tuple(conflicting),
            )

        missing = _missing_expected(expected_data, requirement.required_expected_fields)
        if missing:
            return DomainClaimDecision(
                resolved,
                False,
                ClaimState.PROPOSED,
                ("missing expected proof context: " + ", ".join(missing),),
            )

        generic = ClaimGate.evaluate(claim, evidence_items, requirement.generic)
        if not generic.passed:
            return DomainClaimDecision(
                resolved,
                False,
                generic.state,
                generic.reasons,
                generic.qualifying_evidence_ids,
            )

        verified_receipts = _verified_receipts(receipt_items)
        if requirement.requires_receipt and not verified_receipts:
            return DomainClaimDecision(
                resolved,
                False,
                ClaimState.SUPPORTED,
                ("no verified execution receipt is available",),
                generic.qualifying_evidence_ids,
            )

        validator = {
            DomainClaimType.DEPLOYMENT_COMPLETED: cls._deployment,
            DomainClaimType.GIT_COMMIT_PUSHED: cls._git_push,
            DomainClaimType.PULL_REQUEST_MERGED: cls._pr_merge,
            DomainClaimType.EMAIL_SENT: cls._email,
            DomainClaimType.CONTENT_PUBLISHED: cls._publish,
            DomainClaimType.FILE_CREATED: cls._file,
            DomainClaimType.EXTERNAL_RECORD_CREATED: cls._external_record,
        }[resolved]
        passed, reasons, evidence_ids, receipt_ids, proof = validator(
            evidence_items, verified_receipts, expected_data
        )
        return DomainClaimDecision(
            resolved,
            passed,
            ClaimState.VERIFIED if passed else ClaimState.SUPPORTED,
            tuple(reasons),
            tuple(evidence_ids),
            tuple(receipt_ids),
            proof,
        )

    @staticmethod
    def _deployment(evidence, receipts, expected):
        smoke = _evidence_of_type(evidence, ("deployment_smoke", "http_smoke", "deployment_health", "health_check"))
        if not smoke:
            return False, ["deployment lacks verified smoke/health evidence"], [], [], {}
        expected_sha = _norm(expected["source_sha"])
        expected_environment = expected.get("environment")
        for receipt in receipts:
            details = _details(receipt)
            deployment_id = _remote_id(receipt, details, "deployment_id", "provider_id", "release_id")
            status = _lower(_first(details, "status", "state", "result"))
            source_sha = _norm(_first(details, "source_sha", "commit_sha", "expected_sha"))
            deployed_sha = _norm(_first(details, "deployed_sha", "release_sha", "artifact_sha"))
            url = _first(details, "deployment_url", "url", "target_url")
            environment = _first(details, "environment", "target_environment")
            if not deployment_id or status not in {"success", "succeeded", "ready", "deployed", "healthy"}:
                continue
            if source_sha != expected_sha or deployed_sha != expected_sha:
                continue
            if not url:
                continue
            if expected_environment not in (None, "") and _norm(environment) != _norm(expected_environment):
                continue
            return True, ["deployment provider receipt, source identity, and smoke/health proof verified"], [x.id for x in smoke], [receipt.id], {
                "deployment_id": deployment_id,
                "source_sha": expected_sha,
                "environment": environment,
                "url": url,
            }
        return False, ["no verified deployment receipt matches the expected source/environment"], [x.id for x in smoke], [], {}

    @staticmethod
    def _git_push(evidence, receipts, expected):
        remote_ref = _evidence_of_type(evidence, ("git_remote_ref", "remote_ref", "github_remote_ref"))
        if not remote_ref:
            return False, ["git push lacks verified remote-ref evidence"], [], [], {}
        expected_repo = _norm(expected["repository"])
        expected_branch = _norm(expected["branch"])
        expected_sha = _norm(expected["commit_sha"])
        for receipt in receipts:
            details = _details(receipt)
            repository = _norm(_first(details, "repository", "repo"))
            branch = _norm(_first(details, "branch", "ref", "target_branch"))
            commit_sha = _norm(_first(details, "commit_sha", "sha", "source_sha"))
            remote_sha = _norm(_first(details, "remote_sha", "remote_ref_sha", "resolved_sha"))
            if repository == expected_repo and branch == expected_branch and commit_sha == expected_sha and remote_sha == expected_sha:
                return True, ["remote ref resolves to the expected commit"], [x.id for x in remote_ref], [receipt.id], {
                    "repository": repository,
                    "branch": branch,
                    "commit_sha": expected_sha,
                }
        return False, ["no verified push receipt proves the expected repository/branch/SHA"], [x.id for x in remote_ref], [], {}

    @staticmethod
    def _pr_merge(evidence, receipts, expected):
        remote_state = _evidence_of_type(evidence, ("pull_request_state", "github_pr_state", "remote_pr_state"))
        if not remote_state:
            return False, ["merge lacks verified remote PR-state evidence"], [], [], {}
        expected_repo = _norm(expected["repository"])
        expected_pr = _norm(expected["pr_number"])
        expected_base = _norm(expected["base_branch"])
        for receipt in receipts:
            details = _details(receipt)
            repository = _norm(_first(details, "repository", "repo"))
            pr_number = _norm(_first(details, "pr_number", "pull_request", "pr"))
            base_branch = _norm(_first(details, "base_branch", "base", "target_branch"))
            merged = bool(details.get("merged")) or _lower(_first(details, "state", "status")) == "merged"
            merge_sha = _remote_id(receipt, details, "merge_commit_sha", "merge_sha")
            if repository == expected_repo and pr_number == expected_pr and base_branch == expected_base and merged and merge_sha:
                return True, ["remote PR state proves the requested merge"], [x.id for x in remote_state], [receipt.id], {
                    "repository": repository,
                    "pr_number": pr_number,
                    "base_branch": base_branch,
                    "merge_commit_sha": merge_sha,
                }
        return False, ["no verified receipt proves the requested PR is merged"], [x.id for x in remote_state], [], {}

    @staticmethod
    def _email(evidence, receipts, expected):
        confirmation = _evidence_of_type(evidence, ("email_send_confirmation", "provider_send_confirmation", "message_send_confirmation"))
        if not confirmation:
            return False, ["email send lacks verified provider confirmation evidence"], [], [], {}
        destination = _norm(expected["destination"])
        for receipt in receipts:
            details = _details(receipt)
            message_id = _remote_id(receipt, details, "message_id", "provider_message_id")
            receipt_destination = _norm(_first(details, "destination", "recipient", "to") or receipt.destination)
            if message_id and receipt_destination == destination:
                return True, ["provider receipt proves message ID and destination binding"], [x.id for x in confirmation], [receipt.id], {
                    "message_id": message_id,
                    "destination": destination,
                }
        return False, ["no verified send receipt matches the expected destination"], [x.id for x in confirmation], [], {}

    @staticmethod
    def _publish(evidence, receipts, expected):
        readback = _evidence_of_type(evidence, ("publication_readback", "remote_readback", "content_readback"))
        if not readback:
            return False, ["publication lacks verified remote read-back evidence"], [], [], {}
        destination = _norm(expected["destination"])
        for receipt in receipts:
            details = _details(receipt)
            content_id = _remote_id(receipt, details, "content_id", "post_id", "publication_id")
            receipt_destination = _norm(_first(details, "destination", "platform", "target") or receipt.destination)
            state = _lower(_first(details, "state", "status"))
            if content_id and receipt_destination == destination and state in {"published", "live", "success", "succeeded"}:
                return True, ["remote publication ID/state and read-back are verified"], [x.id for x in readback], [receipt.id], {
                    "content_id": content_id,
                    "destination": destination,
                    "state": state,
                }
        return False, ["no verified publication receipt matches the requested destination/state"], [x.id for x in readback], [], {}

    @staticmethod
    def _file(evidence, receipts, expected):
        readback = _evidence_of_type(evidence, ("file_readback", "artifact_readback", "file_exists_verified"))
        expected_path = _norm(expected["path"])
        expected_hash = expected.get("artifact_hash")
        for item in readback:
            if _norm(item.artifact_ref) != expected_path:
                continue
            if expected_hash not in (None, "") and _norm(item.artifact_hash) != _norm(expected_hash):
                continue
            if bool(expected.get("require_hash")) and not item.artifact_hash:
                continue
            return True, ["file read-back proves the expected artifact"], [item.id], [], {
                "path": expected_path,
                "artifact_hash": item.artifact_hash,
            }
        return False, ["no verified file read-back matches the expected path/hash"], [x.id for x in readback], [], {}

    @staticmethod
    def _external_record(evidence, receipts, expected):
        readback = _evidence_of_type(evidence, ("external_record_readback", "remote_readback", "record_readback"))
        if not readback:
            return False, ["external record lacks verified remote read-back evidence"], [], [], {}
        destination = _norm(expected["destination"])
        for receipt in receipts:
            details = _details(receipt)
            record_id = _remote_id(receipt, details, "record_id", "external_id")
            receipt_destination = _norm(_first(details, "destination", "system", "target") or receipt.destination)
            if record_id and receipt_destination == destination:
                return True, ["external record ID and remote read-back are verified"], [x.id for x in readback], [receipt.id], {
                    "record_id": record_id,
                    "destination": destination,
                }
        return False, ["no verified record receipt matches the requested destination"], [x.id for x in readback], [], {}
