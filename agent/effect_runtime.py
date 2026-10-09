from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Callable

from agent.durable_executor import DurableAgentExecutor
from agent.effects import EffectLedgerMixin, bind_effect_context
from evidence.effect_bridge import GovernedEffectLedger


_PENDING_APPROVAL_ID: ContextVar[str | None] = ContextVar(
    "vishnu_pending_effect_approval_id", default=None
)


class EffectAwareDurableAgentExecutor(EffectLedgerMixin, DurableAgentExecutor):
    """Existing durable executor plus governed Evidence-v3 observation.

    DurableAgentExecutor remains the approval/dispatch implementation. This
    class composes the effect ledger around its `_execute_step` path and may be
    bound to E8 continuation authority. Once the local host is fenced, no tool
    side effect or resumed approval may dispatch from this executor.
    """

    def __init__(self, *args, effect_ledger=None, continuation_authority_guard: Callable[[], object] | None = None, **kwargs):
        if effect_ledger is None:
            memory = kwargs.get("memory")
            memory_path = getattr(memory, "path", None)
            if memory_path is not None:
                effect_ledger = GovernedEffectLedger(
                    db_path=Path(memory_path).parent / "evidence.sqlite3",
                    events=kwargs.get("events"),
                )
        self._continuation_authority_guard = continuation_authority_guard
        super().__init__(*args, effect_ledger=effect_ledger, **kwargs)

    def attach_continuation_authority(self, guard: Callable[[], object] | None) -> None:
        self._continuation_authority_guard = guard

    def _assert_continuation_authority(self) -> None:
        if self._continuation_authority_guard is not None:
            self._continuation_authority_guard()

    def approve(self, approval_id: str, **kwargs):
        # Replaying an approval after this host was fenced must never dispatch.
        self._assert_continuation_authority()
        token = _PENDING_APPROVAL_ID.set(str(approval_id))
        try:
            return super().approve(approval_id, **kwargs)
        finally:
            _PENDING_APPROVAL_ID.reset(token)

    def _execute_step(self, *args, **kwargs):
        # This is the common side-effect boundary for ordinary and approved work.
        self._assert_continuation_authority()
        approval_id = _PENDING_APPROVAL_ID.get()
        if approval_id is None:
            return super()._execute_step(*args, **kwargs)

        # Approval applies to the resumed step only. Clear it before dispatch so
        # additional already-authorized steps in the same continuation do not
        # inherit the approval id.
        _PENDING_APPROVAL_ID.set(None)
        with bind_effect_context(approval_id=approval_id):
            return super()._execute_step(*args, **kwargs)
