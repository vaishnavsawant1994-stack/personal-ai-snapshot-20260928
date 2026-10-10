from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from continuity.model_handoff import public_handoff
from models.contracts import HandoffContext


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class IntelligenceDurabilityMixin:
    """Additive persistence for routing assignments and model handoff audit state."""

    def save_intelligence_assignment(
        self,
        work_order_id: str,
        *,
        worker_id: str,
        routing_policy: str,
        required_capabilities=(),
        preferred_capabilities=(),
        parallelizable: bool = True,
        deliberation_mode: str = "single",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        order_id = str(work_order_id or "").strip()
        worker = str(worker_id or "").strip()
        policy = str(routing_policy or "").strip()
        if not order_id or not worker or not policy:
            raise ValueError("work_order_id, worker_id and routing_policy are required")
        required = tuple(dict.fromkeys(str(item).strip() for item in required_capabilities if str(item).strip()))
        preferred = tuple(dict.fromkeys(str(item).strip() for item in preferred_capabilities if str(item).strip()))
        mode = str(deliberation_mode or "single").strip()
        if mode not in {"single", "parallel_compare", "critic", "judge", "synthesize", "consensus"}:
            raise ValueError("unsupported deliberation mode")
        payload = {
            "work_order_id": order_id,
            "worker_id": worker,
            "routing_policy": policy,
            "required_model_capabilities": list(required),
            "preferred_model_capabilities": list(preferred),
            "parallelizable": bool(parallelizable),
            "deliberation_mode": mode,
            "metadata": dict(metadata or {}),
            "model_is_authority": False,
        }
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO work_intelligence_assignments(
                    work_order_id, worker_id, routing_policy,
                    required_capabilities_json, preferred_capabilities_json,
                    parallelizable, deliberation_mode, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_order_id) DO UPDATE SET
                    worker_id=excluded.worker_id,
                    routing_policy=excluded.routing_policy,
                    required_capabilities_json=excluded.required_capabilities_json,
                    preferred_capabilities_json=excluded.preferred_capabilities_json,
                    parallelizable=excluded.parallelizable,
                    deliberation_mode=excluded.deliberation_mode,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    order_id, worker, policy, _json(list(required)), _json(list(preferred)),
                    int(bool(parallelizable)), mode, _json(dict(metadata or {})), now,
                ),
            )
        return payload

    def get_intelligence_assignment(self, work_order_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM work_intelligence_assignments WHERE work_order_id = ?",
            (str(work_order_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "work_order_id": str(row["work_order_id"]),
            "worker_id": str(row["worker_id"]),
            "routing_policy": str(row["routing_policy"]),
            "required_model_capabilities": json.loads(row["required_capabilities_json"]),
            "preferred_model_capabilities": json.loads(row["preferred_capabilities_json"]),
            "parallelizable": bool(row["parallelizable"]),
            "deliberation_mode": str(row["deliberation_mode"]),
            "metadata": json.loads(row["metadata_json"]),
            "model_is_authority": False,
            "updated_at": str(row["updated_at"]),
        }

    def record_model_handoff(
        self,
        work_order_id: str,
        handoff: HandoffContext,
        *,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        order_id = str(work_order_id or "").strip()
        if not order_id:
            raise ValueError("work_order_id is required")
        payload = public_handoff(handoff)
        handoff_id = f"wmh_{uuid4().hex}"
        created_at = _now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO work_model_handoffs(
                    id, work_order_id, attempt_id, execution_id, agent_id,
                    from_provider, from_model, to_provider, to_model,
                    reason, public_payload_json, checkpoint_reference, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff_id, order_id, attempt_id, handoff.execution_id, handoff.agent_id,
                    handoff.previous_provider, handoff.previous_model,
                    handoff.next_provider, handoff.next_model,
                    handoff.handoff_reason, _json(payload), handoff.checkpoint_reference, created_at,
                ),
            )
            if hasattr(self, "_append_work_event_locked"):
                self._append_work_event_locked(
                    order_id,
                    "model.handoff",
                    {
                        "handoff_id": handoff_id,
                        "from_provider": handoff.previous_provider,
                        "from_model": handoff.previous_model,
                        "to_provider": handoff.next_provider,
                        "to_model": handoff.next_model,
                        "reason": handoff.handoff_reason,
                        "model_is_authority": False,
                    },
                    attempt_id=attempt_id,
                    created_at=created_at,
                )
        return {"id": handoff_id, "created_at": created_at, **payload}

    def list_model_handoffs(self, work_order_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, attempt_id, public_payload_json, created_at
            FROM work_model_handoffs
            WHERE work_order_id = ?
            ORDER BY created_at, id
            """,
            (str(work_order_id),),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "attempt_id": row["attempt_id"],
                "created_at": str(row["created_at"]),
                **json.loads(row["public_payload_json"]),
            }
            for row in rows
        ]
