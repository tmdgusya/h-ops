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

from dashboard import plugin_api


def _task(**overrides):
    base = {
        "id": "t1",
        "title": "Example",
        "status": "done",
        "assignee": "backend",
        "heartbeat_age_seconds": 172800,
        "last_heartbeat_at": int(time.time()) - 172800,
    }
    base.update(overrides)
    return base


class OpsHealthTests(unittest.TestCase):
    def test_completed_ticket_with_old_heartbeat_is_healthy_not_warning(self):
        health = plugin_api._ticket_health(
            _task(status="done", heartbeat_age_seconds=172800),
            {"status": "done", "outcome": "completed"},
            {"exists": False},
        )

        self.assertEqual(health["level"], "healthy")
        self.assertEqual(health["worker_freshness"], "not_required")
        self.assertIn("complete", health["interpretation"].lower())
        self.assertEqual(health["next_action"], "None required")

    def test_running_ticket_with_stale_heartbeat_is_critical(self):
        health = plugin_api._ticket_health(
            _task(status="running", heartbeat_age_seconds=600),
            {"status": "running"},
            {"exists": True},
        )

        self.assertEqual(health["level"], "critical")
        self.assertEqual(health["worker_freshness"], "stale")
        self.assertTrue(health["alerts"])
        self.assertIn("heartbeat", health["alerts"][0]["label"].lower())

    def test_board_health_flags_blocked_and_unassigned_ready_tickets(self):
        columns = [
            {"name": "ready", "tickets": [_task(id="ready1", status="ready", assignee=None, heartbeat_age_seconds=None)]},
            {"name": "blocked", "tickets": [_task(id="blocked1", status="blocked", assignee="frontend", heartbeat_age_seconds=None)]},
            {"name": "running", "tickets": []},
            {"name": "done", "tickets": []},
        ]
        health = plugin_api._board_ops_health(columns, {"ready": 1, "blocked": 1, "running": 0, "done": 0})

        self.assertEqual(health["level"], "warning")
        self.assertEqual(health["counts"]["blocked_tickets"], 1)
        self.assertEqual(health["counts"]["unassigned_ready"], 1)
        self.assertIn("review", health["next_action"].lower())


if __name__ == "__main__":
    unittest.main()
