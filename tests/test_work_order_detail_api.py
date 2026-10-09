from __future__ import annotations

from evidence import Claim, ClaimState, Evidence, EvidenceProvenance, Receipt, VerificationState
from server.work_order_detail_api import WorkOrderDetailService


class _ProjectStore:
    path = "projects.sqlite3"
    def get(self, project_id):
        return {"id": project_id, "name": "Launch", "status": "active"}


class _WorkStore:
    def project_plan_records(self, project_id):
        return [{"source_p10_plan_id": "plan-1"}]


class _EvidenceStore:
    def __init__(self):
        self.ev = Evidence(
            id="ev-1", project_id="project-1", goal_id="goal-1", plan_id="plan-1",
            work_order_id="wo-1", source_type="tool", source="repo", subject="API route",
            observation="The Project API uses /api/v2.", provenance=EvidenceProvenance.TOOL_VERIFIED,
            verification_state=VerificationState.VERIFIED, confidence=.95,
        )
        self.claim = Claim(id="claim-1", project_id="project-1", work_order_id="wo-1", text="The Project API uses /api/v2.", state=ClaimState.VERIFIED, confidence=.96)
    def list_evidence(self, **kwargs): return [self.ev]
    def list_claims(self, **kwargs): return [self.claim]
    def evidence_for_claim(self, claim_id): return [self.ev]
    def list_receipts(self, **kwargs):
        return [Receipt(id="receipt-1", operation="deploy", execution_id="op-1", tool="vercel", destination="project-a", request_hash="abc", remote_id="dep-1", verified=True)]


class _Bridge:
    def __init__(self):
        self.work = _WorkStore()
        self.evidence = _EvidenceStore()


class _Autonomy:
    def __init__(self):
        self._work_bridge = _Bridge()
        self.project_store = None
    def plan(self, plan_id, *, owner_id):
        return {"id": plan_id, "state": "COMPLETED", "tasks": [{"id": "task-1", "status": "COMPLETED", "operation_id": "op-1"}]}
    def work_plan(self, plan_id, *, owner_id):
        return {
            "id": "work-plan-1", "goal_id": "goal-1", "project_id": "project-1", "version": 3,
            "latest_review": {"status": "ready", "score": 100, "authority": "deterministic_reviewer"},
            "milestones": [{"id": "m-1", "title": "Launch proof", "work_order_ids": ["wo-1"]}],
            "work_orders": [{
                "id": "wo-1", "title": "Confirm API", "objective": "Confirm the production API route", "worker_type": "research",
                "status": "completed", "dependencies": [], "allowed_capabilities": ["research", "repository_analysis"],
                "resource_scope": {"repositories": ["project-a"], "metadata": {"p10_task_id": "task-1", "requested_tool": "github"}},
                "expected_output": "Verified API route", "success_criteria": ["Route verified"],
                "evidence_contract": {"requirements": [{"kind": "tool_execution_verification"}]},
                "verification_strategy": {"kind": "repository_check"}, "falsifier": "Repository defines a different production route",
                "retest_strategy": {"kind": "repeat_read"}, "approval_policy": {"requires_reauthentication": False},
                "time_budget_seconds": 120, "cost_budget": 0.5,
            }],
        }
    def work_order_completion(self, plan_id, task_id, *, owner_id):
        return {"work_order_id": "wo-1", "state": "complete", "passed": True, "score": 100.0, "review_state": "ready", "domain_claim_type": "repository_fact"}
    def work_evidence(self, plan_id, task_id, *, owner_id):
        return [{"id": "ev-1", "subject": "API route", "observation": "The Project API uses /api/v2.", "verification_state": "verified", "provenance": "tool_verified", "tool_name": "github"}]
    def work_plan_versions(self, plan_id, *, owner_id): return [{"version": 1}, {"version": 2}, {"version": 3}]
    def work_plan_deltas(self, plan_id, *, owner_id): return [{"from_version": 2, "to_version": 3, "reason": "verified new evidence"}]


def test_work_order_detail_aggregates_existing_authorities_without_mutation():
    store = _ProjectStore(); autonomy = _Autonomy(); runtime = {"advanced_autonomy": autonomy}
    detail = WorkOrderDetailService(runtime, store).detail("project-1", "plan-1", "task-1")

    assert detail["title"] == "Confirm API"
    assert detail["milestone"]["title"] == "Launch proof"
    assert detail["worker"] == "research"
    assert detail["execution_status"] == "COMPLETED"
    assert detail["canonical_status"] == "completed"
    assert detail["requested_tool"] == "github"
    assert detail["required_capabilities"] == ["research", "repository_analysis"]
    assert detail["evidence_count"] == 1
    assert detail["receipts"][0]["verified"] is True
    assert detail["claims"][0]["gate"]["passed"] is True
    assert detail["domain_claim_type"] == "repository_fact"
    assert detail["reviewer_decision"]["authority"] == "deterministic_reviewer"
    assert detail["completion_judge"]["passed"] is True
    assert detail["plan_version"] == 3
    assert len(detail["replan_history"]["versions"]) == 3
    assert detail["safe_next_action"]["type"] == "none"
    assert detail["read_only"] is True
    assert detail["authorities"]["approval"] == "approval_manager"
    assert not hasattr(WorkOrderDetailService, "execute")
    assert not hasattr(WorkOrderDetailService, "approve")
    assert not hasattr(WorkOrderDetailService, "complete")
