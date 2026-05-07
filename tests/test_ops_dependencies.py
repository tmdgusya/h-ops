import sqlite3
import sys
import time
import types
import unittest

fastapi_stub = types.ModuleType("fastapi")
fastapi_stub.APIRouter = lambda *args, **kwargs: types.SimpleNamespace(
    get=lambda *a, **k: (lambda fn: fn),
    post=lambda *a, **k: (lambda fn: fn),
    patch=lambda *a, **k: (lambda fn: fn),
)
fastapi_stub.HTTPException = type("HTTPException", (Exception,), {})
fastapi_stub.Query = lambda default, **kwargs: default
sys.modules.setdefault("fastapi", fastapi_stub)

pydantic_stub = types.ModuleType("pydantic")
pydantic_stub.BaseModel = object
pydantic_stub.Field = lambda default, **kwargs: default
sys.modules.setdefault("pydantic", pydantic_stub)

kanban_db_stub = types.SimpleNamespace()
hermes_cli_stub = types.ModuleType("hermes_cli")
hermes_cli_stub.kanban_db = kanban_db_stub
sys.modules.setdefault("hermes_cli", hermes_cli_stub)

profiles_stub = types.ModuleType("hermes_cli.profiles")
sys.modules.setdefault("hermes_cli.profiles", profiles_stub)

from dashboard import plugin_api


def _connect():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            status TEXT,
            assignee TEXT,
            priority INTEGER DEFAULT 0,
            created_at INTEGER,
            last_heartbeat_at INTEGER,
            current_run_id INTEGER,
            skills TEXT,
            result TEXT,
            last_spawn_error TEXT
        );
        CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            profile TEXT,
            status TEXT,
            worker_pid INTEGER,
            last_heartbeat_at INTEGER,
            started_at INTEGER,
            ended_at INTEGER,
            outcome TEXT,
            summary TEXT,
            metadata TEXT,
            error TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            run_id INTEGER,
            kind TEXT,
            payload TEXT,
            created_at INTEGER
        );
        """
    )
    return conn


def _insert_task(conn, task_id, title, status, assignee, heartbeat=None):
    now = int(time.time())
    conn.execute(
        "INSERT INTO tasks (id, title, body, status, assignee, created_at, last_heartbeat_at, skills) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, title, title + " body", status, assignee, now - 60, heartbeat, "[]"),
    )


class OpsDependencyReadModelTests(unittest.TestCase):
    def setUp(self):
        plugin_api.kanban_db.known_assignees = lambda conn: [{"name": "backend"}, {"name": "frontend"}, {"name": "reviewer"}]
        plugin_api.kanban_db.worker_log_path = lambda task_id: types.SimpleNamespace(exists=lambda: False, stat=lambda: types.SimpleNamespace(st_size=0), __str__=lambda self: "/tmp/none.log")
        plugin_api.kanban_db.read_worker_log = lambda task_id, tail_bytes=4000: None

    def test_dependency_summary_reports_waiting_parent_and_unlock_targets(self):
        conn = _connect()
        _insert_task(conn, "parent", "Backend API", "running", "backend")
        _insert_task(conn, "current", "Frontend UI", "todo", "frontend")
        _insert_task(conn, "child", "Review UI", "todo", "reviewer")
        conn.execute("INSERT INTO task_links (parent_id, child_id) VALUES ('parent', 'current')")
        conn.execute("INSERT INTO task_links (parent_id, child_id) VALUES ('current', 'child')")

        summary = plugin_api._dependency_summary(conn, "current")

        self.assertEqual(summary["state"], "waiting")
        self.assertEqual(summary["parent_count"], 1)
        self.assertEqual(summary["parents_done"], 0)
        self.assertEqual(summary["parents_blocking"], 1)
        self.assertEqual(summary["child_count"], 1)
        self.assertEqual(summary["next_assignees"], ["reviewer"])
        self.assertIn("backend", summary["label"].lower())
        self.assertEqual(summary["blocked_by"][0]["id"], "parent")
        self.assertEqual(summary["unlocks"][0]["id"], "child")

    def test_task_ops_card_includes_dependency_summary(self):
        conn = _connect()
        _insert_task(conn, "parent", "Backend API", "done", "backend")
        _insert_task(conn, "current", "Frontend UI", "ready", "frontend")
        conn.execute("INSERT INTO task_links (parent_id, child_id) VALUES ('parent', 'current')")
        row = conn.execute("SELECT * FROM tasks WHERE id = 'current'").fetchone()

        card = plugin_api._task_ops_card(conn, row)

        self.assertIn("dependency_summary", card)
        self.assertEqual(card["dependency_summary"]["parent_count"], 1)
        self.assertEqual(card["dependency_summary"]["parents_done"], 1)

    def test_agents_merge_profile_metadata_and_availability(self):
        conn = _connect()
        now = int(time.time())
        _insert_task(conn, "queued", "Ready work", "ready", "backend")
        _insert_task(conn, "stale", "Stale worker", "running", "frontend", heartbeat=now - 900)
        _insert_task(conn, "legacy", "Missing profile", "blocked", "ghost")

        ProfileInfo = types.SimpleNamespace
        profiles_stub.list_profiles = lambda: [
            ProfileInfo(name="backend", path="/profiles/backend", gateway_running=True, model="claude", provider="anthropic", has_env=True, skill_count=7, alias_path="/usr/local/bin/hermes-backend"),
            ProfileInfo(name="frontend", path="/profiles/frontend", gateway_running=False, model="gpt", provider="openai", has_env=True, skill_count=5, alias_path=None),
            ProfileInfo(name="reviewer", path="/profiles/reviewer", gateway_running=False, model=None, provider=None, has_env=False, skill_count=0, alias_path=None),
            ProfileInfo(name="designer", path="/profiles/designer", gateway_running=False, model="glm", provider="zai", has_env=True, skill_count=97, alias_path=None),
        ]

        agents = {agent["name"]: agent for agent in plugin_api._agents(conn)}

        self.assertTrue(agents["backend"]["on_disk"])
        self.assertEqual(agents["backend"]["availability"], "queued")
        self.assertEqual(agents["backend"]["skill_count"], 7)
        self.assertEqual(agents["frontend"]["availability"], "stale")
        self.assertEqual(agents["frontend"]["stale_running_count"], 1)
        self.assertEqual(agents["reviewer"]["availability"], "offline")
        self.assertEqual(agents["designer"]["availability"], "stopped")
        self.assertEqual(agents["designer"]["availability_label"], "profile stopped")
        self.assertEqual(agents["ghost"]["availability"], "unconfigured")

    def test_workflow_graph_returns_nodes_and_edges(self):
        conn = _connect()
        _insert_task(conn, "a", "Backend", "done", "backend")
        _insert_task(conn, "b", "Frontend", "todo", "frontend")
        conn.execute("INSERT INTO task_links (parent_id, child_id) VALUES ('a', 'b')")

        graph = plugin_api._workflow_graph(conn, limit=50)

        self.assertEqual({node["id"] for node in graph["nodes"]}, {"a", "b"})
        self.assertEqual(graph["edges"], [{"parent_id": "a", "child_id": "b", "state": "unlocked"}])


if __name__ == "__main__":
    unittest.main()
