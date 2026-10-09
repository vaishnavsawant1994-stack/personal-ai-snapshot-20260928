from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "pwa" / "projects-work-runtime.js"
HOME = ROOT / "pwa" / "home-chat-redesign.js"
SERVICE_WORKER = ROOT / "pwa" / "sw.js"
API = ROOT / "server" / "project_work_api.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_projects_work_adapter_is_loaded_after_existing_views():
    runtime = _read(RUNTIME)
    home = _read(HOME)

    assert "window.renderProjectPlan" in runtime
    assert "window.renderProjectLive" in runtime
    assert "__vishnuLegacyProjectPlan" in runtime
    assert "__vishnuLegacyProjectLive" in runtime
    assert "authority:'presentation_only'" in runtime

    assert "/iphone/projects-work-runtime.js" in home
    assert "script[data-canonical-project-work]" in home
    assert "dataset.canonicalProjectWork" in home
    assert "script.async=false" in home


def test_projects_work_ui_consumes_canonical_work_contract_only():
    runtime = _read(RUNTIME)

    required = (
        "/work`",
        "/work/history`",
        "/work/plan`",
        "/tasks/${encodeURIComponent(taskId)}/execute",
        "/pause",
        "/resume",
        "/cancel",
        "snapshot.evidence",
        "latest_review",
        "latest_delta",
        "WorkOrders",
        "Version history",
        "waiting_approval_task_ids",
        "blocked_task_ids",
    )
    for marker in required:
        assert marker in runtime, marker

    # The old ProjectStore task runner remains available elsewhere, but this
    # canonical adapter must never pretend it is the WorkOrder executor.
    assert "/execution" not in runtime
    assert "approval is not granted from this view" in runtime.lower()
    assert "no ui-only execution state is invented" in runtime.lower()


def test_projects_work_ui_keeps_mobile_and_desktop_layouts():
    runtime = _read(RUNTIME)

    assert "@media(max-width:900px)" in runtime
    assert "@media(max-width:760px)" in runtime
    assert ".cw-layout" in runtime
    assert ".cw-live-list" in runtime
    assert ".cw-order-grid" in runtime
    assert "min-height:44px" in runtime


def test_project_work_server_routes_match_frontend_contract():
    source = _read(API)

    routes = (
        '@router.get("/{project_id}/work")',
        '@router.get("/{project_id}/work/history")',
        '@router.post("/{project_id}/work/plan")',
        '@router.get("/{project_id}/work/{plan_id}/tasks/{task_id}/evidence")',
        '@router.post("/{project_id}/work/{plan_id}/tasks/{task_id}/execute")',
        '@router.post("/{project_id}/work/{plan_id}/pause")',
        '@router.post("/{project_id}/work/{plan_id}/resume")',
        '@router.post("/{project_id}/work/{plan_id}/cancel")',
    )
    for route in routes:
        assert route in source, route

    assert 'require_trusted_session=True' in source
    assert '"authority": "existing_p10_p6_runtime"' in source
    assert '"legacy_project_task_runner_preserved": True' in source


def test_service_worker_precaches_canonical_work_adapter():
    source = _read(SERVICE_WORKER)

    assert "personal-ai-iphone-v32" in source
    assert "'/iphone/projects-work-runtime.js'" in source
    assert "url.pathname.startsWith('/iphone/api/')" in source


def test_projects_work_runtime_has_valid_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed in this test environment")
    result = subprocess.run(
        [node, "--check", str(RUNTIME)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
