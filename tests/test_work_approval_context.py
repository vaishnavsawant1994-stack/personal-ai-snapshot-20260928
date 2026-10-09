from types import SimpleNamespace

import server.approvals_center_api as api


class _Registry:
    def is_active(self, _device_id):
        return True

    def authorize(self, _device_id, _permission):
        return True


class _Manager:
    def list_pending(self, **_kwargs):
        return [{
            "approval_id": "ap-1",
            "execution_id": "exec-1",
            "action": "publish_content",
            "status": "pending",
            "created_at": 1.0,
            "expires_at": 999.0,
            "destination": "example.com",
            "data_classification": "internal",
            "device_id": None,
            "session_id": None,
        }]


class _Attention:
    def summary(self, **_kwargs):
        return {
            "items": [{
                "id": "attn-1",
                "kind": "approval_required",
                "severity": "urgent",
                "approval_id": "ap-1",
                "project_id": "project-1",
                "project_name": "Marketing Launch",
                "goal_id": "goal-1",
                "plan_id": "plan-1",
                "plan_version": 2,
                "work_order_id": "wo-1",
                "work_order_title": "Publish campaign",
                "worker_type": "communications",
                "reason": "A governed external action is waiting for the owner.",
                "expected_effect": "publish_content → example.com",
                "deep_link": "/iphone/?section=approvals&approval=ap-1",
            }]
        }


def _route(router, path):
    return next(route.endpoint for route in router.routes if route.path == path)


def test_approvals_center_enriches_pending_approval_with_work_context(monkeypatch):
    monkeypatch.setattr(
        api,
        "current_trusted_request",
        lambda: SimpleNamespace(device_id="device-1", session_id="session-1"),
    )
    monkeypatch.setattr(api, "WorkAttentionService", lambda *_args, **_kwargs: _Attention())
    runtime = {
        "device_registry": _Registry(),
        "agent_executor": SimpleNamespace(approvals=_Manager()),
        "project_store": object(),
    }
    router = api.approvals_center_router(runtime)
    result = _route(router, "/iphone/api/approvals-center")(limit=50)

    assert result["authority"] == "approval_manager"
    assert result["decision_endpoint_authority"] == "stage_2_approval_api"
    item = result["approvals"][0]
    assert item["work_context_available"] is True
    assert item["project_name"] == "Marketing Launch"
    assert item["goal_id"] == "goal-1"
    assert item["plan_id"] == "plan-1"
    assert item["plan_version"] == 2
    assert item["work_order_id"] == "wo-1"
    assert item["work_order_title"] == "Publish campaign"
    assert item["worker_type"] == "communications"
    assert item["expected_effect"] == "publish_content → example.com"


def test_approvals_center_falls_back_without_project_work_context(monkeypatch):
    monkeypatch.setattr(
        api,
        "current_trusted_request",
        lambda: SimpleNamespace(device_id="device-1", session_id="session-1"),
    )
    runtime = {
        "device_registry": _Registry(),
        "agent_executor": SimpleNamespace(approvals=_Manager()),
    }
    router = api.approvals_center_router(runtime)
    result = _route(router, "/iphone/api/approvals-center")(limit=50)
    assert result["approvals"][0]["work_context_available"] is False
    assert "project_id" not in result["approvals"][0]
