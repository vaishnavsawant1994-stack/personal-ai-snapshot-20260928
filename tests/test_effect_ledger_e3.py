from __future__ import annotations

from pathlib import Path

import pytest

from agent.effects import (
    EffectLedger,
    EffectLedgerMixin,
    bind_effect_context,
)
from evidence import EvidenceProvenance, EvidenceStore, VerificationState
from future_intelligence.work_orchestration.recovery import RecoveryReason


class _WorkStore:
    def __init__(self):
        self.events = []
        self.recovery = []

    def append_work_event(self, work_order_id, event_type, payload, *, attempt_id=None):
        self.events.append((work_order_id, event_type, attempt_id, dict(payload)))

    def mark_recovery_required(self, work_order_id, *, reason, attempt_id=None):
        self.recovery.append((work_order_id, reason, attempt_id))


class _Tools:
    emergency_stop = False

    @staticmethod
    def destination(_params):
        return "remote:test"


class _BaseExecutor:
    def __init__(self, *, should_fail=False, **_kwargs):
        self.should_fail = should_fail
        self.tools = _Tools()
        self.memory = type("Memory", (), {"path": None})()
        self.events = None

    @staticmethod
    def _check_cancel(_event):
        return None

    def _execute_step(self, execution_id, index, tool, params, results, **_kwargs):
        if self.should_fail:
            raise RuntimeError("response lost after dispatch")
        results[f"step{index + 1}"] = {
            "ok": True,
            "verified": True,
            "verification": {"reason": "remote id confirmed", "evidence": {"remote_id": "r-1"}},
            "result": {"remote_id": "r-1"},
        }


class _EffectHarness(EffectLedgerMixin, _BaseExecutor):
    pass


class _Tool:
    name = "send_test"


def test_verified_result_records_idempotent_receipt_and_evidence():
    store = EvidenceStore()
    ledger = EffectLedger(store)
    with bind_effect_context(work_order_id="work-1", attempt_id="attempt-1"):
        context = ledger.context(
            execution_id="exec-1",
            step_index=0,
            tool="send_test",
            destination="remote:test",
            parameters={"value": 1},
            data_classification="internal",
        )
        first_receipt, first_evidence = ledger.record_result(
            context,
            {
                "verified": True,
                "verification": {"reason": "remote id confirmed"},
                "result": {"remote_id": "r-1"},
            },
        )
        second_receipt, second_evidence = ledger.record_result(
            context,
            {
                "verified": True,
                "verification": {"reason": "remote id confirmed"},
                "result": {"remote_id": "r-1"},
            },
        )

    assert first_receipt.id == second_receipt.id
    assert first_evidence.id == second_evidence.id
    assert len(store.list_receipts(execution_id="exec-1")) == 1
    evidence = store.list_evidence(work_order_id="work-1")
    assert len(evidence) == 1
    assert evidence[0].provenance is EvidenceProvenance.TOOL_VERIFIED
    assert evidence[0].verification_state is VerificationState.VERIFIED
    assert evidence[0].worker_run_id == "attempt-1"


def test_unknown_dispatch_records_recovery_evidence_and_marks_work():
    store = EvidenceStore()
    work = _WorkStore()
    ledger = EffectLedger(store, work_store=work)
    with bind_effect_context(work_order_id="work-2", attempt_id="attempt-2", approval_id="approval-1"):
        context = ledger.context(
            execution_id="exec-2",
            step_index=0,
            tool="send_test",
            destination="remote:test",
            parameters={"value": 2},
            data_classification="sensitive",
        )
        receipt, evidence = ledger.outcome_unknown(context, RuntimeError("lost response"))

    assert receipt.verified is False
    assert receipt.details["outcome_unknown"] is True
    assert evidence.source_type == "recovery_event"
    assert evidence.verification_state is VerificationState.UNVERIFIED
    assert work.recovery == [("work-2", RecoveryReason.UNKNOWN_EFFECT, "attempt-2")]
    assert any(event[1] == "effect.recovery_required" for event in work.events)


def test_effect_mixin_wraps_existing_executor_without_replacing_dispatch_logic():
    store = EvidenceStore()
    work = _WorkStore()
    ledger = EffectLedger(store, work_store=work)
    executor = _EffectHarness(effect_ledger=ledger)
    results = {}

    with bind_effect_context(work_order_id="work-3", attempt_id="attempt-3"):
        executor._execute_step(
            "exec-3",
            0,
            _Tool(),
            {"value": 3},
            results,
            sensitivity="internal",
        )

    assert results["step1"]["verified"] is True
    assert len(store.list_receipts(execution_id="exec-3")) == 1
    phases = [event[1] for event in work.events]
    assert phases[:4] == [
        "effect.prepared",
        "effect.authorized",
        "effect.dispatching",
        "effect.dispatched",
    ]
    assert "effect.verified" in phases


def test_effect_mixin_treats_post_boundary_exception_as_unknown_not_failed():
    store = EvidenceStore()
    work = _WorkStore()
    ledger = EffectLedger(store, work_store=work)
    executor = _EffectHarness(effect_ledger=ledger, should_fail=True)

    with bind_effect_context(work_order_id="work-4", attempt_id="attempt-4"):
        with pytest.raises(RuntimeError, match="response lost"):
            executor._execute_step(
                "exec-4",
                0,
                _Tool(),
                {"value": 4},
                {},
                sensitivity="internal",
            )

    receipts = store.list_receipts(execution_id="exec-4")
    assert len(receipts) == 1
    assert receipts[0].operation == "tool_dispatch_unknown"
    assert receipts[0].verified is False
    assert work.recovery == [("work-4", RecoveryReason.UNKNOWN_EFFECT, "attempt-4")]
