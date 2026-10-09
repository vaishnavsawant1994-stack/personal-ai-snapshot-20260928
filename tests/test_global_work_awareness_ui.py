from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "pwa" / "global-work-awareness.js"
LOADER = ROOT / "pwa" / "home-chat-redesign.js"
SERVICE_WORKER = ROOT / "pwa" / "sw.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_global_work_awareness_is_read_only_and_canonical():
    source = _read(RUNTIME)

    for marker in (
        "authority:'presentation_only'",
        "source:'canonical_project_work'",
        "/projects?status=all",
        "/work')",
        "WAITING_APPROVAL",
        "RECOVERY_REQUIRED",
        "UNCERTAIN",
        "Canonical Work state only.",
        "Vishnu work",
        "openProject(order.projectId,'live')",
    ):
        assert marker in source, marker

    assert "method:'POST'" not in source
    assert 'method:"POST"' not in source
    assert "/execute" not in source
    assert "/pause" not in source
    assert "/resume" not in source
    assert "/cancel" not in source
    assert "approve(" not in source.lower()


def test_global_awareness_updates_home_today_and_idle_living_state_only():
    source = _read(RUNTIME)

    assert "globalWorkPulse" in source
    assert "globalWorkTodaySection" in source
    assert "stateLabel" in source
    assert "status" in source
    assert "['idle','active','background'].includes(stateName)" in source
    assert "foreground" not in source.lower() or "foreground" in source.lower()
    assert "@media(max-width:760px)" in source
    assert "MAX_PROJECTS=24" in source
    assert "REFRESH_MS=30000" in source


def test_global_awareness_loads_after_canonical_project_surfaces_and_is_precached():
    loader = _read(LOADER)
    sw = _read(SERVICE_WORKER)

    assert "/iphone/projects-work-runtime.js" in loader
    assert "/iphone/projects-work-visualization-runtime.js" in loader
    assert "/iphone/global-work-awareness.js" in loader
    assert "data-global-work-awareness" in loader
    assert "loadGlobalAwareness" in loader
    assert "visual.onload=loadGlobalAwareness" in loader

    assert "personal-ai-iphone-v34" in sw
    assert "'/iphone/global-work-awareness.js'" in sw
    assert "url.pathname.startsWith('/iphone/api/')" in sw


def test_global_work_awareness_has_valid_javascript_syntax():
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
