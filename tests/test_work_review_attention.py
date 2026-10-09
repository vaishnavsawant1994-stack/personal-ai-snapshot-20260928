import threading
from types import SimpleNamespace

from evidence import Claim, ClaimState, Evidence, EvidenceProvenance, EvidenceStore, VerificationState
from future_intelligence.work_orchestration.recovery_attention import RecoveryAwareWorkAttentionService
from future_intelligence.work_orchestration.review_attention import ReviewAwareWorkAttentionService


def _base_snapshot():
    return {
        "authority": "read_only_projection",
        "decision_authorities": {
            "approval": "approval_manager",
            "execution": "existing_p10_p6_runtime",
            "recovery": "recovery_authority",
        },
        "counts": {"total": 0, "approval": 0, "recovery": 0, "review": 0, "blocked": 0, "urgent": 0},
        "items": [],
    }


def _bridge_with_rejected_claim_and_evidence():
    store = EvidenceStore()
    store.create_claim(
        Claim(
            id="claim-1",
            project_id="project-1",
            work_order_id="wo-1",
            text="Deployment succeeded",
            state=ClaimState.REJECTED,
            confidence=0.2,
        )
    )
    store.record_evidence(
        Evidence(
            id="evidence-1",
            project_id="project-1",
            goal_id="goal-1",
            plan_id="plan-1",
            work_order_id="wo-1",
            source_type="deployment_provider",
            source="provider",
            subject="Authorization: Bearer secret-token-123 deployment",
            observation="Provider did not verify the deployment",
            provenance=EvidenceProvenance.TOOL_VERIFIED,
            verification_state=VerificationState.REJECTED,
            verification_reason="Remote state mismatch",
            confidence=0.1,
        )
    )
    return SimpleNamespace(
        lock=threading.RLock(),
        evidence=store,
        connection=store.connection,
    )


def test_review_attention_surfaces_rejected_claim_and_evidence(monkeypatch):
    monkeypatch.setattr(
        RecoveryAwareWorkAttentionService,
        "summary",
        lambda self, **_kwargs: _base_snapshot(),
    )
    service = ReviewAwareWorkAttentionService.__new__(ReviewAwareWorkAttentionService)
    bridge = _bridge_with_rejected_claim_and_evidence()
    service._bridge = lambda: bridge
    service._work_map = lambda: {
        "wo-1": {
            "work_order_id": "wo-1",
            "project_id": "project-1",
            "project_name": "Launch",
            "goal_id": "goal-1",
            "plan_id": "plan-1",
            "plan_version": 2,
            "title": "Authorization: Bearer token-123 Verify deployment",
            "worker_type": "reviewer",
            "status": "COMPLETED",
        }
    }
    service._plan_review_items = lambda _bridge: []

    result = service.summary(limit=100)
    assert result["counts"]["total"] == 2
    assert result["counts"]["review"] == 2
    kinds = [item["kind"] for item in result["items"]]
    assert kinds == ["verification_failed", "claim_unsupported"]

    evidence_item = result["items"][0]
    assert evidence_item["evidence_id"] == "evidence-1"
    assert "token-123" not in evidence_item["summary"]
    assert "[redacted" in evidence_item["summary"]

    claim_item = result["items"][1]
    assert claim_item["claim_id"] == "claim-1"
    assert claim_item["status"] == "rejected"
    assert claim_item["authority"] == "claim_gate"
    assert claim_item["work_order_id"] == "wo-1"

    assert result["decision_authorities"]["evidence"] == "evidence_store"
    assert result["decision_authorities"]["claims"] == "claim_gate"
    assert result["decision_authorities"]["review"] == "deterministic_reviewer"


def test_terminal_work_with_unverified_claim_stays_attention(monkeypatch):
    monkeypatch.setattr(
        RecoveryAwareWorkAttentionService,
        "summary",
        lambda self, **_kwargs: _base_snapshot(),
    )
    store = EvidenceStore()
    store.create_claim(
        Claim(
            id="claim-pending",
            project_id="project-1",
            work_order_id="wo-1",
            text="Work order completed",
            state=ClaimState.SUPPORTED,
            confidence=0.7,
        )
    )
    bridge = SimpleNamespace(lock=threading.RLock(), evidence=store, connection=store.connection)
    service = ReviewAwareWorkAttentionService.__new__(ReviewAwareWorkAttentionService)
    service._bridge = lambda: bridge
    service._work_map = lambda: {
        "wo-1": {
            "work_order_id": "wo-1",
            "project_id": "project-1",
            "project_name": "Launch",
            "plan_id": "plan-1",
            "title": "Deploy",
            "status": "COMPLETED",
        }
    }
    service._plan_review_items = lambda _bridge: []

    item = service.summary(limit=10)["items"][0]
    assert item["kind"] == "claim_unsupported"
    assert item["status"] == "supported"
    assert "not verified" in item["reason"].lower()
