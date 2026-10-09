from __future__ import annotations

from agent.effects import EffectLedger, ExecutionContext
from evidence.ingestion import EvidenceIngestor, EvidenceStatus


class GovernedEffectLedger(EffectLedger):
    """EffectLedger with Evidence-v3 lifecycle and normalized receipt context."""

    def _persist(self, context: ExecutionContext, **kwargs):
        receipt, evidence = super()._persist(context, **kwargs)
        if receipt is None and evidence is None:
            return receipt, evidence
        with self._open_store() as store:
            if store is None:
                return receipt, evidence
            ingestor = EvidenceIngestor(store)
            if evidence is not None and ingestor.lifecycle(evidence.id) is None:
                ingestor.set_lifecycle(
                    evidence.id,
                    EvidenceStatus.ACTIVE,
                    actor="agent.effect_ledger",
                    reason="recorded by governed tool execution",
                )
            if receipt is not None:
                details = dict(receipt.details)
                ingestor.record_receipt_context(
                    receipt.id,
                    work_order_id=context.work_order_id,
                    attempt_id=context.attempt_id,
                    approval_id=context.approval_id,
                    idempotency_key=context.idempotency_key,
                    verification_method=str(details.get("verification_method") or "tool_registry.verify_result"),
                    verified_at=receipt.created_at if receipt.verified else None,
                )
        return receipt, evidence
