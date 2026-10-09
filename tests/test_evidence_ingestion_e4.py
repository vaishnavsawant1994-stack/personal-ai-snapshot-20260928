from __future__ import annotations

from agent.effects import bind_effect_context
from evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceIngestor,
    EvidenceSourceType,
    EvidenceStatus,
    EvidenceStore,
)
from evidence.effect_bridge import GovernedEffectLedger
from evidence.models import Receipt
from evidence.sources import (
    feedback_record,
    recovery_record,
    security_record,
    skill_assessment_record,
    work_experience_record,
)


def test_evidence_schema_v3_is_additive_and_idempotent():
    with EvidenceStore() as store:
        versions = {
            int(row[0])
            for row in store.connection.execute("SELECT version FROM evidence_schema_migrations")
        }
        assert EVIDENCE_SCHEMA_VERSION == 3
        assert versions == {1, 2, 3}
        for table in (
            "evidence_lifecycle",
            "evidence_fingerprints",
            "evidence_ingestion_cursors",
            "evidence_ingestion_runs",
            "receipt_context",
        ):
            assert store.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()


def test_ingestion_redacts_secrets_and_deduplicates():
    with EvidenceStore() as store:
        ingestor = EvidenceIngestor(store)
        record = feedback_record(
            "The connector failed with api_key=super-secret-value and needs a clearer retry path",
            correction=True,
            work_order_id="work-1",
        )
        first = ingestor.ingest(record, actor="owner")
        second = ingestor.ingest(record, actor="owner")

        assert first.id == second.id
        assert "super-secret-value" not in first.observation
        assert "[REDACTED]" in first.observation
        assert len(store.list_evidence(work_order_id="work-1")) == 1
        lifecycle = ingestor.lifecycle(first.id)
        assert lifecycle["status"] == EvidenceStatus.ACTIVE.value


def test_failed_ingestion_run_never_advances_cursor():
    with EvidenceStore() as store:
        ingestor = EvidenceIngestor(store)
        run = ingestor.start_run(
            EvidenceSourceType.WORK_EXPERIENCE,
            partition_key="project-1",
            input_payload={"cursor": 10},
        )
        ingestor.fail_run(run, error_code="malformed_scan_output")
        assert ingestor.cursor(
            EvidenceSourceType.WORK_EXPERIENCE,
            partition_key="project-1",
        ) is None

        retry = ingestor.start_run(
            EvidenceSourceType.WORK_EXPERIENCE,
            partition_key="project-1",
            input_payload={"cursor": 10},
        )
        ingestor.complete_run(retry, cursor={"offset": 11}, output_payload={"accepted": 1})
        assert ingestor.cursor(
            EvidenceSourceType.WORK_EXPERIENCE,
            partition_key="project-1",
        ) == {"offset": 11}


def test_evidence_lifecycle_preserves_history_instead_of_deleting():
    with EvidenceStore() as store:
        ingestor = EvidenceIngestor(store)
        first = ingestor.ingest(feedback_record("First observation"), actor="owner")
        replacement = ingestor.ingest(feedback_record("Corrected observation", correction=True), actor="owner")

        ingestor.set_lifecycle(
            first.id,
            EvidenceStatus.SUPERSEDED,
            actor="owner",
            reason="owner supplied a correction",
            superseded_by_id=replacement.id,
        )

        lifecycle = ingestor.lifecycle(first.id)
        assert lifecycle["status"] == EvidenceStatus.SUPERSEDED.value
        assert lifecycle["superseded_by_id"] == replacement.id
        assert store.get_evidence(first.id) is not None
        assert [item.id for item in ingestor.list_active()] == [replacement.id]


def test_source_adapters_only_create_typed_ingestion_records():
    assert feedback_record("use a clearer message").source_type is EvidenceSourceType.USER_FEEDBACK
    assert feedback_record("that result is wrong", correction=True).source_type is EvidenceSourceType.USER_CORRECTION
    assert work_experience_record("needed owner intervention", work_order_id="w", repeated_intervention=True).source_type is EvidenceSourceType.REPEATED_INTERVENTION
    assert work_experience_record("workflow caused friction", work_order_id="w", workflow_friction=True).source_type is EvidenceSourceType.WORKFLOW_FRICTION
    assert recovery_record("worker disappeared").source_type is EvidenceSourceType.RECOVERY_EVENT
    assert security_record("permission was denied").source_type is EvidenceSourceType.SECURITY_EVENT
    assert skill_assessment_record("skill-a", "latency increased", performance_regression=True).source_type is EvidenceSourceType.PERFORMANCE_REGRESSION


def test_governed_effect_ledger_records_normalized_receipt_context(tmp_path):
    ledger = GovernedEffectLedger(db_path=tmp_path / "evidence.sqlite3")
    with bind_effect_context(
        work_order_id="work-2",
        attempt_id="attempt-2",
        approval_id="approval-2",
        idempotency_key="idem-2",
    ):
        context = ledger.context(
            execution_id="exec-2",
            step_index=0,
            tool="send_test",
            destination="remote:test",
            parameters={"message": "hello"},
            data_classification="internal",
        )
        receipt, evidence = ledger.record_result(
            context,
            {
                "verified": True,
                "verification": {"reason": "remote id confirmed"},
                "result": {"remote_id": "remote-2"},
            },
        )

    assert receipt is not None and evidence is not None
    with EvidenceStore(tmp_path / "evidence.sqlite3") as store:
        row = store.connection.execute(
            "SELECT * FROM receipt_context WHERE receipt_id = ?",
            (receipt.id,),
        ).fetchone()
        assert row["work_order_id"] == "work-2"
        assert row["attempt_id"] == "attempt-2"
        assert row["approval_id"] == "approval-2"
        assert row["idempotency_key"] == "idem-2"
        assert row["verified_at"] is not None
        lifecycle = EvidenceIngestor(store).lifecycle(evidence.id)
        assert lifecycle["status"] == EvidenceStatus.ACTIVE.value


def test_reconciliation_receipts_may_share_one_idempotency_key():
    with EvidenceStore() as store:
        ingestor = EvidenceIngestor(store)
        unknown = Receipt(
            id="receipt-unknown",
            operation="tool_dispatch_unknown",
            execution_id="exec-1",
            tool="tool",
            destination="dest",
            request_hash="hash-1",
        )
        verified = Receipt(
            id="receipt-verified",
            operation="tool_result",
            execution_id="exec-1",
            tool="tool",
            destination="dest",
            request_hash="hash-1",
            verified=True,
        )
        store.record_receipt(unknown)
        store.record_receipt(verified)
        ingestor.record_receipt_context(unknown.id, idempotency_key="same-effect")
        ingestor.record_receipt_context(verified.id, idempotency_key="same-effect", verified_at=verified.created_at)
        assert store.connection.execute(
            "SELECT COUNT(*) FROM receipt_context WHERE idempotency_key = ?",
            ("same-effect",),
        ).fetchone()[0] == 2
