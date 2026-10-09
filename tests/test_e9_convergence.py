from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.executor import AgentExecutor
from agent.planner import InvalidPlan, Planner
from automation.work_bridge import AutomationWorkBridge
from core.events import EventBus
from evidence import EvidenceStore
from evidence.ingestion import EvidenceIngestor
from evolution import ContinuousEvolutionRuntime, EvolutionMode, EvolutionService, EvolutionStore
from future_intelligence.work_orchestration.attempt_parking import park_attempt, resume_parked_attempt
from future_intelligence.work_orchestration.attempts import WorkAttemptStatus
from future_intelligence.work_orchestration.durable_store import DurableWorkStore
from future_intelligence.work_orchestration.models import (
    GoalSpec,
    ReadinessStatus,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)
from future_intelligence.work_orchestration.p10_authority import P10CanonicalWorkAuthority
from identity import IdentityRuntime, IdentityStore, SelfAuthorityViolation
from integrations.extension_contracts import ExtensionGrantStore, ExtensionManifest
from integrations.provider_contracts import ProviderKind, conformance_snapshot
from tools.registry import Risk, Tool, ToolRegistry


class _ToolSet:
    def __init__(self, tools):
        self._tools = list(tools)

    def all(self):
        return self._tools

    def schema_text(self):
        return "\n".join(item.name for item in self._tools)


def test_simple_planner_preserves_bounded_structure_and_rejects_prohibited_tool():
    good = Tool("read", "read", lambda params: params)
    bad = Tool("danger", "danger", lambda params: params, prohibited=True)
    planner = Planner(SimpleNamespace(), _ToolSet([good, bad]))
    plan = planner.validate(
        {
            "goal": "inspect",
            "version": 1,
            "execution_budget": {"max_steps": 2, "max_tool_calls": 2},
            "steps": [
                {
                    "id": "one",
                    "tool": "read",
                    "parameters": {"path": "README"},
                    "success_criteria": ["content observed"],
                    "verification": {"required": True, "method": "tool_contract"},
                    "retry_policy": {"max_attempts": 1, "safe_only": True},
                    "timeout_seconds": 30,
                },
                {"id": "two", "tool": "read", "parameters": {}, "depends_on": ["one"]},
            ],
        }
    )
    assert plan["steps"][1]["depends_on"] == ["one"]
    assert plan["execution_budget"]["max_steps"] == 2
    with pytest.raises(InvalidPlan, match="unavailable tool"):
        planner.validate({"goal": "bad", "steps": [{"tool": "danger", "parameters": {}}]})


