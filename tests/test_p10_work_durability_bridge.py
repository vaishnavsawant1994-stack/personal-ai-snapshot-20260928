import sqlite3

from future_intelligence.work_orchestration import DurableWorkStore, P10WorkBridge


def test_p10_bridge_installs_durable_work_schema_without_claiming_authority():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        bridge = P10WorkBridge(connection)

        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM work_schema_migrations")
        }
        assert 3 in versions
        assert isinstance(bridge.work, DurableWorkStore)
        assert bridge.mode == "observe_only"
        assert bridge.status()["durability_schema"] == 3
    finally:
        connection.close()
