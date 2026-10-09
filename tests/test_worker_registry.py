from __future__ import annotations

from future_intelligence.work_orchestration.capabilities import CapabilityRegistry
from future_intelligence.work_orchestration.models import ResourceScope, WorkOrder, WorkPlan
from future_intelligence.workers import WorkerRegistry


class _Tool:
    def __init__(self, name, capability, *, prohibited=False):
        self.name = name
        self.description = name
        self.capability = capability
        self.connector_id = None
        self.prohibited = prohibited
        self.risk = 2
        self.verification_required = True
        self.requires_reauth = False
        self.allowed_destinations = ()


class _Tools:
    def all(self):
        return [
            _Tool("gmail_send", "email.send"),
            _Tool("github_read", "github.read"),
            _Tool("web_search", "web.search"),
            _Tool("blocked_admin", "admin", prohibited=True),
        ]


def _plan(order: WorkOrder) -> WorkPlan:
    return WorkPlan(id="p1", goal_id="g1", version=1, summary="test", work_orders=(order,))


def test_communications_worker_matches_available_email_tool():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Email",
        objective="Send update",
        worker_type="communications",
        allowed_capabilities=("email",),
        resource_scope=ResourceScope(metadata={"requested_tool": "gmail_send"}),
    )
    assessment = WorkerRegistry.default().assess_plan(
        _plan(order), CapabilityRegistry.from_tool_registry(_Tools())
    )
    assert assessment.status.value == "ready"
    assert assessment.assignments[0].selected_tool == "gmail_send"
    assert "gmail_send" in assessment.assignments[0].candidate_tools


def test_unknown_worker_role_holds_plan():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Unknown",
        objective="Unknown work",
        worker_type="superuser",
        allowed_capabilities=("read",),
    )
    assessment = WorkerRegistry.default().assess_plan(_plan(order), CapabilityRegistry.unavailable())
    assert assessment.status.value == "hold"
    assert any("unknown worker role" in blocker for blocker in assessment.blockers)


def test_requested_tool_holds_when_registry_is_unavailable():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Tool",
        objective="Use tool",
        worker_type="tool",
        resource_scope=ResourceScope(metadata={"requested_tool": "gmail_send"}),
    )
    assessment = WorkerRegistry.default().assess_plan(_plan(order), CapabilityRegistry.unavailable())
    assert assessment.status.value == "hold"
    assert any("ToolRegistry is unavailable" in blocker for blocker in assessment.blockers)


def test_generic_tool_worker_requires_explicit_tool_selection():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Tool",
        objective="Use a tool",
        worker_type="tool",
    )
    assessment = WorkerRegistry.default().assess_plan(
        _plan(order), CapabilityRegistry.from_tool_registry(_Tools())
    )
    assert assessment.status.value == "hold"
    assert any("does not select a tool" in blocker for blocker in assessment.blockers)


def test_generic_tool_worker_rejects_capability_mismatch():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Tool",
        objective="Use unrelated tool",
        worker_type="tool",
        allowed_capabilities=("research",),
        resource_scope=ResourceScope(metadata={"requested_tool": "gmail_send"}),
    )
    assessment = WorkerRegistry.default().assess_plan(
        _plan(order), CapabilityRegistry.from_tool_registry(_Tools())
    )
    assert assessment.status.value == "hold"
    assert any("does not advertise required capability research" in blocker for blocker in assessment.blockers)


def test_omitted_order_capability_cannot_escape_parent_goal_scope():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Email outside scope",
        objective="Try unrelated email tool",
        worker_type="communications",
        resource_scope=ResourceScope(
            metadata={
                "requested_tool": "gmail_send",
                "allowed_capabilities": ["research"],
            }
        ),
    )
    assessment = WorkerRegistry.default().assess_plan(
        _plan(order), CapabilityRegistry.from_tool_registry(_Tools())
    )
    assert assessment.status.value == "hold"
    assert any("outside the goal capability scope" in blocker for blocker in assessment.blockers)


def test_broad_role_scope_can_use_static_role_compatible_tool():
    order = WorkOrder(
        id="w1",
        plan_id="p1",
        title="Research",
        objective="Search the web",
        worker_type="research",
        resource_scope=ResourceScope(
            metadata={
                "requested_tool": "web_search",
                "allowed_capabilities": ["research"],
            }
        ),
    )
    assessment = WorkerRegistry.default().assess_plan(
        _plan(order), CapabilityRegistry.from_tool_registry(_Tools())
    )
    assert assessment.status.value == "ready"
    assert assessment.assignments[0].selected_tool == "web_search"
