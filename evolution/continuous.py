from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from evidence.ingestion import EvidenceIngestor, EvidenceSourceType, IngestionRecord
from evidence.sources.feedback import feedback_record
from evidence.sources.recovery import recovery_record
from evidence.sources.security import security_record
from evidence.sources.work_experience import work_experience_record

from .models import EvolutionMode


@dataclass(frozen=True)
class ContinuousEvolutionStatus:
    enabled: bool
    running: bool
    interval_seconds: int
    cycles: int
    last_scanned: int
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ContinuousEvolutionRuntime:
    """Evidence adapters plus a bounded recommendation-only evolution cadence.

    This runtime owns no approval, handoff, merge, deploy or Body-activation
    authority. Its strongest action is creating/redacting canonical Evidence and
    asking E5 EvolutionService to synthesize/curate read-only candidates.
    """

    MIN_INTERVAL = 3600
    MAX_INTERVAL = 7 * 24 * 3600

    def __init__(self, *, events, ingestor: EvidenceIngestor, evolution, preferences=None) -> None:
        self.events = events
        self.ingestor = ingestor
        self.evolution = evolution
        self.preferences = preferences
        configured = 24 * 3600
        if preferences is not None:
            try:
                configured = int(preferences.get("evolution_interval_seconds", configured))
            except (TypeError, ValueError):
                configured = 24 * 3600
        self.interval_seconds = max(self.MIN_INTERVAL, min(configured, self.MAX_INTERVAL))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cycles = 0
        self._last_scanned = 0
        self._last_error: str | None = None
        self._subscriptions = []
        self._install_sources()

    @property
    def enabled(self) -> bool:
        if self.evolution.mode is EvolutionMode.OFF:
            return False
        if self.preferences is None:
            return True
        return bool(self.preferences.get("continuous_evolution_enabled", True))

    def _subscribe(self, event: str, callback) -> None:
        self._subscriptions.append(self.events.subscribe(event, callback))

    def _safe_ingest(self, record: IngestionRecord) -> None:
        try:
            item = self.ingestor.ingest(record, actor="continuous_evidence_runtime")
            self.events.emit(
                "evidence.ingested",
                evidence_id=item.id,
                source_type=item.source_type,
                work_order_id=item.work_order_id,
            )
        except Exception as exc:
            self.events.emit("evidence.ingestion_failed", error_type=type(exc).__name__)

    @staticmethod
    def _event_text(event: dict[str, Any], fallback: str) -> str:
        for key in ("message", "error", "reason", "detail", "observation"):
            value = str(event.get(key) or "").strip()
            if value:
                return value[:4000]
        return fallback

    def _install_sources(self) -> None:
        self._subscribe(
            "conversation.feedback",
            lambda event: self._safe_ingest(
                feedback_record(
                    self._event_text(event, "Owner supplied feedback"),
                    correction=False,
                    project_id=event.get("project_id"),
                    work_order_id=event.get("work_order_id"),
                )
            ),
        )
        self._subscribe(
            "conversation.correction",
            lambda event: self._safe_ingest(
                feedback_record(
                    self._event_text(event, "Owner corrected Vishnu"),
                    correction=True,
                    project_id=event.get("project_id"),
                    work_order_id=event.get("work_order_id"),
                )
            ),
        )
        self._subscribe(
            "tool.unverified",
            lambda event: self._safe_ingest(
                IngestionRecord(
                    source_type=EvidenceSourceType.VERIFICATION_FAILURE,
                    source="tool_runtime",
                    subject=f"tool:{event.get('tool') or 'unknown'}",
                    observation=self._event_text(event, "Tool outcome could not be verified"),
                    work_order_id=event.get("work_order_id"),
                    tool_name=event.get("tool"),
                    confidence=0.95,
                )
            ),
        )
        for event_name in ("workflow.failed", "automation.failed"):
            self._subscribe(
                event_name,
                lambda event, event_name=event_name: self._safe_ingest(
                    work_experience_record(
                        self._event_text(event, f"{event_name} requires intervention"),
                        work_order_id=str(event.get("work_order_id") or event.get("run_id") or event.get("automation_id") or event_name),
                        project_id=event.get("project_id"),
                        worker_run_id=event.get("run_id"),
                        workflow_friction=True,
                    )
                ),
            )
        for event_name in ("workflow.recovery_required", "continuity.authority.unavailable", "effect.recovery_required"):
            self._subscribe(
                event_name,
                lambda event, event_name=event_name: self._safe_ingest(
                    recovery_record(
                        self._event_text(event, f"{event_name} occurred"),
                        source=event_name,
                        work_order_id=event.get("work_order_id"),
                        worker_run_id=event.get("run_id") or event.get("attempt_id"),
                        project_id=event.get("project_id"),
                    )
                ),
            )
        for event_name in ("identity.body_mismatch", "approval.rejected", "security.policy_denied"):
            self._subscribe(
                event_name,
                lambda event, event_name=event_name: self._safe_ingest(
                    security_record(
                        self._event_text(event, f"{event_name} occurred"),
                        source=event_name,
                        project_id=event.get("project_id"),
                        work_order_id=event.get("work_order_id"),
                    )
                ),
            )
        self._subscribe(
            "work.repeated_intervention",
            lambda event: self._safe_ingest(
                work_experience_record(
                    self._event_text(event, "Repeated owner intervention was required"),
                    work_order_id=str(event.get("work_order_id") or "unknown"),
                    project_id=event.get("project_id"),
                    worker_run_id=event.get("attempt_id"),
                    repeated_intervention=True,
                )
            ),
        )
        self._subscribe(
            "skill.assessment",
            lambda event: self._safe_ingest(
                IngestionRecord(
                    source_type=EvidenceSourceType.SKILL_ASSESSMENT,
                    source=str(event.get("source") or "skill_runtime"),
                    subject=str(event.get("skill") or "skill assessment")[:500],
                    observation=self._event_text(event, "Skill assessment recorded"),
                    project_id=event.get("project_id"),
                    work_order_id=event.get("work_order_id"),
                    confidence=float(event.get("confidence", 0.8)),
                )
            ),
        )

    def run_once(self):
        if not self.enabled:
            return None
        try:
            cycle = self.evolution.run_cycle()
            self._cycles += 1
            self._last_scanned = int(cycle.scanned)
            self._last_error = None
            self.events.emit(
                "evolution.cycle_completed",
                scanned=cycle.scanned,
                candidates=len(cycle.created_or_existing),
                mode=cycle.mode.value,
                execution_authority=False,
            )
            return cycle
        except Exception as exc:
            self._last_error = type(exc).__name__
            self.events.emit("evolution.cycle_failed", error_type=self._last_error)
            return None

    def _loop(self) -> None:
        # Do not synthesize immediately at process start; allow event ingestion to
        # accumulate and avoid surprise model/workload spikes during boot.
        while not self._stop.wait(self.interval_seconds):
            self.run_once()

    def start(self) -> bool:
        if not self.enabled or (self._thread is not None and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vishnu-evolution", daemon=True)
        self._thread.start()
        self.events.emit("evolution.continuous_started", interval_seconds=self.interval_seconds)
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None

    def status(self) -> ContinuousEvolutionStatus:
        return ContinuousEvolutionStatus(
            enabled=self.enabled,
            running=bool(self._thread and self._thread.is_alive()),
            interval_seconds=self.interval_seconds,
            cycles=self._cycles,
            last_scanned=self._last_scanned,
            last_error=self._last_error,
        )
