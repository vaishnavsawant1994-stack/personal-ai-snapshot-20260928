from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.capabilities import CapabilityRegistry, CapabilityState
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.versioned_replanning import install as install_versioned_replanning
from playbooks import PlaybookRegistry
from qualification import (
    CapabilityClaimState,
    CapabilityQualificationStore,
    QualificationState,
    ReplayCase,
    ReplayRunner,
)


class _Gate:
    pass


class _Models:
    def __init__(self):
        self.prompts = []

    def json(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return {
            "summary": "Research using the advisory playbook",
            "assumptions": [],
            "work_orders": [
                {
                    "id": "research",
                    "title": "Research",
                    "objective": "Collect and synthesize evidence",
                    "worker_type": "research",
                    "dependencies": [],
                    "required_capabilities": ["research"],
                    "expected_output": "evidence-backed notes",
                    "success_criteria": ["notes answer the research question"],
                    "verification_required": False,
                }
            ],
            "milestones": [],
        }


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)
install_versioned_replanning(AdvancedAutonomy)


def test_default_playbooks_are_advisory_and_resolve_deterministically():
    registry = PlaybookRegistry.default()
    assert registry.status()["count"] == 7
    software = registry.resolve(project_type="software")
    assert software is not None
    assert software.id == "software_project"
    research = registry.resolve(playbook_id="research_project")
    assert research is not None
    prompt = research.prompt_text()
    assert "Authority: advisory only" in prompt
    assert "cannot grant tools" in prompt
    with pytest.raises(KeyError):
        registry.resolve(playbook_id="does-not-exist")


def test_exact_head_replay_and_evidence_are_required_for_qualified_state(tmp_path):
    store = CapabilityQualificationStore(tmp_path / "qualification.sqlite3")
    runner = ReplayRunner(store.replays)
    case = ReplayCase(
        id="read-docs-happy-path",
        tool_name="read_docs",
        capability="knowledge.read",
        description="Read a known deterministic fixture",
        input_descriptor={"token": "raw-secret-must-not-be-stored", "fixture": "doc-1"},
        evidence_refs=("fixture:doc-1",),
    )
    replay = runner.run(
        case,
        exact_head_sha="abc123",
        invoke=lambda: {"verified": True, "content": "fixture", "secret": "raw-output-secret"},
        verify=lambda output: output.get("verified") is True and output.get("content") == "fixture",
        evidence_refs=("ci:run-100",),
    )
    assert replay.passed is True

    claim = store.create_claim(
        tool_name="read_docs",
        capability="knowledge.read",
        exact_head_sha="abc123",
        qualification_suite="knowledge-read-v1",
        evidence_refs=("qualification:report-1",),
    )
    entry = store.promote_claim(claim.id)
    assert entry.state is QualificationState.QUALIFIED
    assert entry.exact_head_sha == "abc123"
    assert replay.id in entry.replay_ids
    assert "qualification:report-1" in entry.evidence_refs
    assert store.claims.get(claim.id).state is CapabilityClaimState.QUALIFIED

    with sqlite3.connect(tmp_path / "qualification.sqlite3") as con:
        payload = con.execute("SELECT payload_json FROM capability_replays WHERE id=?", (replay.id,)).fetchone()[0]
    assert "raw-secret-must-not-be-stored" not in payload
    assert "raw-output-secret" not in payload


