from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from evidence import Evidence, EvidenceProvenance, EvidenceStore, Receipt, VerificationState
from future_intelligence.work_orchestration.recovery import RecoveryReason
from security.approvals import parameter_hash


class EffectPhase(StrEnum):
    PREPARED = "prepared"
    AUTHORIZED = "authorized"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DENIED = "denied"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class EffectBinding:
    work_order_id: str | None = None
    attempt_id: str | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    capability: str | None = None
    resource_scope: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    step_index: int
    tool: str
    destination: str
    request_hash: str
    idempotency_key: str
    data_classification: str = "internal"
    work_order_id: str | None = None
    attempt_id: str | None = None
    approval_id: str | None = None
    capability: str | None = None
    resource_scope: Mapping[str, Any] = field(default_factory=dict)


_EFFECT_BINDING: ContextVar[EffectBinding] = ContextVar(
    "vishnu_effect_binding", default=EffectBinding()
)


def current_effect_binding() -> EffectBinding:
    return _EFFECT_BINDING.get()


@contextmanager
def bind_effect_context(**values: Any):
    previous = current_effect_binding()
    binding = EffectBinding(
        work_order_id=values.get("work_order_id", previous.work_order_id),
        attempt_id=values.get("attempt_id", previous.attempt_id),
        approval_id=values.get("approval_id", previous.approval_id),
        idempotency_key=values.get("idempotency_key", previous.idempotency_key),
        capability=values.get("capability", previous.capability),
        resource_scope=values.get("resource_scope", previous.resource_scope),
    )
    token = _EFFECT_BINDING.set(binding)
    try:
        yield binding
    finally:
        _EFFECT_BINDING.reset(token)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_remote_id(result: Any) -> str | None:
    if not isinstance(result, Mapping):
        return None
    for key in ("remote_id", "message_id", "event_id", "job_id", "id"):
        value = result.get(key)
        if value is not None and str(value).strip():
            return str(value)[:500]
    return None


