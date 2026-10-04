from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_semantic_typography_and_spacing_tokens_exist_on_each_product_surface():
    pwa = (ROOT / "pwa/index.html").read_text(encoding="utf-8")
    standalone = (ROOT / "personal-ai/pwa/index.html").read_text(encoding="utf-8")
    web = (ROOT / "web-companion/styles.css").read_text(encoding="utf-8")
    android = (ROOT / "android-companion/app/src/main/java/ai/personal/companion/PersonalAITheme.kt").read_text(encoding="utf-8")
    ios = (ROOT / "ios-companion/PersonalAICompanion/PersonalAITheme.swift").read_text(encoding="utf-8")
    desktop = (ROOT / "ui/design_tokens.py").read_text(encoding="utf-8")

    for name in ("display", "page", "section", "subsection", "body", "supporting", "control", "metadata", "micro"):
        assert f"--pa-type-{name}" in pwa
        assert f"--pa-type-{name}" in standalone
        assert f"--pa-type-{name}" in web
    for token in ("pageTitle", "sectionTitle", "body", "supporting", "control", "metadata"):
        assert token in android
    assert "enum Typography" in ios and ".body" in ios and ".caption" in ios
    assert "TYPE =" in desktop and "SPACE =" in desktop


def test_automated_ui_qualification_covers_module_matrix_and_companion_states():
    pwa = (ROOT / "tests/pwa_mobile_preview.mjs").read_text(encoding="utf-8")
    web = (ROOT / "tests/web_companion_responsive.mjs").read_text(encoding="utf-8")
    standalone = (ROOT / "tests/standalone_pwa_responsive.mjs").read_text(encoding="utf-8")
    doc = (ROOT / "docs/ui/DESIGN_SYSTEM.md").read_text(encoding="utf-8")
    for route in ("memory", "knowledge", "activities", "tools", "workflows", "devices", "dashboard", "settings", "owner", "system"):
        assert f'"{route}"' in pwa
    for width in ("320", "360", "375", "390", "430", "600", "768", "820", "1024", "1280", "1440", "1920", "2560"):
        assert width in pwa and width in web
    assert "prefers-reduced-motion" in pwa and "prefers-reduced-motion" in web
    assert "prefers-reduced-motion" in standalone and "Owner verification required" in standalone
    assert "200%" in pwa and "400%" in pwa
    assert "real device" in doc.lower() and "not" in doc.lower()
