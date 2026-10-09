from __future__ import annotations

from typing import Any

from recovery.visibility_projection import ExecutionRecoveryProjection

from .attention import WorkAttentionService


class RecoveryAwareWorkAttentionService(WorkAttentionService):
    """Adds owner-bound W7 recovery context to the read-only Attention projection.

    The service never retries, compensates, resolves, or mutates recovery state.
    RecoveryAuthority remains the sole W7 authority. A recovery identifier is only
    exposed after the canonical recovery visibility projection validates the
    owner/device/session binding.
    """

    @staticmethod
    def _safe_actions(view: dict[str, Any]) -> list[str]:
        owner_status = str(view.get("owner_status") or "").upper()
        if owner_status == "VERIFIED_SUCCESS":
            return ["refresh_work_state"]
        if owner_status in {"FAILED", "CANCELLED", "ABANDONED_BY_OWNER"}:
            return ["inspect_failure", "decide_replan"]
        if owner_status == "COMPENSATION_PENDING":
            return ["inspect_compensation", "review_required_governance"]
        return ["inspect_remote_state", "reconcile_before_retry"]

    def _recovery_detail(
        self,
        execution_id: str | None,
        *,
        owner_id: str,
        device_id: str | None,
        session_id: str | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if not execution_id or not device_id or not session_id:
            return None, None
        autonomy = self.work_service._autonomy()
        operations = getattr(autonomy, "operations", None)
        if operations is None:
            return None, None
        delegation = getattr(operations, "_delegation", None)
        if not callable(delegation):
            return None, None
        try:
            operation = delegation(str(execution_id))
        except Exception:
            return None, None
        if not operation or str(operation.get("owner_id") or "") != str(owner_id):
            return None, None
        if operation.get("device_id") not in (None, device_id):
            return None, None
        if operation.get("session_id") not in (None, session_id):
            return None, None
        transaction_id = operation.get("recovery_transaction_id")
        if not transaction_id:
            discover = getattr(operations, "_discover_recovery_transaction", None)
            if callable(discover) and str(operation.get("status") or "").lower() == "recovery_required":
                try:
                    transaction_id = discover(str(execution_id))
                except Exception:
                    transaction_id = None
        if not transaction_id:
            return None, None
        try:
            authority = self.runtime["tools"].ensure_recovery_authority()
        except (KeyError, RuntimeError, AttributeError):
            return None, None
        view = ExecutionRecoveryProjection(authority).detail(
            str(transaction_id),
            owner_id=owner_id,
            device_id=device_id,
            session_id=session_id,
        )
        if view is None:
            return None, None
        return str(transaction_id), view

    def summary(
        self,
        *,
        owner_id: str = "owner",
        device_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        snapshot = super().summary(
            owner_id=owner_id,
            device_id=device_id,
            session_id=session_id,
            limit=limit,
        )
        for item in snapshot.get("items") or []:
            if item.get("kind") not in {"uncertain_effect", "recovery_required"}:
                continue
            transaction_id, view = self._recovery_detail(
                item.get("execution_id"),
                owner_id=owner_id,
                device_id=device_id,
                session_id=session_id,
            )
            if not transaction_id or view is None:
                item["recovery_context_available"] = False
                # Never expose a guessed recovery identifier from a P10 operation id.
                item["recovery_id"] = None
                continue
            item.update(
                {
                    "recovery_context_available": True,
                    "recovery_id": transaction_id,
                    "recovery_state": view.get("recovery_state"),
                    "last_known_state": view.get("owner_status"),
                    "verified_success": bool(view.get("verified_success")),
                    "verification_required_for_success": bool(
                        view.get("verification_required_for_success")
                    ),
                    "safe_next_actions": self._safe_actions(view),
                    "recovery_detail_api": f"/iphone/api/execution-recovery/{transaction_id}",
                }
            )
        return snapshot