class EffectLedger:
    """Durable receipt/evidence recorder for the existing governed executor.

    This component is deliberately not an authorization source. It records what
    the already-authorized executor attempted and what verification proved.
    """

    def __init__(
        self,
        evidence_store: EvidenceStore | None = None,
        *,
        db_path: str | Path | None = None,
        events=None,
        work_store=None,
    ) -> None:
        if evidence_store is not None and db_path is not None:
            raise ValueError("provide evidence_store or db_path, not both")
        self._store = evidence_store
        self._db_path = None if db_path is None else Path(db_path)
        self.events = events
        self.work_store = work_store

    def attach_work_store(self, work_store) -> None:
        self.work_store = work_store

    def context(
        self,
        *,
        execution_id: str,
        step_index: int,
        tool: str,
        destination: str,
        parameters: Mapping[str, Any],
        data_classification: str,
    ) -> ExecutionContext:
        binding = current_effect_binding()
        request_hash = parameter_hash(dict(parameters))
        idempotency_key = binding.idempotency_key or (
            f"effect:{binding.work_order_id or execution_id}:"
            f"{binding.attempt_id or execution_id}:{step_index}:{tool}:{request_hash}"
        )
        return ExecutionContext(
            execution_id=str(execution_id),
            step_index=int(step_index),
            tool=str(tool),
            destination=str(destination or "local"),
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            data_classification=str(data_classification or "internal"),
            work_order_id=binding.work_order_id,
            attempt_id=binding.attempt_id,
            approval_id=binding.approval_id,
            capability=binding.capability or str(tool),
            resource_scope=dict(binding.resource_scope),
        )

    @contextmanager
    def _open_store(self):
        if self._store is not None:
            yield self._store
            return
        if self._db_path is None:
            yield None
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with EvidenceStore(self._db_path) as store:
            yield store

    def _emit(self, event: str, **payload: Any) -> None:
        if self.events is not None:
            self.events.emit(event, **payload)

    def phase(self, context: ExecutionContext, phase: EffectPhase, **extra: Any) -> None:
        payload = {
            "execution_id": context.execution_id,
            "work_order_id": context.work_order_id,
            "attempt_id": context.attempt_id,
            "approval_id": context.approval_id,
            "tool": context.tool,
            "destination": context.destination,
            "phase": phase.value,
            **extra,
        }
        self._emit("effect.phase", **payload)
        if self.work_store is not None and context.work_order_id:
            try:
                self.work_store.append_work_event(
                    context.work_order_id,
                    f"effect.{phase.value}",
                    payload,
                    attempt_id=context.attempt_id,
                )
            except Exception:
                # Work projection/history cannot make the already-governed tool
                # path fail. The effect ledger remains observational here.
                self._emit(
                    "effect.work_event_failed",
                    execution_id=context.execution_id,
                    work_order_id=context.work_order_id,
                    phase=phase.value,
                )

    def _receipt_id(self, context: ExecutionContext, operation: str) -> str:
        return f"receipt:{_stable_hash([context.idempotency_key, operation])[:32]}"

    def _evidence_id(self, receipt_id: str, kind: str) -> str:
        return f"evidence:{_stable_hash([receipt_id, kind])[:32]}"

    def _persist(
        self,
        context: ExecutionContext,
        *,
        operation: str,
        verified: bool,
        verification_reason: str,
        result: Any = None,
        outcome_unknown: bool = False,
        error_type: str | None = None,
    ) -> tuple[Receipt | None, Evidence | None]:
        receipt_id = self._receipt_id(context, operation)
        details = {
            "work_order_id": context.work_order_id,
            "attempt_id": context.attempt_id,
            "approval_id": context.approval_id,
            "idempotency_key": context.idempotency_key,
            "capability": context.capability,
            "resource_scope": dict(context.resource_scope),
            "verification_method": "tool_registry.verify_result",
            "verification_reason": str(verification_reason or "")[:1000],
            "outcome_unknown": bool(outcome_unknown),
            "error_type": error_type,
        }
        receipt = Receipt(
            id=receipt_id,
            operation=operation,
            execution_id=context.execution_id,
            tool=context.tool,
            destination=context.destination,
            request_hash=context.request_hash,
            remote_id=_safe_remote_id(result),
            details=details,
            verified=bool(verified),
        )
        if outcome_unknown:
            observation = (
                f"Dispatch outcome for {context.tool} is unknown after {error_type or 'interruption'}; "
                "reconciliation is required before retry."
            )
            provenance = EvidenceProvenance.OBSERVED
            verification_state = VerificationState.UNVERIFIED
            confidence = 0.5
            source_type = "recovery_event"
        elif verified:
            observation = f"Tool {context.tool} outcome verified: {verification_reason or 'verified'}"
            provenance = EvidenceProvenance.TOOL_VERIFIED
            verification_state = VerificationState.VERIFIED
            confidence = 1.0
            source_type = "tool_execution"
        else:
            observation = f"Tool {context.tool} returned an unverified outcome: {verification_reason or 'verification unavailable'}"
            provenance = EvidenceProvenance.OBSERVED
            verification_state = VerificationState.UNVERIFIED
            confidence = 0.6
            source_type = "tool_execution"

        evidence = Evidence(
            id=self._evidence_id(receipt_id, source_type),
            source_type=source_type,
            source="agent.effect_ledger",
            subject=f"tool:{context.tool}",
            observation=observation,
            provenance=provenance,
            work_order_id=context.work_order_id,
            worker_run_id=context.attempt_id,
            tool_name=context.tool,
            artifact_ref=receipt.id,
            verification_state=verification_state,
            verification_reason=str(verification_reason or "")[:1000] or None,
            confidence=confidence,
            data_classification=context.data_classification,
        )

        with self._open_store() as store:
            if store is None:
                return None, None
            try:
                store.record_receipt(receipt)
            except sqlite3.IntegrityError:
                receipt = store.get_receipt(receipt.id) or receipt
            try:
                store.record_evidence(evidence)
            except sqlite3.IntegrityError:
                evidence = store.get_evidence(evidence.id) or evidence
        return receipt, evidence

    def record_result(self, context: ExecutionContext, step_result: Mapping[str, Any]) -> tuple[Receipt | None, Evidence | None]:
        verification = dict(step_result.get("verification") or {})
        verified = bool(step_result.get("verified"))
        reason = str(verification.get("reason") or "")
        result = step_result.get("result")
        receipt, evidence = self._persist(
            context,
            operation="tool_result",
            verified=verified,
            verification_reason=reason,
            result=result,
        )
        self.phase(
            context,
            EffectPhase.VERIFIED if verified else EffectPhase.UNVERIFIED,
            receipt_id=None if receipt is None else receipt.id,
            evidence_id=None if evidence is None else evidence.id,
            verification_reason=reason,
        )
        return receipt, evidence

    def outcome_unknown(self, context: ExecutionContext, error: BaseException) -> tuple[Receipt | None, Evidence | None]:
        error_type = type(error).__name__
        self.phase(context, EffectPhase.OUTCOME_UNKNOWN, error_type=error_type)
        receipt, evidence = self._persist(
            context,
            operation="tool_dispatch_unknown",
            verified=False,
            verification_reason="outcome unknown after dispatch boundary",
            outcome_unknown=True,
            error_type=error_type,
        )
        if self.work_store is not None and context.work_order_id:
            try:
                self.work_store.mark_recovery_required(
                    context.work_order_id,
                    reason=RecoveryReason.UNKNOWN_EFFECT,
                    attempt_id=context.attempt_id,
                )
            except Exception:
                self._emit(
                    "effect.recovery_mark_failed",
                    execution_id=context.execution_id,
                    work_order_id=context.work_order_id,
                    attempt_id=context.attempt_id,
                )
        self.phase(
            context,
            EffectPhase.RECOVERY_REQUIRED,
            receipt_id=None if receipt is None else receipt.id,
            evidence_id=None if evidence is None else evidence.id,
            error_type=error_type,
        )
        return receipt, evidence


