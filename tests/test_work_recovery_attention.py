from types import SimpleNamespace

from future_intelligence.work_orchestration.attention import WorkAttentionService
from future_intelligence.work_orchestration.recovery_attention import RecoveryAwareWorkAttentionService


class _Authority:
    def transaction_binding(self, transaction_id):
        assert transaction_id == "tx-1"
        return {
            "owner_id": "owner",
            "device_id": "device-1",
            "session_id": "session-1",
        }

    def owner_view(self, transaction_id):
        assert transaction_id == "tx-1"
        return {
            "transaction_id": "tx-1",
            "transaction_state": "executing",
            "recovery_state": "recovery_review_required",
            "uncertain": True,
            "verified": False,
        }


class _Tools:
    def ensure_recovery_authority(self):
        return _Authority()


class _Operations:
    def _delegation(self, operation_id):
        assert operation_id == "op-1"
        return {
            "operation_id": "op-1",
            "owner_id": "owner",
            "device_id": "device-1",
            "session_id": "session-1",
            "status": "recovery_required",
            "recovery_transaction_id": "tx-1",
        }


class _WorkService:
    def _autonomy(self):
        return SimpleNamespace(operations=_Operations())


def _base_snapshot():
    return {
        "authority": "read_only_projection",
        "decision_authorities": {"recovery": "recovery_authority"},
        "counts": {"total": 1, "recovery": 1},
        "items": [{
            "id": "attn-1",
            "kind": "uncertain_effect",
            "severity": "critical",
            "execution_id": "op-1",
            "recovery_id": "op-1",
            "project_id": "project-1",
            "work_order_id": "wo-1",
        }],
    }


def test_recovery_attention_exposes_only_owner_bound_canonical_transaction(monkeypatch):
    monkeypatch.setattr(WorkAttentionService, "summary", lambda self, **_kwargs: _base_snapshot())
    service = RecoveryAwareWorkAttentionService.__new__(RecoveryAwareWorkAttentionService)
    service.runtime = {"tools": _Tools()}
    service.work_service = _WorkService()

    result = service.summary(
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
    )
    item = result["items"][0]
    assert item["recovery_context_available"] is True
    assert item["recovery_id"] == "tx-1"
    assert item["recovery_state"] == "recovery_review_required"
    assert item["last_known_state"] == "UNVERIFIED_OR_RECOVERY_REQUIRED"
    assert item["verified_success"] is False
    assert item["verification_required_for_success"] is True
    assert item["safe_next_actions"] == ["inspect_remote_state", "reconcile_before_retry"]
    assert item["recovery_detail_api"] == "/iphone/api/execution-recovery/tx-1"


def test_recovery_attention_fails_closed_on_device_binding_mismatch(monkeypatch):
    monkeypatch.setattr(WorkAttentionService, "summary", lambda self, **_kwargs: _base_snapshot())
    service = RecoveryAwareWorkAttentionService.__new__(RecoveryAwareWorkAttentionService)
    service.runtime = {"tools": _Tools()}
    service.work_service = _WorkService()

    result = service.summary(
        owner_id="owner",
        device_id="other-device",
        session_id="session-1",
    )
    item = result["items"][0]
    assert item["recovery_context_available"] is False
    assert item["recovery_id"] is None
    assert "recovery_detail_api" not in item


def test_recovery_attention_creates_no_retry_or_compensation_authority():
    forbidden = {
        "retry",
        "retry_decision",
        "compensate",
        "authorize_compensation",
        "recover",
        "resolve",
    }
    assert forbidden.isdisjoint(set(dir(RecoveryAwareWorkAttentionService)))
