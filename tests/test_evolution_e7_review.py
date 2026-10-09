from __future__ import annotations

from dataclasses import dataclass

import pytest

from evolution.adoption import OwnerBodyAdoptionService
from evolution.code_policy import evaluate_code_change
from evolution.review import GitHubPublicReviewVerifier
from evolution.runtime_config import CodeBodyRuntimeConfig


@dataclass
class _Response:
    status_code: int
    payload: object

    def json(self):
        return self.payload


def test_review_verifier_rejects_wrong_repository_without_network(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("network must not be used for a wrong-repository review")

    monkeypatch.setattr("evolution.review.requests.get", unexpected)
    verifier = GitHubPublicReviewVerifier(repository="vaishnavsawant1994-stack/vishnu")
    result = verifier.verify(
        "https://github.com/example/other/pull/7",
        revision="abc123",
    )
    assert result.verified is False
    assert result.approved is False
    assert result.state == "wrong_repository"


def test_review_verifier_requires_exact_head_revision(monkeypatch):
    def fake_get(url, **_kwargs):
        assert url.endswith("/pulls/7")
        return _Response(200, {"state": "open", "head": {"sha": "different-sha"}})

    monkeypatch.setattr("evolution.review.requests.get", fake_get)
    verifier = GitHubPublicReviewVerifier(repository="vaishnavsawant1994-stack/vishnu")
    result = verifier.verify(
        "https://github.com/vaishnavsawant1994-stack/vishnu/pull/7",
        revision="verified-sha",
    )
    assert result.verified is False
    assert result.approved is False
    assert result.state == "revision_mismatch"


def test_review_verifier_uses_latest_review_state_per_reviewer(monkeypatch):
    responses = iter(
        (
            _Response(200, {"state": "open", "head": {"sha": "verified-sha"}}),
            _Response(
                200,
                [
                    {"state": "APPROVED", "user": {"login": "reviewer"}},
                    {"state": "CHANGES_REQUESTED", "user": {"login": "reviewer"}},
                ],
            ),
        )
    )
    monkeypatch.setattr("evolution.review.requests.get", lambda *_args, **_kwargs: next(responses))
    verifier = GitHubPublicReviewVerifier(repository="vaishnavsawant1994-stack/vishnu")
    result = verifier.verify(
        "https://github.com/vaishnavsawant1994-stack/vishnu/pull/7",
        revision="verified-sha",
    )
    assert result.verified is True
    assert result.approved is False
    assert result.reviewer is None


def test_review_verifier_accepts_current_approval_for_exact_revision(monkeypatch):
    responses = iter(
        (
            _Response(200, {"state": "open", "head": {"sha": "verified-sha"}}),
            _Response(200, [{"state": "APPROVED", "user": {"login": "human-reviewer"}}]),
        )
    )
    monkeypatch.setattr("evolution.review.requests.get", lambda *_args, **_kwargs: next(responses))
    verifier = GitHubPublicReviewVerifier(repository="vaishnavsawant1994-stack/vishnu")
    result = verifier.verify(
        "https://github.com/vaishnavsawant1994-stack/vishnu/pull/7",
        revision="verified-sha",
    )
    assert result.verified is True
    assert result.approved is True
    assert result.reviewer == "human-reviewer"


def test_only_canonical_owner_can_approve_body_adoption():
    service = object.__new__(OwnerBodyAdoptionService)
    with pytest.raises(PermissionError, match="canonical owner"):
        service.approve("candidate", owner_id="agent", reason="self approve")


@pytest.mark.parametrize(
    "path",
    (
        "evolution/code_policy.py",
        "evolution/verification.py",
        "evidence/store.py",
        "identity/store.py",
        "future_intelligence/work_orchestration/repository.py",
        "core/permissions.py",
        "agent/durable_executor.py",
        "tools/builtins.py",
        ".github/workflows/ci.yml",
        "tests/test_evolution_e7_policy.py",
    ),
)
def test_code_policy_protects_self_governance_surfaces(path):
    decision = evaluate_code_change((path,))
    assert decision.allowed is False
    assert path in decision.protected_paths


def test_code_policy_still_allows_ordinary_product_or_planner_work():
    decision = evaluate_code_change(("agent/planner.py", "ui/index.html"))
    assert decision.allowed is True
    assert decision.protected_paths == ()


def test_code_body_runtime_is_disabled_without_explicit_repository_root(monkeypatch, tmp_path):
    monkeypatch.delenv("VISHNU_REPOSITORY_ROOT", raising=False)
    monkeypatch.delenv("VISHNU_LOCAL_CODE_VERIFICATION_ENABLED", raising=False)
    config = CodeBodyRuntimeConfig.from_environment(data_dir=tmp_path)
    assert config.repository_root is None
    assert config.local_verification_enabled is False


def test_repository_root_does_not_implicitly_enable_local_code_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("VISHNU_REPOSITORY_ROOT", str(tmp_path))
    monkeypatch.delenv("VISHNU_LOCAL_CODE_VERIFICATION_ENABLED", raising=False)
    config = CodeBodyRuntimeConfig.from_environment(data_dir=tmp_path)
    assert config.repository_root == tmp_path.resolve()
    assert config.local_verification_enabled is False
