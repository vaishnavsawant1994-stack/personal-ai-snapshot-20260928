from __future__ import annotations

from evidence import (
    Claim,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    VerificationState,
)
from future_intelligence.work_orchestration.memory_promotion import (
    WorkMemoryPromotionBridge,
    assess_usefulness,
)


class _Events:
    def __init__(self):
        self.handlers = {}

    def subscribe(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)
        return lambda: None


class _Memory:
    def __init__(self):
        self.calls = []

    def remember(self, candidate, **kwargs):
        self.calls.append((candidate, dict(kwargs)))
        return f"candidate-{len(self.calls)}"


class _EvidenceStore:
    def __init__(self, evidence, claims=()):
        self.evidence = list(evidence)
        self.claims = list(claims)

    def list_evidence(self, *, work_order_id=None, **_kwargs):
        return [item for item in self.evidence if item.work_order_id == work_order_id]

    def list_claims(self, *, work_order_id=None, state=None, **_kwargs):
        return [
            item for item in self.claims
            if item.work_order_id == work_order_id and (state is None or item.state is state)
        ]

    def evidence_for_claim(self, claim_id):
        return self.evidence if any(item.id == claim_id for item in self.claims) else []


class _Bridge:
    def __init__(self, store):
        self.evidence = store


class _Autonomy:
    def __init__(self, store, *, passed=True, review_state="passed"):
        self._work_bridge = _Bridge(store)
        self.passed = passed
        self.review_state = review_state

    def work_order_completion(self, plan_id, task_id, *, owner_id):
        assert owner_id == "owner"
        return {
            "passed": self.passed,
            "state": "complete" if self.passed else "verifying",
            "review_state": self.review_state,
            "score": 100.0 if self.passed else 50.0,
        }

    def work_plan(self, plan_id, *, owner_id):
        assert owner_id == "owner"
        return {
            "id": "work-plan-1",
            "goal_id": "goal-1",
            "project_id": "project-1",
            "version": 3,
            "work_orders": [
                {
                    "id": "wo-1",
                    "project_id": "project-1",
                    "title": "Confirm API convention",
                    "worker_type": "research",
                    "resource_scope": {"metadata": {"p10_task_id": "task-1"}},
                }
            ],
        }


def _evidence(observation="The Project API uses /api/v2 for production requests.", *, classification="internal", verified=True):
    return Evidence(
        id="ev-1",
        project_id="project-1",
        goal_id="goal-1",
        plan_id="work-plan-1",
        work_order_id="wo-1",
        source_type="tool",
        source="repository",
        subject="Project API convention",
        observation=observation,
        provenance=EvidenceProvenance.TOOL_VERIFIED,
        verification_state=VerificationState.VERIFIED if verified else VerificationState.UNVERIFIED,
        confidence=0.95,
        data_classification=classification,
    )


def _claim(text="The Project API uses /api/v2 for production requests."):
    return Claim(
        id="claim-1",
        project_id="project-1",
        work_order_id="wo-1",
        text=text,
        state=ClaimState.VERIFIED,
        confidence=0.96,
    )


def test_verified_completed_work_creates_governed_review_candidate_with_provenance():
    store = _EvidenceStore([_evidence()], [_claim()])
    memory = _Memory()
    bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store), memory)

    result = bridge.consider({"plan_id": "plan-1", "task_id": "task-1"})

    assert result == ["candidate-1"]
    assert len(memory.calls) == 1
    candidate, kwargs = memory.calls[0]
    assert candidate.source == "verified-work"
    assert candidate.verified is True
    assert candidate.content == "The Project API uses /api/v2 for production requests."
    assert candidate.evidence == ["ev-1"]
    assert candidate.metadata["project_id"] == "project-1"
    assert candidate.metadata["goal_id"] == "goal-1"
    assert candidate.metadata["plan_id"] == "plan-1"
    assert candidate.metadata["plan_version"] == 3
    assert candidate.metadata["work_order_id"] == "wo-1"
    assert candidate.metadata["claim_ids"] == ["claim-1"]
    assert candidate.metadata["verification_state"] == "verified"
    assert candidate.metadata["promotion_mode"] == "governed_candidate_only"
    assert kwargs["owner_id"] == "owner"
    assert kwargs["force_review"] is True
    assert kwargs["request_id"].startswith("work-memory:plan-1:3:wo-1:verified_claim:claim-1")


def test_completion_judge_failure_blocks_memory_candidate():
    store = _EvidenceStore([_evidence()], [_claim()])
    memory = _Memory()
    bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store, passed=False), memory)
    assert bridge.consider({"plan_id": "plan-1", "task_id": "task-1"}) == []
    assert memory.calls == []


def test_unverified_or_sensitive_evidence_cannot_seed_memory():
    for evidence in (
        _evidence(verified=False),
        _evidence(classification="sensitive"),
        _evidence("The API key secret token is abc123 and must be retained."),
    ):
        memory = _Memory()
        store = _EvidenceStore([evidence], [_claim()])
        bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store), memory)
        assert bridge.consider({"plan_id": "plan-1", "task_id": "task-1"}) == []
        assert memory.calls == []


def test_transient_execution_history_is_not_promoted():
    observation = "npm install finished successfully for this execution."
    store = _EvidenceStore([_evidence(observation)], [])
    memory = _Memory()
    bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store), memory)
    assert bridge.consider({"plan_id": "plan-1", "task_id": "task-1"}) == []
    assert memory.calls == []
    assert assess_usefulness(observation).useful is False


def test_review_rejection_blocks_promotion_and_bridge_has_no_memory_approval_authority():
    store = _EvidenceStore([_evidence()], [_claim()])
    memory = _Memory()
    bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store, review_state="rejected"), memory)
    assert bridge.consider({"plan_id": "plan-1", "task_id": "task-1"}) == []
    assert memory.calls == []
    for forbidden in ("approve", "approve_candidate", "commit", "remember_directly"):
        assert not hasattr(bridge, forbidden)


def test_evidence_only_stable_fact_can_be_proposed_when_no_claim_exists():
    store = _EvidenceStore([_evidence()], [])
    memory = _Memory()
    bridge = WorkMemoryPromotionBridge(_Events(), _Autonomy(store), memory)
    assert bridge.consider({"plan_id": "plan-1", "task_id": "task-1"}) == ["candidate-1"]
    candidate, _ = memory.calls[0]
    assert candidate.metadata["source_type"] == "verified_evidence"
    assert candidate.metadata["claim_ids"] == []
