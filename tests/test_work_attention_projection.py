from types import SimpleNamespace

from future_intelligence.work_orchestration.attention import WorkAttentionService


class _Autonomy:
    def plan(self, plan_id, owner_id="owner"):
        assert owner_id == "owner"
        return {
            "id": plan_id,
            "tasks": [
                {"id": "approve", "status": "WAITING_APPROVAL", "operation_id": "exec-1"},
                {"id": "uncertain", "status": "UNCERTAIN", "operation_id": "tx-2"},
                {"id": "blocked", "status": "BLOCKED"},
                {"id": "failed", "status": "FAILED"},
            ],
        }

    def work_plan(self, plan_id, owner_id="owner"):
        return {"id": "wp-1", "goal_id": "goal-1", "version": 3}


class _WorkService:
    def _autonomy(self):
        return _Autonomy()

    def summary(self, **_kwargs):
        return {
            "projects": [
                {"project_id": "project-1", "project_name": "Launch", "plan_id": "plan-1"}
            ],
            "work_orders": [
                {
                    "project_id": "project-1", "project_name": "Launch",
                    "plan_id": "plan-1", "task_id": "approve", "work_order_id": "wo-a",
                    "title": "Publish campaign", "worker_type": "communications",
                    "status": "WAITING_APPROVAL", "updated_at": "2026-10-09T00:00:00Z",
                },
                {
                    "project_id": "project-1", "project_name": "Launch",
                    "plan_id": "plan-1", "task_id": "uncertain", "work_order_id": "wo-u",
                    "title": "Send email", "worker_type": "communications",
                    "status": "UNCERTAIN", "updated_at": "2026-10-09T00:01:00Z",
                },
                {
                    "project_id": "project-1", "project_name": "Launch",
                    "plan_id": "plan-1", "task_id": "blocked", "work_order_id": "wo-b",
                    "title": "Build asset", "worker_type": "coding",
                    "status": "BLOCKED", "updated_at": "2026-10-09T00:02:00Z",
                },
                {
                    "project_id": "project-1", "project_name": "Launch",
                    "plan_id": "plan-1", "task_id": "failed", "work_order_id": "wo-f",
                    "title": "Verify release", "worker_type": "reviewer",
                    "status": "FAILED", "updated_at": "2026-10-09T00:03:00Z",
                },
            ],
        }


class _Approvals:
    def pending(self, **kwargs):
        assert kwargs["owner_id"] == "owner"
        assert kwargs["device_id"] == "device-1"
        assert kwargs["session_id"] == "session-1"
        return [
            {
                "approval_id": "approval-1",
                "execution_id": "exec-1",
                "tool_id": "publish_content",
                "status": "pending",
                "created_at": 1.0,
                "expires_at": 100.0,
                "destination": "example.com",
                "data_classification": "internal",
            }
        ]


def _service():
    return WorkAttentionService(
        {},
        object(),
        work_service=_WorkService(),
        approvals_projection=_Approvals(),
    )


def test_attention_projection_prioritizes_uncertainty_then_bound_approval():
    result = _service().summary(
        device_id="device-1",
        session_id="session-1",
    )

    assert result["authority"] == "read_only_projection"
    assert result["decision_authorities"]["approval"] == "approval_manager"
    assert result["counts"] == {
        "total": 4,
        "approval": 1,
        "recovery": 1,
        "review": 1,
        "blocked": 1,
        "urgent": 2,
    }
    assert [item["kind"] for item in result["items"]] == [
        "uncertain_effect",
        "approval_required",
        "verification_failed",
        "blocked",
    ]

    approval = result["items"][1]
    assert approval["project_id"] == "project-1"
    assert approval["work_order_id"] == "wo-a"
    assert approval["work_order_title"] == "Publish campaign"
    assert approval["worker_type"] == "communications"
    assert approval["goal_id"] == "goal-1"
    assert approval["plan_version"] == 3
    assert approval["authority"] == "approval_manager"
    assert approval["expected_effect"] == "publish_content → example.com"


def test_attention_projection_never_duplicates_mapped_waiting_approval():
    result = _service().summary(device_id="device-1", session_id="session-1")
    ids = [item["work_order_id"] for item in result["items"]]
    assert ids.count("wo-a") == 1


def test_attention_detail_is_stable_and_owner_scoped():
    service = _service()
    result = service.summary(device_id="device-1", session_id="session-1")
    item = result["items"][0]
    again = service.detail(item["id"], device_id="device-1", session_id="session-1")
    assert again == item
