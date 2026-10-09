from pathlib import Path


def test_project_autonomy_ui_uses_only_existing_authoritative_endpoints():
    text = Path("pwa/project-autonomy-controls.js").read_text()
    assert "/work/autonomy" in text
    assert "/advance" in text
    assert "method:'PUT'" in text
    assert "method:'POST'" in text
    assert "localStorage" not in text
    assert "sessionStorage" not in text
    assert "existing P10/P6 runtime" in text
    assert "Completion Judge" in text or "completion" in text.lower()
    assert "Emergency Stop" in text
    assert "Approval is required" in text
    assert "Recovery or remote-state reconciliation" in text


def test_project_autonomy_ui_is_loaded_after_canonical_work_and_precached():
    loader = Path("pwa/home-chat-redesign.js").read_text()
    assert loader.index("projects-work-runtime.js") < loader.index("project-autonomy-controls.js")
    assert loader.index("project-autonomy-controls.js") < loader.index("projects-work-visualization-runtime.js")
    sw = Path("pwa/sw.js").read_text()
    assert "project-autonomy-controls.js" in sw
    assert "personal-ai-iphone-v35" in sw
    assert "url.pathname.startsWith('/iphone/api/')" in sw
