from __future__ import annotations

from future_intelligence.work_orchestration.context_pack import ContextPackBuilder


class _Memory:
    def search(self, query, limit=20):
        return [
            {
                "id": "m1",
                "subject": "release",
                "content": "Prefer staged releases",
                "score": 0.9,
                "secret": "must-not-project",
                "metadata": {"token": "hidden", "safe": "yes"},
            },
            {
                "id": "m2",
                "subject": "verification",
                "content": "Always verify deployments",
                "score": 0.8,
            },
        ]


class _Knowledge:
    def search(self, query, limit=12):
        return [
            {
                "chunk_id": "k1",
                "document_id": "d1",
                "title": "Release guide",
                "excerpt": "Run verification after deployment.",
                "score": 4,
                "citation": {"document_id": "d1", "page_start": 2},
            }
        ]


def test_context_pack_is_bounded_sanitized_and_fingerprinted():
    pack = ContextPackBuilder(
        memory=_Memory(),
        knowledge=_Knowledge(),
        max_memory=1,
        max_knowledge=1,
    ).build(
        goal_id="g1",
        query="release verification",
        available_tools=["deploy", "verify"],
        recent_results=[{"result": "ok", "token": "drop-me"}],
    )

    assert len(pack.memory) == 1
    assert len(pack.knowledge) == 1
    assert pack.memory[0].source_id == "m1"
    assert "secret" not in pack.memory[0].metadata
    assert "token" not in pack.recent_results[0]
    assert len(pack.fingerprint) == 64
    assert "deploy" in pack.prompt_text()
