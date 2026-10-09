from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
VISUAL = ROOT / "pwa" / "projects-work-visualization-runtime.js"
LOADER = ROOT / "pwa" / "home-chat-redesign.js"
CORE = ROOT / "pwa" / "home-chat-redesign-core.js"
SERVICE_WORKER = ROOT / "pwa" / "sw.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_visualization_adapter_is_presentation_only_and_canonical():
    source = _read(VISUAL)

    for marker in (
        "window.renderProjectStatus",
        "window.renderProjectStructure",
        "window.renderProjectActivity",
        "__vishnuLegacyProjectStatus",
        "__vishnuLegacyProjectStructure",
        "__vishnuLegacyProjectActivity",
        "authority:'presentation_only'",
        "snapshot.work_plan",
        "snapshot.p10_plan",
        "snapshot.evidence",
        "plan_deltas",
        "work_plan_history",
        "No synthetic execution events",
        "does not invent links",
    ):
        assert marker in source, marker

    assert "method:'POST'" not in source
    assert 'method:"POST"' not in source
    assert "/execute" not in source
    assert "/pause" not in source
    assert "/resume" not in source
    assert "/cancel" not in source
    assert "/approval" not in source


def test_visualizations_map_runtime_truth_not_legacy_tasks():
    source = _read(VISUAL)

    assert "WAITING_APPROVAL" in source
    assert "RECOVERY_REQUIRED" in source
    assert "UNCERTAIN" in source
    assert "WorkOrder" in source
    assert "depends on" in source
    assert "uses tool" in source
    assert "supported by" in source
    assert "Project source retained from the existing project workspace" in source
    assert "These visualizations intentionally do not convert legacy Project tasks into fake orchestration state" in source


def test_visualization_loader_preserves_existing_home_implementation():
    loader = _read(LOADER)
    core = _read(CORE)

    assert "/iphone/home-chat-redesign-core.js" in loader
    assert "/iphone/projects-work-runtime.js" in loader
    assert "/iphone/projects-work-visualization-runtime.js" in loader
    assert "script[data-canonical-project-work]" in loader
    assert "script[data-canonical-project-visualizations]" in loader
    assert "script.async=false" in loader

    # The previously-qualified Home/Chat implementation is copied byte-for-byte
    # into the core file rather than rewritten for this visualization tranche.
    assert "function keepMobileHomeClearOfDock" in core
    assert "function loadRecentProjects" in core
    assert "Projects Work adapter is intentionally loaded" in core


def test_visualizations_are_responsive_and_offline_cached():
    source = _read(VISUAL)
    sw = _read(SERVICE_WORKER)

    assert "@media(max-width:900px)" in source
    assert "@media(max-width:760px)" in source
    assert ".cv-layout" in source
    assert ".cv-status-stage" in source
    assert ".cv-graph" in source
    assert ".cv-activity-list" in source

    assert "personal-ai-iphone-v33" in sw
    assert "'/iphone/home-chat-redesign-core.js'" in sw
    assert "'/iphone/projects-work-runtime.js'" in sw
    assert "'/iphone/projects-work-visualization-runtime.js'" in sw
    assert "url.pathname.startsWith('/iphone/api/')" in sw


def test_visualization_runtime_has_valid_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed in this test environment")
    result = subprocess.run(
        [node, "--check", str(VISUAL)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
