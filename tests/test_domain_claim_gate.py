from __future__ import annotations

from evidence import (
    Claim,
    ClaimState,
    DomainClaimGate,
    DomainClaimType,
    Evidence,
    EvidenceProvenance,
    Receipt,
    VerificationState,
)


def ev(eid: str, source_type: str, *, ref: str | None = None, hash_: str | None = None, state=VerificationState.VERIFIED, provenance=EvidenceProvenance.TOOL_VERIFIED):
    return Evidence(
        id=eid,
        source_type=source_type,
        source="verifier",
        subject="proof",
        observation="verified proof",
        artifact_ref=ref,
        artifact_hash=hash_,
        provenance=provenance,
        verification_state=state,
        confidence=1.0,
    )


def receipt(rid: str, *, destination="target", remote_id="remote-1", verified=True, **details):
    return Receipt(
        id=rid,
        operation="test",
        execution_id="exec-1",
        tool="tool",
        destination=destination,
        request_hash="hash",
        remote_id=remote_id,
        details=details,
        verified=verified,
    )


def claim():
    return Claim(id="c1", text="operation completed")


def test_deployment_requires_matching_sha_provider_status_url_and_smoke():
    evidence = [ev("e1", "http_smoke")]
    good = receipt(
        "r1",
        deployment_id="dep-1",
        status="success",
        source_sha="abc",
        deployed_sha="abc",
        deployment_url="https://example.test",
        environment="production",
    )
    decision = DomainClaimGate.evaluate(
        DomainClaimType.DEPLOYMENT_COMPLETED,
        claim(),
        evidence,
        receipts=[good],
        expected={"source_sha": "abc", "environment": "production"},
    )
    assert decision.passed is True
    assert decision.state is ClaimState.VERIFIED
    assert decision.proof["deployment_id"] == "remote-1"

    wrong_sha = receipt(
        "r2",
        deployment_id="dep-2",
        status="success",
        source_sha="abc",
        deployed_sha="different",
        deployment_url="https://example.test",
        environment="production",
    )
    failed = DomainClaimGate.evaluate(
        "deployment_completed",
        claim(),
        evidence,
        receipts=[wrong_sha],
        expected={"source_sha": "abc", "environment": "production"},
    )
    assert failed.passed is False


def test_tool_or_model_success_text_alone_cannot_prove_deployment():
    tool_text = ev("e1", "tool_result")
    decision = DomainClaimGate.evaluate(
        "deployment_completed",
        claim(),
        [tool_text],
        receipts=[receipt("r1", status="success", source_sha="abc", deployed_sha="abc", deployment_url="https://example.test")],
        expected={"source_sha": "abc"},
    )
    assert decision.passed is False

    model_text = ev(
        "e2",
        "model_output",
        provenance=EvidenceProvenance.MODEL_ONLY,
    )
    decision = DomainClaimGate.evaluate(
        "deployment_completed",
        claim(),
        [model_text],
        receipts=[receipt("r2", status="success", source_sha="abc", deployed_sha="abc", deployment_url="https://example.test")],
        expected={"source_sha": "abc"},
    )
    assert decision.passed is False


def test_git_push_requires_remote_ref_to_expected_sha():
    evidence = [ev("e1", "git_remote_ref")]
    good = receipt(
        "r1",
        repository="org/repo",
        branch="main",
        commit_sha="abc",
        remote_sha="abc",
    )
    assert DomainClaimGate.evaluate(
        "git_commit_pushed",
        claim(),
        evidence,
        receipts=[good],
        expected={"repository": "org/repo", "branch": "main", "commit_sha": "abc"},
    ).passed

    bad = receipt(
        "r2",
        repository="org/repo",
        branch="main",
        commit_sha="abc",
        remote_sha="old",
    )
    assert not DomainClaimGate.evaluate(
        "git_commit_pushed",
        claim(),
        evidence,
        receipts=[bad],
        expected={"repository": "org/repo", "branch": "main", "commit_sha": "abc"},
    ).passed


def test_pull_request_merge_requires_remote_merged_state_and_merge_sha():
    evidence = [ev("e1", "github_pr_state")]
    good = receipt(
        "r1",
        repository="org/repo",
        pr_number=42,
        base_branch="main",
        merged=True,
        merge_commit_sha="merge-sha",
    )
    assert DomainClaimGate.evaluate(
        "pull_request_merged",
        claim(),
        evidence,
        receipts=[good],
        expected={"repository": "org/repo", "pr_number": 42, "base_branch": "main"},
    ).passed

    closed_only = receipt(
        "r2",
        repository="org/repo",
        pr_number=42,
        base_branch="main",
        state="closed",
        merge_commit_sha="",
        remote_id=None,
    )
    assert not DomainClaimGate.evaluate(
        "pull_request_merged",
        claim(),
        evidence,
        receipts=[closed_only],
        expected={"repository": "org/repo", "pr_number": 42, "base_branch": "main"},
    ).passed


def test_email_send_requires_verified_provider_receipt_and_destination_binding():
    evidence = [ev("e1", "provider_send_confirmation")]
    good = receipt("r1", destination="person@example.com", message_id="message-1")
    assert DomainClaimGate.evaluate(
        "email_sent",
        claim(),
        evidence,
        receipts=[good],
        expected={"destination": "person@example.com"},
    ).passed

    uncertain = receipt("r2", destination="person@example.com", message_id="message-2", verified=False)
    decision = DomainClaimGate.evaluate(
        "email_sent",
        claim(),
        evidence,
        receipts=[uncertain],
        expected={"destination": "person@example.com"},
    )
    assert decision.passed is False
    assert "no verified execution receipt" in decision.reasons[0]


def test_publish_requires_remote_id_published_state_and_readback():
    evidence = [ev("e1", "publication_readback")]
    good = receipt("r1", destination="site", content_id="post-1", state="published")
    assert DomainClaimGate.evaluate(
        "content_published",
        claim(),
        evidence,
        receipts=[good],
        expected={"destination": "site"},
    ).passed

    not_published = receipt("r2", destination="site", content_id="post-2", state="draft")
    assert not DomainClaimGate.evaluate(
        "content_published",
        claim(),
        evidence,
        receipts=[not_published],
        expected={"destination": "site"},
    ).passed


def test_file_creation_requires_verified_readback_and_expected_hash_when_supplied():
    evidence = [ev("e1", "file_readback", ref="/tmp/output.txt", hash_="sha256:abc")]
    assert DomainClaimGate.evaluate(
        "file_created",
        claim(),
        evidence,
        expected={"path": "/tmp/output.txt", "artifact_hash": "sha256:abc"},
    ).passed

    assert not DomainClaimGate.evaluate(
        "file_created",
        claim(),
        evidence,
        expected={"path": "/tmp/output.txt", "artifact_hash": "sha256:different"},
    ).passed


def test_rejected_or_disputed_evidence_blocks_domain_claim():
    evidence = [ev("e1", "http_smoke", state=VerificationState.REJECTED)]
    decision = DomainClaimGate.evaluate(
        "deployment_completed",
        claim(),
        evidence,
        receipts=[receipt("r1", status="success", source_sha="abc", deployed_sha="abc", deployment_url="https://example.test")],
        expected={"source_sha": "abc"},
    )
    assert decision.passed is False
    assert decision.state is ClaimState.DISPUTED
