from future_intelligence.work_orchestration.living_projection import LivingAgentWorkProjection


def _work(*, task_counts=None, orders=None, active_projects=1):
    return {
        "authority": "read_only_projection",
        "task_counts": task_counts or {},
        "work_orders": orders or [],
        "active_projects": active_projects,
    }


def _attention(*, counts=None, items=None):
    return {
        "authority": "read_only_projection",
        "counts": {
            "total": 0,
            "approval": 0,
            "recovery": 0,
            "review": 0,
            "blocked": 0,
            "urgent": 0,
            **(counts or {}),
        },
        "items": items or [],
    }


def test_uncertain_effect_has_highest_presentation_priority_and_never_celebrates():
    result = LivingAgentWorkProjection.project(
        _work(task_counts={"COMPLETED": 3}, active_projects=0),
        _attention(
            counts={"total": 1, "recovery": 1, "urgent": 1},
            items=[{
                "kind": "uncertain_effect",
                "project_name": "Launch",
                "work_order_title": "Publish campaign",
                "worker_type": "communications",
            }],
        ),
    )
    assert result["authority"] == "presentation_only"
    assert result["state"] == "needs_attention"
    assert result["needs_attention"] is True
    assert result["attention_count"] == 1
    assert result["recovery_count"] == 1
    assert result["current_project_name"] == "Launch"
    assert result["current_work_order_title"] == "Publish campaign"
    assert result["state"] not in {"completed", "celebrating"}


def test_approval_precedes_recovery_review_and_working_animation():
    result = LivingAgentWorkProjection.project(
        _work(
            task_counts={"WAITING_APPROVAL": 1, "RECOVERING": 1, "RUNNING": 2},
            orders=[{
                "project_id": "p1",
                "project_name": "Marketing Launch",
                "title": "Publish campaign",
                "worker_type": "communications",
                "status": "WAITING_APPROVAL",
            }],
        ),
        _attention(counts={"total": 2, "approval": 1, "recovery": 1}),
    )
    assert result["state"] == "waiting_approval"
    assert result["approval_count"] == 1
    assert result["workers_active"] == 1
    assert result["projects_active"] == 1


def test_recovery_precedes_review_and_verification():
    result = LivingAgentWorkProjection.project(
        _work(task_counts={"RECOVERY_REQUIRED": 1, "VERIFYING": 1}),
        _attention(counts={"total": 2, "recovery": 1, "review": 1}),
    )
    assert result["state"] == "recovering"
    assert result["recovery_count"] == 1
    assert result["review_count"] == 1
    assert "not retried blindly" in result["activity"]


def test_review_attention_blocks_completed_projection():
    result = LivingAgentWorkProjection.project(
        _work(task_counts={"COMPLETED": 2}, active_projects=0),
        _attention(
            counts={"total": 1, "review": 1},
            items=[{
                "kind": "claim_unsupported",
                "project_name": "Release",
                "work_order_title": "Verify deployment",
                "worker_type": "reviewer",
            }],
        ),
    )
    assert result["state"] == "reviewing"
    assert result["needs_attention"] is True
    assert result["state"] != "completed"


def test_running_worker_projects_specific_presentation_state():
    for worker, expected in (("coding", "coding"), ("browser", "browsing"), ("research", "researching"), ("data", "working")):
        result = LivingAgentWorkProjection.project(
            _work(
                task_counts={"RUNNING": 1},
                orders=[{
                    "project_id": "p1",
                    "project_name": "Build",
                    "title": "Current task",
                    "worker_type": worker,
                    "status": "RUNNING",
                }],
            ),
            _attention(),
        )
        assert result["state"] == expected
        assert result["needs_attention"] is False
        assert result["workers_active"] == 1


def test_verified_terminal_work_can_project_completed_only_without_attention():
    result = LivingAgentWorkProjection.project(
        _work(
            task_counts={"COMPLETED": 2},
            orders=[
                {"project_id": "p1", "project_name": "Done", "title": "A", "worker_type": "coding", "status": "COMPLETED"},
                {"project_id": "p1", "project_name": "Done", "title": "B", "worker_type": "reviewer", "status": "COMPLETED"},
            ],
            active_projects=0,
        ),
        _attention(),
    )
    assert result["state"] == "completed"
    assert result["attention_count"] == 0
    assert result["intensity"] == 0.2


def test_empty_canonical_work_projects_idle():
    result = LivingAgentWorkProjection.project(_work(task_counts={}, orders=[], active_projects=0), _attention())
    assert result["state"] == "idle"
    assert result["workers_active"] == 0
    assert result["projects_active"] == 0
    assert result["intensity"] == 0.0
