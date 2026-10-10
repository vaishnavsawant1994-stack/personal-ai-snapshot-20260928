from __future__ import annotations

from types import SimpleNamespace

import pytest

from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore


def service(tmp_path, **kwargs):
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    return AgentWorkforceService(store, **kwargs)


def qualification(name="agent-v1.1"):
    return {
        "passed": True,
        "qualification_run_id": name,
        "test_summary": "Regression and isolation qualification passed.",
        "evidence_refs": [f"evidence:{name}"],
    }


def test_core_agents_seed_once_and_summary_is_real(tmp_path):
    workforce = service(tmp_path)
    first = workforce.catalog()
    second = AgentWorkforceService(workforce.store).catalog()
    assert len(first) >= 10
    assert len(second) == len(first)
    assert workforce.summary()["total_agents"] == len(first)
    assert workforce.summary()["total_instances"] == 0
    assert workforce.summary()["success_rate"] is None


def test_runtime_instance_is_project_scoped_and_cannot_cross_assign(tmp_path):
    workforce = service(tmp_path)
    coding = workforce.store.get_template_by_slug("coding")
    worker = workforce.create_instance(coding["id"], project_id="project-a")
    with pytest.raises(PermissionError):
        workforce.store.assign(worker["id"], project_id="project-b", work_order_id="work-b")
    assignment = workforce.store.assign(worker["id"], project_id="project-a", work_order_id="work-a")
    assert assignment["project_id"] == "project-a"
    assert workforce.store.get_instance(worker["id"])["current_work_order_id"] == "work-a"


def test_same_agent_type_can_have_many_isolated_instances_across_projects(tmp_path):
    workforce = service(tmp_path)
    coding = workforce.store.get_template_by_slug("coding")
    a = [workforce.create_instance(coding["id"], project_id="a") for _ in range(4)]
    b = [workforce.create_instance(coding["id"], project_id="b") for _ in range(3)]
    assert len(workforce.store.list_instances(template_id=coding["id"], project_id="a")) == 4
    assert len(workforce.store.list_instances(template_id=coding["id"], project_id="b")) == 3
    assert {row["project_id"] for row in a} == {"a"}
    assert {row["project_id"] for row in b} == {"b"}


def test_team_creation_adds_project_manager_and_requested_specialists(tmp_path):
    workforce = service(tmp_path)
    team = workforce.create_team("p1", {"coding": 3, "research": 2, "reviewer": 1})
    roles = [row["role"] for row in team["members"]]
    assert roles.count("project_manager") == 1
    assert roles.count("coding") == 3
    assert roles.count("research") == 2
    assert roles.count("reviewer") == 1
    assert {row["project_id"] for row in team["members"]} == {"p1"}


def test_team_rebuild_never_duplicates_project_manager_even_if_requested(tmp_path):
    workforce = service(tmp_path)
    workforce.ensure_project_manager("p1")
    workforce.create_team("p1", {"project-manager": 9, "coding": 1})
    workforce.create_team("p1", {"project-manager": 2, "research": 1})
    team = workforce.project_team("p1")
    assert len([row for row in team if row["is_manager"]]) == 1
    roles = [row["role"] for row in team]
    assert roles.count("project_manager") == 1
    assert roles.count("coding") == 1
    assert roles.count("research") == 1


def test_ensure_project_manager_is_idempotent(tmp_path):
    workforce = service(tmp_path)
    first = workforce.ensure_project_manager("p1")
    second = workforce.ensure_project_manager("p1")
    team = workforce.project_team("p1")
    assert first["id"] == second["instance_id"]
    assert len([row for row in team if row["is_manager"]]) == 1


def test_versions_coexist_and_preferred_promotion_requires_real_qualification(tmp_path):
    workforce = service(tmp_path)
    coding = workforce.store.get_template_by_slug("coding")
    v1 = workforce.store.preferred_version(coding["id"])
    v11 = workforce.create_version(
        coding["id"], version="1.1", parent_version_id=v1["id"],
        instructions=v1["instructions"] + "\nUse test-first repair when practical.",
    )
    with pytest.raises(ValueError):
        workforce.promote_version(v11["id"], state="preferred", qualification={"passed": False})
    with pytest.raises(ValueError):
        workforce.promote_version(v11["id"], state="preferred", qualification={"passed": True})
    with pytest.raises(ValueError):
        workforce.promote_version(
            v11["id"], state="stable",
            qualification={"passed": True, "test_summary": "passed but no evidence"},
        )
    promoted = workforce.promote_version(v11["id"], state="preferred", qualification=qualification())
    versions = workforce.store.list_versions(coding["id"])
    assert promoted["state"] == "preferred"
    assert promoted["qualification"]["authority"] is False
    assert {row["version"] for row in versions} >= {"1.0", "1.1"}
    assert workforce.store.get_version(v1["id"])["state"] == "stable"


def test_work_order_pins_exact_agent_version(tmp_path):
    workforce = service(tmp_path)
    coding = workforce.store.get_template_by_slug("coding")
    v1 = workforce.store.preferred_version(coding["id"])
    worker = workforce.create_instance(coding["id"], project_id="p", version_id=v1["id"])
    assignment = workforce.store.assign(worker["id"], project_id="p", work_order_id="w1")
    v11 = workforce.create_version(coding["id"], version="1.1", parent_version_id=v1["id"], instructions=v1["instructions"])
    workforce.promote_version(v11["id"], state="preferred", qualification=qualification("pinning"))
    assert workforce.store.get_assignment(assignment["id"])["version_id"] == v1["id"]


def test_learning_is_evidence_reference_not_self_adoption(tmp_path):
    workforce = service(tmp_path)
    coding = workforce.store.get_template_by_slug("coding")
    version = workforce.store.preferred_version(coding["id"])
    observation = workforce.record_learning(
        coding["id"], version["id"], kind="verification_failure",
        summary="Remote ref was not verified after push.", project_id="p", work_order_id="w",
        score=0.0, evidence_ref="evidence:123",
    )
    assert observation["evidence_ref"] == "evidence:123"
    assert workforce.store.get_version(version["id"])["state"] == "preferred"


class FakeWorkStore:
    def get_work_order(self, work_order_id):
        return SimpleNamespace(id=work_order_id, project_id="project-a") if work_order_id == "work-a" else None


class FakeIntelligence:
    def invoke(self, work_order_id, prompt, **kwargs):
        return SimpleNamespace(
            request_id="request-1", provider_id="provider", model_id="model", content="proposal",
            usage=SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3, estimated_cost=0.0),
        )


def test_specialist_chat_remains_project_and_work_bound_and_has_no_authority(tmp_path):
    workforce = service(tmp_path, work_store=FakeWorkStore(), worker_intelligence=FakeIntelligence())
    coding = workforce.store.get_template_by_slug("coding")
    worker = workforce.create_instance(coding["id"], project_id="project-a")
    workforce.assign(worker["id"], project_id="project-a", work_order_id="work-a")
    result = workforce.specialist_proposal(
        work_order_id="work-a", prompt="fix tests", project_id="project-a", instance_id=worker["id"], context="repo only"
    )
    assert result["content"] == "proposal"
    assert result["model_output_authority"] is False
    assert result["completion_authority"] is False
    with pytest.raises(PermissionError):
        workforce.specialist_proposal(
            work_order_id="work-a", prompt="fix tests", project_id="project-b", instance_id=worker["id"]
        )