class EffectLedgerMixin:
    """Wrap the existing AgentExecutor step path with receipts and evidence."""

    def __init__(self, *args, effect_ledger: EffectLedger | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if effect_ledger is None:
            memory_path = getattr(getattr(self, "memory", None), "path", None)
            if memory_path is not None:
                effect_ledger = EffectLedger(
                    db_path=Path(memory_path).parent / "evidence.sqlite3",
                    events=getattr(self, "events", None),
                )
        self.effect_ledger = effect_ledger

    def attach_work_store(self, work_store) -> None:
        if self.effect_ledger is not None:
            self.effect_ledger.attach_work_store(work_store)

    def _execute_step(
        self,
        execution_id,
        index,
        tool,
        params,
        results,
        *,
        cancel_event=None,
        sensitivity="internal",
    ):
        ledger = self.effect_ledger
        if ledger is None:
            return super()._execute_step(
                execution_id,
                index,
                tool,
                params,
                results,
                cancel_event=cancel_event,
                sensitivity=sensitivity,
            )

        self._check_cancel(cancel_event)
        destination = self.tools.destination(params)
        context = ledger.context(
            execution_id=execution_id,
            step_index=index,
            tool=tool.name,
            destination=destination,
            parameters=params,
            data_classification=sensitivity,
        )
        ledger.phase(context, EffectPhase.PREPARED)
        if getattr(self.tools, "emergency_stop", False):
            ledger.phase(context, EffectPhase.DENIED, reason="emergency_stop_active")
            raise PermissionError("owner emergency stop is active")
        ledger.phase(context, EffectPhase.AUTHORIZED)
        ledger.phase(context, EffectPhase.DISPATCHING)
        try:
            value = super()._execute_step(
                execution_id,
                index,
                tool,
                params,
                results,
                cancel_event=cancel_event,
                sensitivity=sensitivity,
            )
        except BaseException as exc:
            # We crossed the dispatch boundary. A raised handler, lost response,
            # verification exception, or cancellation can all hide a completed
            # external effect; never classify that as safely retryable here.
            ledger.outcome_unknown(context, exc)
            raise

        ledger.phase(context, EffectPhase.DISPATCHED)
        ledger.phase(context, EffectPhase.VERIFYING)
        step_result = results.get(f"step{index + 1}", {})
        ledger.record_result(context, step_result)
        return value
