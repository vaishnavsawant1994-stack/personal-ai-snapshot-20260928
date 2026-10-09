from __future__ import annotations

import pytest

from agent.effect_runtime import EffectAwareDurableAgentExecutor
from continuity import ContinuityCheckpoint, ContinuityCompatibilityError, ContinuityCompatibilityVerifier
from evolution.code_body import CodeBodyEvolutionService


def _blocked():
    raise PermissionError("host continuation authority is fenced")


def test_effect_executor_checks_host_authority_before_approval_dispatch():
    executor = object.__new__(EffectAwareDurableAgentExecutor)
    executor._continuation_authority_guard = _blocked
    with pytest.raises(PermissionError, match="fenced"):
        executor.approve("approval-id")


def test_effect_executor_checks_host_authority_before_any_tool_step():
    executor = object.__new__(EffectAwareDurableAgentExecutor)
    executor._continuation_authority_guard = _blocked
    with pytest.raises(PermissionError, match="fenced"):
        executor._execute_step()


@pytest.mark.parametrize(
    ("method", "kwargs"),
    (
        ("prepare", {"candidate_id": "candidate", "worker_id": "worker", "runtime_epoch": 1}),
        ("commit", {"candidate_id": "candidate", "message": "change"}),
        ("verify", {"candidate_id": "candidate"}),
        ("attach_review", {"candidate_id": "candidate", "review_ref": "https://example.invalid/review"}),
    ),
)
def test_code_body_mutations_check_host_authority_first(method, kwargs):
    service = object.__new__(CodeBodyEvolutionService)
    service._continuation_authority_guard = _blocked
    with pytest.raises(PermissionError, match="fenced"):
        getattr(service, method)(**kwargs)


def test_future_schema_checkpoint_is_rejected():
    checkpoint = ContinuityCheckpoint(
        id="future",
        source_host_id="source",
        authority_epoch=1,
        backup_filename="x",
        backup_sha256="a" * 64,
        backup_size=1,
        payload_sha256="b" * 64,
        data_manifest_hash="c" * 64,
        active_body_revision_id=None,
        active_body_git_revision="abc1234",
        schema_versions={"work": (999,)},
    )
    verifier = ContinuityCompatibilityVerifier({"work": (3,)})
    with pytest.raises(ContinuityCompatibilityError, match="newer than"):
        verifier.verify_checkpoint(checkpoint, running_git_revision="abc1234")
