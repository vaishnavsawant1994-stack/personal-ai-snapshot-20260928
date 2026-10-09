import sqlite3

from future_intelligence.work_orchestration.migrations import migrate_work_schema


def _schema(conn: sqlite3.Connection, table: str):
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]


def test_work_migration_is_additive_idempotent_and_preserves_legacy_p10():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE p10_goals (id TEXT PRIMARY KEY, goal_json TEXT NOT NULL)")
    conn.execute("CREATE TABLE p10_plans (id TEXT PRIMARY KEY, plan_json TEXT NOT NULL)")
    conn.execute("INSERT INTO p10_goals VALUES ('g1', '{\"sentinel\":1}')")
    conn.execute("INSERT INTO p10_plans VALUES ('p1', '{\"sentinel\":2}')")
    conn.commit()

    legacy_goal_schema = _schema(conn, "p10_goals")
    legacy_plan_schema = _schema(conn, "p10_plans")
    legacy_goals = conn.execute("SELECT * FROM p10_goals").fetchall()
    legacy_plans = conn.execute("SELECT * FROM p10_plans").fetchall()

    assert migrate_work_schema(conn) == 2
    assert migrate_work_schema(conn) == 2

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {
        "work_schema_migrations",
        "work_goals",
        "work_plans",
        "work_orders",
        "work_order_dependencies",
        "plan_reviews",
        "plan_deltas",
    }.issubset(tables)
    assert _schema(conn, "p10_goals") == legacy_goal_schema
    assert _schema(conn, "p10_plans") == legacy_plan_schema
    assert conn.execute("SELECT * FROM p10_goals").fetchall() == legacy_goals
    assert conn.execute("SELECT * FROM p10_plans").fetchall() == legacy_plans
    assert conn.execute("SELECT COUNT(*) FROM work_schema_migrations").fetchone()[0] == 2

    indexes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert "idx_work_plans_source_version" in indexes
    assert "idx_work_plans_project_created" in indexes
    assert "idx_work_orders_project_status_updated" in indexes
