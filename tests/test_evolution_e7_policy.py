from __future__ import annotations

import json
from pathlib import Path

from evolution import GuardedVerificationProvider, VerificationCheck, VerificationReport
from future_intelligence.work_orchestration import RepositoryWorkspaceSession


_BODY = {
    "body_version": 1,
    "identity": {"name": "Vishnu", "role": "personal_ai"},
    "contracts": {"work": 1},
    "mission": ["assist the owner"],
    "principles": ["review software changes"],
}


class _Repository:
    repository = "vaishnavsawant1994-stack/vishnu"

    def __init__(self, paths):
        self.paths = tuple(paths)

    def changed_paths(self, *, base_revision, working_revision):
        return self.paths

    def read_text_at(self, revision, path):
        return json.dumps(_BODY)


class _Inner:
    def __init__(self):
        self.called = False

    def verify(self, session, *, revision):
        self.called = True
        return VerificationReport(
            revision=revision,
            checks=(VerificationCheck("tests", ("pytest",), True, 0, 1, "x" * 64, "pass"),),
        )


def _session(tmp_path: Path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "vishnu-body.yaml").write_text(json.dumps(_BODY), encoding="utf-8")
    return RepositoryWorkspaceSession(
        repository="vaishnavsawant1994-stack/vishnu",
        work_order_id="work",
        attempt_id="attempt",
        base_revision="base",
        branch_ref="branch",
        local_path=tmp_path,
    )


def test_protected_diff_is_rejected_before_inner_verifier_runs(tmp_path):
    inner = _Inner()
    guarded = GuardedVerificationProvider(
        repository_provider=_Repository(("security/permissions.py", "agent/executor.py")),
        inner=inner,
    )
    report = guarded.verify(_session(tmp_path), revision="working")
    assert report.passed is False
    assert inner.called is False
    assert report.checks[0].name == "protected-code-scope"


def test_body_manifest_change_is_rejected_before_inner_verifier_runs(tmp_path):
    session = _session(tmp_path)
    changed = dict(_BODY)
    changed["mission"] = ["different authority"]
    (tmp_path / "config" / "vishnu-body.yaml").write_text(json.dumps(changed), encoding="utf-8")
    inner = _Inner()
    guarded = GuardedVerificationProvider(
        # Use an ordinary, non-protected implementation path so this test
        # specifically reaches the independent Body-manifest integrity gate.
        repository_provider=_Repository(("agent/planner.py",)),
        inner=inner,
    )
    report = guarded.verify(session, revision="working")
    assert report.passed is False
    assert inner.called is False
    assert report.checks[-1].name == "body-manifest-integrity"


def test_ordinary_diff_runs_inner_verification(tmp_path):
    inner = _Inner()
    guarded = GuardedVerificationProvider(
        repository_provider=_Repository(("agent/planner.py",)),
        inner=inner,
    )
    report = guarded.verify(_session(tmp_path), revision="working")
    assert report.passed is True
    assert inner.called is True
