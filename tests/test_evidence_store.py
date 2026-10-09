import sqlite3

import pytest

from evidence.models import (
    Claim,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    Receipt,
    VerificationState,
)
from evidence.store import EvidenceStore


def _evidence(evidence_id="e1"):
    return Evidence(
        id=evidence_id,
        project_id="project-1",
        work_order_id="wo-1",
        source_type="tool_result",
        source="github",
        subject="commit",
        observation="Commit exists remotely",
        provenance=EvidenceProvenance.TOOL_VERIFIED,
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )


def test_evidence_receipt_claim_and_links_round_trip():
    store = EvidenceStore()
    evidence = store.record_evidence(_evidence())
    receipt = store.record_receipt(
        Receipt(
            id="r1",
            operation="github.commit",
            execution_id="exec-1",
            tool="github",
            destination="org/repo",
            request_hash="abc123",
            remote_id="deadbeef",
            verified=True,
        )
    )
    claim = store.create_claim(
        Claim(
            id="c1",
            project_id="project-1",
            work_order_id="wo-1",
            text="Commit exists remotely",
        )
    )
    store.link_evidence(claim.id, evidence.id)

    assert store.get_evidence("e1") == evidence
    assert store.get_receipt("r1") == receipt
    assert store.get_claim("c1") == claim
    assert store.evidence_for_claim("c1") == [evidence]
    assert store.list_evidence(project_id="project-1") == [evidence]


def test_evidence_is_insert_only_by_id():
    store = EvidenceStore()
    store.record_evidence(_evidence())
    with pytest.raises(sqlite3.IntegrityError):
        store.record_evidence(_evidence())


def test_claim_state_update_is_controlled():
    store = EvidenceStore()
    store.create_claim(Claim(id="c1", text="Deployment is live"))
    updated = store.update_claim_state("c1", ClaimState.SUPPORTED, confidence=0.8)
    assert updated.state is ClaimState.SUPPORTED
    assert updated.confidence == 0.8
    assert store.get_claim("c1") == updated
