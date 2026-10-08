from __future__ import annotations

import sqlite3

from future_intelligence.work_orchestration.p10_bridge import P10WorkBridge


def _goal():
    return {
        "id": "g1",
        "owner_id": "owner",
        "description": "Ship a verified release",
        "desired_outcome": "A release whose deployment is verified",
        "priority": 80,
        "privacy": "internal",
        "risk": "medium",
        "allowed_capabilities": ["deploy"],
        "prohibited_actions": [],
        "success_criteria": ["deployment verified"],
        "constraints": [],
        "created_at": 1.0,
        "updated_at": 1.0,
    }


def _plan(status="READY"):
    return {
        "id": "p1",
        "goal_id": "g1",
        "owner_id": "owner",
        "state": status,
        "tasks": [
            {
                "id": "build",
                "objective": "Build release",
                "dependencies": [],
                "required_capabilities": ["deploy"],
                "requested_tool": "build",
                "status": "WAITING",
                "verification_required": True,
                "approval_required": False,
                "retry_limit": 1,
            },
            {
                "id": "deploy",
                "objective": "Deploy release",
                "dependencies": ["build"],
                "required_capabilities": ["deploy"],
                "requested_tool": "deploy",
                "status": "WAITING",
                "verification_required": True,
                "approval_required": True,
                "retry_limit": 0,
            },
        ],
        "created_at": 2.0,
        "updated_at": 2.0,
    }


def test_bridge_projects_p10_dag_and_versions():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE p10_goals (id TEXT PRIMARY KEY, owner_id TEXT, document TEXT, updated_at REAL);
        CREATE TABLE p10_plans (id TEXT PRIMARY KEY, goal_id TEXT, owner_id TEXT, state TEXT, document TEXT, updated_at REAL);
        """
    )
    bridge = P10WorkBridge(connection)

    first = bridge.project_plan(_plan(), _goal())
    assert first.version == 1
    assert first.work_orders[1].dependencies == (first.work_orders[0].id,)
    assert first.work_orders[0].evidence_contract.requirements[0].min_provenance == "tool_verified"

    synced = bridge.project_plan(_plan("RUNNING"), _goal())
    assert synced.id == first.id
    assert synced.version == 1

    replanned = bridge.project_plan(_plan("READY"), _goal(), force_new_version=True)
    assert replanned.version == 2
    assert replanned.supersedes_plan_id == first.id