def test_wrong_head_or_failed_replay_cannot_qualify(tmp_path):
    store = CapabilityQualificationStore(tmp_path / "qualification.sqlite3")
    runner = ReplayRunner(store.replays)
    case = ReplayCase(
        id="send-check",
        tool_name="send_message",
        capability="communications.send",
        description="Qualification fixture",
        input_descriptor={"fixture": "message-1"},
        evidence_refs=("fixture:message-1",),
    )
    runner.run(
        case,
        exact_head_sha="old-head",
        invoke=lambda: {"verified": True},
        verify=lambda output: bool(output.get("verified")),
    )
    runner.run(
        ReplayCase(
            id="send-check-current",
            tool_name="send_message",
            capability="communications.send",
            description="Current-head negative fixture",
            input_descriptor={"fixture": "message-2"},
            evidence_refs=("fixture:message-2",),
        ),
        exact_head_sha="new-head",
        invoke=lambda: {"verified": False},
        verify=lambda output: bool(output.get("verified")),
    )
    claim = store.create_claim(
        tool_name="send_message",
        capability="communications.send",
        exact_head_sha="new-head",
        qualification_suite="communications-v1",
        evidence_refs=("ci:run-200",),
    )
    with pytest.raises(RuntimeError, match="qualification claim is not satisfied"):
        store.promote_claim(claim.id)
    assert store.claims.get(claim.id).state is CapabilityClaimState.PROPOSED


def test_qualified_state_cannot_be_set_without_claim_gate(tmp_path):
    store = CapabilityQualificationStore(tmp_path / "qualification.sqlite3")
    with pytest.raises(ValueError, match="only be set through promote_claim"):
        store.set_nonqualified_state(
            "read_docs",
            "knowledge.read",
            QualificationState.QUALIFIED,
        )


def test_capability_registry_overlays_manifest_but_prohibited_tool_stays_disabled():
    tools = [
        SimpleNamespace(
            name="read_docs",
            description="Read documents",
            capability="knowledge.read",
            connector_id="drive",
            prohibited=False,
            risk=0,
            verification_required=False,
            requires_reauth=False,
            allowed_destinations=None,
        ),
        SimpleNamespace(
            name="dangerous_tool",
            description="Never use",
            capability="danger.execute",
            connector_id=None,
            prohibited=True,
            risk=4,
            verification_required=True,
            requires_reauth=True,
            allowed_destinations=None,
        ),
    ]
    registry = SimpleNamespace(all=lambda: tools)
    manifest = {
        "read_docs": {
            "state": "qualified",
            "exact_head_sha": "abc123",
            "qualification_suite": "knowledge-read-v1",
            "evidence_refs": ["ci:run-100"],
        },
        "dangerous_tool": {
            "state": "qualified",
            "exact_head_sha": "abc123",
            "qualification_suite": "bad",
            "evidence_refs": ["should-not-matter"],
        },
    }
    capabilities = CapabilityRegistry.from_tool_registry(registry, qualification_manifest=manifest)
    read = capabilities.get_tool("read_docs")
    danger = capabilities.get_tool("dangerous_tool")
    assert read.state is CapabilityState.QUALIFIED
    assert read.exact_head_sha == "abc123"
    assert read.qualification_evidence == ("ci:run-100",)
    assert danger.state is CapabilityState.DISABLED
    assert danger.exact_head_sha is None
    assert capabilities.available_tool_names() == ("read_docs",)


def test_hierarchical_runtime_passes_selected_playbook_as_advisory_guidance(tmp_path):
    models = _Models()
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "autonomy.sqlite3", models=models)
    goal = autonomy.create_goal(
        "Research a market question",
        desired_outcome="Evidence-backed answer",
        allowed_capabilities=["research"],
        success_criteria=["answer is supported by evidence"],
    )
    result = autonomy.propose_hierarchical_plan(goal["id"], playbook_id="research_project")
    assert result["created"] is True
    assert result["playbook"]["id"] == "research_project"
    assert result["playbook"]["authority"] == "advisory_only"
    assert result["work_plan"]["critic"]["playbook_id"] == "research_project"
    assert result["work_plan"]["critic"]["playbook_authority"] == "advisory_only"
    assert "Playbook: Research project" in models.prompts[-1]
    assert "cannot grant tools" in models.prompts[-1]
    status = autonomy.status()["hierarchical_planning"]
    assert status["playbooks"]["count"] == 7
    assert status["qualification"]["authority"] == "qualification_metadata_only"