def test_tool_schema_contracts_fail_closed_at_dispatch():
    registry = object.__new__(ToolRegistry)
    tool = Tool(
        "inspect",
        "inspect",
        lambda params: {"ok": params["path"]},
        input_schema={"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "string"}}, "additionalProperties": False},
    )
    assert registry.dispatch(tool, {"path": "readme"}) == {"ok": "readme"}
    with pytest.raises(ValueError):
        registry.dispatch(tool, {})
    with pytest.raises(ValueError):
        registry.dispatch(tool, {"path": "x", "extra": True})


def _body_manifest(path: Path):
    path.write_text(
        '{"body_version":1,"identity":{"name":"Vishnu","role":"personal_ai"},'
        '"contracts":{"work":1,"evidence":2,"evolution":1,"continuity":1,"extension":1},'
        '"mission":["assist owner"],"principles":["Self never grants authority"]}',
        encoding="utf-8",
    )


def test_identity_runtime_bootstraps_once_and_never_auto_activates_changed_body(tmp_path):
    manifest = tmp_path / "body.yaml"; _body_manifest(manifest)
    store = IdentityStore(tmp_path / "identity.sqlite3")
    first = IdentityRuntime(store=store, running_git_revision="a" * 40, body_manifest_path=manifest)
    assert first.status().body_compatible is True
    first.update_self({"communication_style": {"tone": "clear"}}, actor="owner")
    assert first.context_dict()["self"]["communication_style"]["tone"] == "clear"
    second = IdentityRuntime(store=store, running_git_revision="b" * 40, body_manifest_path=manifest)
    assert second.status().bootstrap_state == "running_body_mismatch"
    assert second.status().active_git_revision == "a" * 40
    with pytest.raises(RuntimeError, match="does not match"):
        second.assert_body_compatible()
    with pytest.raises(SelfAuthorityViolation):
        first.update_self({"preferences": {"permissions": {"tools": "all"}}}, actor="owner")


def test_reasoning_system_includes_identity_but_denies_authority():
    system = AgentExecutor._grounded_system("", identity_context='{"self":{"personality":{"tone":"warm"}}}')
    assert "TRUSTED IDENTITY CONTEXT" in system
    assert "never grants permissions" in system


def _canonical_store():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    work = DurableWorkStore(connection=connection)
    evidence = EvidenceStore(connection=connection)
    goal = GoalSpec(id="goal", title="Goal", objective="Do it", desired_outcome="Done")
    order = WorkOrder(id="order", plan_id="plan", title="Task", objective="Read", worker_type="orchestrator", status=WorkOrderStatus.QUEUED)
    plan = WorkPlan(id="plan", goal_id="goal", version=1, summary="Plan", work_orders=(order,), readiness=ReadinessStatus.READY, status=WorkPlanStatus.READY)
    work.upsert_goal(goal); work.save_plan(plan)
    return connection, work, evidence, plan


def test_work_attempt_can_park_for_approval_and_resume_without_duplicate_attempt():
    _connection, work, _evidence, _plan = _canonical_store()
    claim = work.claim_work_order("order", worker_id="worker", runtime_epoch=1, lease_seconds=60)
    assert claim is not None
    park_attempt(work, claim.attempt.id, lease_token=claim.lease.lease_token, status=WorkAttemptStatus.WAITING_APPROVAL)
    assert work.get_lease("order") is None
    assert len(work.list_attempts("order")) == 1
    resumed = resume_parked_attempt(work, claim.attempt.id, worker_id="worker", runtime_epoch=1)
    assert resumed.attempt.id == claim.attempt.id
    assert len(work.list_attempts("order")) == 1


def test_p10_canonical_authority_completes_only_with_evidence():
    _connection, work, evidence, projected = _canonical_store()
    class Bridge:
        mode = "observe_only"
        def __init__(self): self.work=work; self.evidence=evidence
        def work_plan_for_p10(self, _plan_id): return projected
    authority=P10CanonicalWorkAuthority(Bridge(), runtime_epoch=1)
    claim=authority.claim("p10-plan","task") if False else None
    # Adapt the deterministic P10 order convention for this focused unit test.
    projected2=WorkPlan(id="p10-plan",goal_id="goal",version=2,summary="P10",work_orders=(WorkOrder(id="p10-plan:task",plan_id="p10-plan",title="Task",objective="Read",worker_type="orchestrator",status=WorkOrderStatus.QUEUED),),readiness=ReadinessStatus.READY,status=WorkPlanStatus.READY)
    work.save_plan(projected2)
    bridge=Bridge(); bridge.work_plan_for_p10=lambda _plan_id: projected2
    authority=P10CanonicalWorkAuthority(bridge,runtime_epoch=2)
    claim=authority.claim("p10-plan","task")
    p10_plan={"id":"p10-plan","goal_id":"goal","owner_id":"owner"}
    p10_goal={"id":"goal","privacy":"internal"}
    task={"id":"task","objective":"Read","status":"COMPLETED","retry_limit":0,"result_ref":"read-only-orchestration"}
    authority.settle(p10_plan,p10_goal,task,claim)
    assert work.get_order("p10-plan:task").status is WorkOrderStatus.COMPLETED
    assert evidence.list_evidence(work_order_id="p10-plan:task")


def test_continuous_evolution_ingests_feedback_but_has_no_execution_authority(tmp_path):
    events=EventBus(); evidence=EvidenceStore(tmp_path/"evidence.sqlite3"); ingestor=EvidenceIngestor(evidence); store=EvolutionStore(connection=evidence.connection)
    service=EvolutionService(store=store,ingestor=ingestor,mode=EvolutionMode.CO_EVOLVE)
    runtime=ContinuousEvolutionRuntime(events=events,ingestor=ingestor,evolution=service)
    events.emit("conversation.feedback",message="The workflow required repeated manual correction")
    assert any(item.source_type == "user_feedback" for item in evidence.list_evidence())
    assert not hasattr(runtime,"approve") and not hasattr(runtime,"handoff") and not hasattr(runtime,"deploy")


def test_automation_occurrence_has_deterministic_canonical_work_identity():
    _connection, work, _evidence, _plan = _canonical_store();events=EventBus()
    class Engine:
        def _run(self, _run_id): return {"id":"run-1","idempotency_key":"schedule:2026-10-10T08:00:00Z","started_at":"2026-10-10T08:00:00+00:00"}
        def workflow(self, _workflow_id): return {"id":"wf-1","title":"Morning brief","trigger":{"type":"schedule"},"steps":[{"kind":"prompt"}]}
    bridge=AutomationWorkBridge(engine=Engine(),work_store=work,events=events)
    first=bridge.record("run-1","wf-1",event_type="started")
    second=bridge.record("run-1","wf-1",event_type="completed")
    assert first["work_order_id"] == second["work_order_id"]
    assert work.get_order(first["work_order_id"]).status is WorkOrderStatus.COMPLETED


def test_provider_conformance_and_extension_install_never_grants_permission(tmp_path):
    class Reasoner:
        def chat(self): pass
        def json(self): pass
        def embed(self): pass
    snapshot=conformance_snapshot(Reasoner(),kind=ProviderKind.REASONING,provider_id="reasoner")
    assert snapshot.kind is ProviderKind.REASONING
    manifest=ExtensionManifest(id="example",version="1.0",requested_permissions=("files.read",),endpoint="https://example.invalid")
    grants=ExtensionGrantStore(tmp_path/"extensions.sqlite3")
    installed=grants.install(manifest)
    assert installed["granted_permissions"] == []
    with pytest.raises(PermissionError):grants.grant("example","files.read",actor="extension")
    grants.grant("example","files.read",actor="owner")
    assert grants.is_granted("example","files.read")
