from __future__ import annotations

from evidence import EvidenceStore, Receipt


def make_receipt(rid: str, execution_id: str, *, tool="github", verified=True):
    return Receipt(
        id=rid,
        operation="operation",
        execution_id=execution_id,
        tool=tool,
        destination="target",
        request_hash=f"hash-{rid}",
        remote_id=f"remote-{rid}",
        verified=verified,
    )


def test_list_receipts_filters_execution_tool_and_verification():
    store = EvidenceStore()
    first = store.record_receipt(make_receipt("r1", "exec-1", tool="github", verified=True))
    store.record_receipt(make_receipt("r2", "exec-1", tool="github", verified=False))
    third = store.record_receipt(make_receipt("r3", "exec-2", tool="email", verified=True))

    assert store.list_receipts(execution_id="exec-1", verified=True) == [first]
    assert store.list_receipts(tool="email") == [third]
    assert len(store.list_receipts()) == 3
