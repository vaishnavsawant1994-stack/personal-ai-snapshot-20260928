from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "architecture" / "GLOBAL_WORK_AWARENESS_IMPLEMENTATION_PROMPT.md"


def test_global_work_prompt_preserves_authority_and_release_invariants():
    source = DOC.read_text(encoding="utf-8")
    for marker in (
        "canonical Project Work -> owner-scoped read-only projection -> Home / Today / living status",
        "GET /iphone/api/work/summary",
        "never execute, approve, retry, recover, pause, resume, cancel, verify, or mutate anything",
        "openProject(projectId, 'live')",
        "foreground thinking state is not overwritten",
        "zero non-GET requests",
        "P10 adversarial/durability and soak",
        "merged into `main` only after qualification",
    ):
        assert marker in source, marker
