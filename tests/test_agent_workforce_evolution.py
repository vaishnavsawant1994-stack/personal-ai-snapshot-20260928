from __future__ import annotations

from core.events import EventBus
from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore
from future_intelligence.agent_workforce.evolution import AgentEvolutionRuntime
from future_intelligence.agent_workforce.learning_bridge import AgentLearningEventBridge


def workforce(tmp_path):
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    return AgentWorkforceService(store)


def add_lessons(service, template_id, version_id, prefix, count=3):
    rows = []
    for index in range(count):
        rows.append(
            service.record_learning(
                template_id,
                version_id,
                kind="owner_correction" if index == 0 else "verification_failure",
                summary=f"{prefix} lesson {index + 1}",
                project_id=f"project-{index + 1}",
                work_order_id=f"work-{prefix}-{index + 1}",
                score=0.0,
                evidence_ref=f"evidence:{prefix}:{index + 1}",
            )
        )
    return rows


def qualified(name):
    return {
        "passed": True,
        "qualification_run_id": name,
        "test_summary": "Agent regression qualification passed.",
        "evidence_refs": [f"evidence:qualification:{name}"],
    }


def test_three_evidence_backed_lessons_create_one_non_authoritative_vnext_candidate(tmp_path):
    service = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    parent = service.store.preferred_version(coding["id"])
    observations = add_lessons(service, coding["id"], parent["id"], "v10")

    evolution = AgentEvolutionRuntime(service, enabled=True, observation_threshold=3, interval_seconds=60)
    created = evolution.scan_once()

    assert len(created) == 1
    record = created[0]
    candidate = service.store.get_version(record.candidate_version_id)
    assert candidate["version"] == "1.1"
    assert candidate["state"] == "candidate"
    assert candidate["parent_version_id"] == parent["id"]
    assert candidate["capabilities"] == parent["capabilities"]
    assert candidate["tools"] == parent["tools"]
    assert candidate["model_policy"] == parent["model_policy"]
    assert candidate["qualification"]["authority"] is False
    assert candidate["qualification"]["auto_evolution"]["generated"] is True
    assert set(candidate["qualification"]["auto_evolution"]["source_observation_ids"]) == {row["id"] for row in observations}
    assert "v10 lesson 1" in candidate["instructions"]
    assert service.store.preferred_version(coding["id"])["id"] == parent["id"]


def test_repeated_scan_does_not_duplicate_open_candidate(tmp_path):
    service = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    parent = service.store.preferred_version(coding["id"])
    add_lessons(service, coding["id"], parent["id"], "same")
    evolution = AgentEvolutionRuntime(service, enabled=True, observation_threshold=3)

    first = evolution.scan_once()
    second = evolution.scan_once()

    assert len(first) == 1
    assert second == []
    assert [row["version"] for row in service.store.list_versions(coding["id"])].count("1.1") == 1


def test_observations_without_evidence_never_create_upgrade_candidate(tmp_path):
    service = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    parent = service.store.preferred_version(coding["id"])
    for index in range(5):
        service.record_learning(
            coding["id"], parent["id"], kind="model_note", summary=f"unverified {index}"
        )
    evolution = AgentEvolutionRuntime(service, enabled=True, observation_threshold=3)
    assert evolution.scan_once() == []
    assert {row["version"] for row in service.store.list_versions(coding["id"])} == {"1.0"}


def test_after_qualified_v11_promotion_new_v11_lessons_create_v12_candidate(tmp_path):
    service = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    v10 = service.store.preferred_version(coding["id"])
    add_lessons(service, coding["id"], v10["id"], "first")
    evolution = AgentEvolutionRuntime(service, enabled=True, observation_threshold=3)
    v11_record = evolution.scan_once()[0]
    v11 = service.promote_version(v11_record.candidate_version_id, state="preferred", qualification=qualified("v11"))
    assert v11["version"] == "1.1"

    add_lessons(service, coding["id"], v11["id"], "second")
    created = evolution.scan_once()
    assert len(created) == 1
    v12 = service.store.get_version(created[0].candidate_version_id)
    assert v12["version"] == "1.2"
    assert v12["state"] == "candidate"
    assert service.store.preferred_version(coding["id"])["id"] == v11["id"]


def test_canonical_work_mistakes_flow_automatically_into_vnext_candidate(tmp_path):
    events = EventBus()
    service = AgentWorkforceService(AgentWorkforceStore(tmp_path / "agents.sqlite3"), events=events)
    coding = service.store.get_template_by_slug("coding")
    parent = service.store.preferred_version(coding["id"])
    bridge = AgentLearningEventBridge(service, events)

    for index, event_name in enumerate(
        ("work.order.blocked", "work.order.recovery_required", "work.review.rejected"), start=1
    ):
        instance = service.create_instance(coding["id"], project_id=f"project-{index}", version_id=parent["id"])
        service.store.assign(
            instance["id"], project_id=f"project-{index}", work_order_id=f"work-{index}"
        )
        events.emit(
            event_name,
            event_id=f"workevt-auto-{index}",
            work_order_id=f"work-{index}",
            project_id=f"project-{index}",
            reason=f"verified runtime lesson {index}",
            state="BLOCKED" if index == 1 else "RECOVERY_REQUIRED" if index == 2 else "REVIEWING",
            review_state="rejected" if index == 3 else None,
        )

    observations = service.store.list_observations(coding["id"], version_id=parent["id"])
    assert len(observations) == 3
    assert all(row["evidence_ref"].startswith("work-event:workevt-auto-") for row in observations)

    evolution = AgentEvolutionRuntime(service, enabled=True, observation_threshold=3)
    candidates = evolution.scan_once()
    assert len(candidates) == 1
    vnext = service.store.get_version(candidates[0].candidate_version_id)
    assert vnext["version"] == "1.1"
    assert vnext["state"] == "candidate"
    assert vnext["parent_version_id"] == parent["id"]
    assert vnext["capabilities"] == parent["capabilities"]
    assert vnext["tools"] == parent["tools"]
    assert service.store.preferred_version(coding["id"])["id"] == parent["id"]
    bridge.close()


def test_evolution_can_be_disabled_without_mutating_versions(tmp_path):
    service = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    parent = service.store.preferred_version(coding["id"])
    add_lessons(service, coding["id"], parent["id"], "disabled")
    evolution = AgentEvolutionRuntime(service, enabled=False)
    assert evolution.scan_once() == []
    assert {row["version"] for row in service.store.list_versions(coding["id"])} == {"1.0"}
