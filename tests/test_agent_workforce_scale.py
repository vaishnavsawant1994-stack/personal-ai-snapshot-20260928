from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore


def test_one_hundred_projects_keep_independent_teams_assignments_and_versions(tmp_path):
    service = AgentWorkforceService(AgentWorkforceStore(tmp_path / "agents.sqlite3"))
    coding = service.store.get_template_by_slug("coding")
    coding_version = service.store.preferred_version(coding["id"])["id"]

    all_instance_ids = set()
    assigned_instance_ids = set()
    for index in range(100):
        project_id = f"project-{index:03d}"
        team = service.create_team(project_id, {"coding": 1, "research": 1})["members"]
        assert len(team) == 3
        assert len([row for row in team if row["is_manager"]]) == 1
        assert {row["project_id"] for row in team} == {project_id}
        assert not (all_instance_ids & {row["instance_id"] for row in team})
        all_instance_ids.update(row["instance_id"] for row in team)

        coding_member = next(row for row in team if row["role"] == "coding")
        assert coding_member["version_id"] == coding_version
        assignment = service.store.assign(
            coding_member["instance_id"],
            project_id=project_id,
            work_order_id=f"work-{index:03d}",
        )
        assert assignment["project_id"] == project_id
        assert assignment["version_id"] == coding_version
        assigned_instance_ids.add(assignment["instance_id"])

    summary = service.summary()
    assert summary["projects_using_agents"] == 100
    assert summary["total_instances"] == 300
    assert summary["active_instances"] == 100
    assert summary["running_tasks"] == 100
    assert len(all_instance_ids) == 300
    assert len(assigned_instance_ids) == 100

    # Project 000 can never be reassigned to Project 099 even under a large pool.
    first_coding = next(
        row for row in service.project_team("project-000") if row["role"] == "coding"
    )
    try:
        service.store.assign(
            first_coding["instance_id"],
            project_id="project-099",
            work_order_id="cross-project-attempt",
        )
        raise AssertionError("cross-project assignment must be rejected")
    except PermissionError:
        pass

    # All project-team queries remain isolated at scale.
    for index in (0, 1, 49, 50, 98, 99):
        project_id = f"project-{index:03d}"
        rows = service.project_team(project_id)
        assert len(rows) == 3
        assert {row["project_id"] for row in rows} == {project_id}


def test_one_hundred_projects_can_provision_and_assign_concurrently_without_context_mix(tmp_path):
    service = AgentWorkforceService(AgentWorkforceStore(tmp_path / "concurrent-agents.sqlite3"))

    def provision(index: int):
        project_id = f"parallel-{index:03d}"
        service.create_team(project_id, {"coding": 1, "research": 1})
        return project_id

    with ThreadPoolExecutor(max_workers=20) as pool:
        projects = list(pool.map(provision, range(100)))

    assert len(set(projects)) == 100
    assert service.summary()["projects_using_agents"] == 100
    assert service.summary()["total_instances"] == 300

    coding_members = {}
    for project_id in projects:
        team = service.project_team(project_id)
        assert len(team) == 3
        assert {row["project_id"] for row in team} == {project_id}
        assert len([row for row in team if row["is_manager"]]) == 1
        coding_members[project_id] = next(row for row in team if row["role"] == "coding")

    def assign(project_id: str):
        member = coding_members[project_id]
        assignment = service.store.assign(
            member["instance_id"],
            project_id=project_id,
            work_order_id=f"parallel-work-{project_id}",
        )
        return assignment["project_id"], assignment["instance_id"], assignment["version_id"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        assignments = list(pool.map(assign, projects))

    assert {project for project, _instance, _version in assignments} == set(projects)
    assert len({instance for _project, instance, _version in assignments}) == 100
    assert len({service.store.get_instance(instance)["project_id"] for _project, instance, _version in assignments}) == 100
    assert service.summary()["active_instances"] == 100
    assert service.summary()["running_tasks"] == 100

    # Every assigned worker is still pinned to exactly its own Project.
    for project_id, instance_id, _version_id in assignments:
        assert service.store.get_instance(instance_id)["project_id"] == project_id
