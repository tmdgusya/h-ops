"""H-OPS dashboard plugin backend.

Mounted at /api/plugins/h-ops/ by the Hermes dashboard plugin system.

H-OPS is an operator-facing Ops board over the existing Hermes Kanban kernel.
It intentionally reuses Kanban tasks/runs/events/logs rather than creating a
second work system.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from hermes_cli import kanban_db

log = logging.getLogger(__name__)
router = APIRouter()

STATUS_ORDER = ["triage", "todo", "ready", "running", "blocked", "done"]
ACTIVE_STATUSES = {"ready", "running", "blocked"}
TEXT_ARTIFACT_SUFFIXES = {".md", ".markdown", ".mdx", ".txt", ".log", ".json"}
ARTIFACT_PATH_RE = re.compile(r"(?:~|/)[^\s'\"<>]+(?:\.md|\.markdown|\.mdx|\.txt|\.log|\.json)", re.IGNORECASE)


def _conn() -> sqlite3.Connection:
    try:
        kanban_db.init_db()
    except Exception as exc:  # pragma: no cover
        log.warning("h-ops kanban init failed: %s", exc)
    return kanban_db.connect()


def _json_loads(value: Optional[str], fallback: Any = None) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _compact_text(*values: Any, limit: int = 260) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            text = str(value)
        text = " ".join(text.split())
        if text:
            return text[:limit] + ("…" if len(text) > limit else "")
    return ""


def _run_dict(row: sqlite3.Row) -> Dict[str, Any]:
    data = _row_dict(row)
    data["metadata"] = _json_loads(data.get("metadata"), {})
    return data


def _latest_event(conn: sqlite3.Connection, task_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, task_id, run_id, kind, payload, created_at
        FROM task_events
        WHERE task_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if not row:
        return None
    item = _row_dict(row)
    item["payload"] = _json_loads(item.get("payload"), {})
    return item


def _latest_run(conn: sqlite3.Connection, task_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return _run_dict(row) if row else None


def _log_preview(task_id: str, tail_bytes: int = 4000) -> Dict[str, Any]:
    path = kanban_db.worker_log_path(task_id)
    content = kanban_db.read_worker_log(task_id, tail_bytes=tail_bytes)
    exists = content is not None
    size = path.stat().st_size if path.exists() else 0
    return {
        "exists": exists,
        "path": str(path),
        "size_bytes": size,
        "truncated": bool(size and size > tail_bytes),
        "content": content or "",
        "preview": _compact_text(content, limit=420) if content else "",
    }


def _safe_text_artifact(path_text: str, max_bytes: int = 120000) -> Optional[Dict[str, Any]]:
    try:
        path = Path(path_text).expanduser().resolve()
    except Exception:
        return None
    if path.suffix.lower() not in TEXT_ARTIFACT_SUFFIXES or not path.exists() or not path.is_file():
        return None
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(max_bytes + 1)
    except Exception:
        return None
    truncated = len(content.encode("utf-8", errors="ignore")) > max_bytes or size > max_bytes
    return {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "size_bytes": size,
        "truncated": truncated,
        "content": content[:max_bytes],
        "preview": _compact_text(content, limit=260),
    }


def _artifact_candidates(*values: Any, limit: int = 8) -> List[Dict[str, Any]]:
    seen = set()
    artifacts: List[Dict[str, Any]] = []
    def visit(value: Any) -> None:
        if len(artifacts) >= limit or value is None:
            return
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        for match in ARTIFACT_PATH_RE.findall(text):
            clean = match.rstrip(".,);]")
            if clean in seen:
                continue
            seen.add(clean)
            artifact = _safe_text_artifact(clean)
            if artifact:
                artifacts.append(artifact)
                if len(artifacts) >= limit:
                    return
    for value in values:
        visit(value)
    return artifacts


def _progress(task: Dict[str, Any], run: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    status = task.get("status")
    now = int(time.time())
    created = int(task.get("created_at") or now)
    age = max(0, now - created)
    heartbeat = task.get("last_heartbeat_at") or (run or {}).get("last_heartbeat_at")
    stale = False
    if heartbeat and status == "running":
        stale = now - int(heartbeat) > 180

    if status in {"done", "archived"}:
        pct, label = 100, "completed"
    elif status == "blocked":
        pct, label = 55, "blocked — operator input"
    elif status == "running":
        # visual progress only: keep moving but cap until completion.
        pct = min(86, 35 + int(age / 45))
        label = "running" if not stale else "running · heartbeat stale"
    elif status == "ready":
        pct, label = 20, "ready for dispatcher"
    elif status == "todo":
        pct, label = 10, "waiting"
    elif status == "triage":
        pct, label = 5, "needs spec"
    else:
        pct, label = 0, "unknown"
    return {"percent": pct, "label": label, "stale": stale}


def _ticket_health(task: Dict[str, Any], run: Optional[Dict[str, Any]], log_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute operator-facing health without treating completed old heartbeats as incidents."""
    status = str(task.get("status") or "unknown")
    run_status = str((run or {}).get("status") or status or "unknown")
    heartbeat_age = task.get("heartbeat_age_seconds")
    alerts: List[Dict[str, Any]] = []
    level = "healthy"
    worker_freshness = "unknown"
    interpretation = "No active operational issue detected."
    next_action = "None required"

    if status in {"done", "archived"}:
      worker_freshness = "not_required"
      interpretation = "Worker signal is historical and acceptable because the ticket is complete."
      if not (log_info or {}).get("exists"):
          alerts.append({"level": "notice", "label": "No worker log recorded", "detail": "The run completed without a worker log artifact."})
      return {
          "level": level,
          "run_status": run_status,
          "worker_freshness": worker_freshness,
          "last_heartbeat_label": None if heartbeat_age is None else f"{heartbeat_age}s",
          "interpretation": interpretation,
          "next_action": next_action,
          "alerts": alerts,
      }

    if status == "blocked":
        level = "warning"
        alerts.append({"level": "warning", "label": "Ticket blocked", "detail": "Operator input is required before the worker can continue.", "ticket_id": task.get("id")})
        next_action = "Review blocked ticket"
        worker_freshness = "not_required"
        interpretation = "Ticket is blocked and waiting on an operator decision."
    elif status == "ready" and not task.get("assignee"):
        level = "warning"
        alerts.append({"level": "warning", "label": "Ready but unassigned", "detail": "Assign a Hermes profile before dispatch.", "ticket_id": task.get("id")})
        next_action = "Assign a worker profile"
        worker_freshness = "not_required"
        interpretation = "Ticket is ready but cannot dispatch without an assignee."
    elif status == "running":
        if heartbeat_age is None:
            level = "critical"
            worker_freshness = "missing"
            alerts.append({"level": "critical", "label": "Worker heartbeat missing", "detail": "Running ticket has no recorded heartbeat.", "ticket_id": task.get("id")})
            next_action = "Inspect worker logs"
            interpretation = "Running ticket has no worker signal."
        elif int(heartbeat_age) > 300:
            level = "critical"
            worker_freshness = "stale"
            alerts.append({"level": "critical", "label": "Worker heartbeat stale", "detail": f"No worker signal for {int(heartbeat_age)} seconds.", "ticket_id": task.get("id")})
            next_action = "Inspect or restart worker"
            interpretation = "Running worker signal is stale and may require intervention."
        else:
            worker_freshness = "healthy"
            interpretation = "Worker heartbeat is fresh."
    else:
        worker_freshness = "not_required"

    if (run or {}).get("error"):
        level = "critical"
        alerts.append({"level": "critical", "label": "Latest run error", "detail": _compact_text((run or {}).get("error"), limit=160), "ticket_id": task.get("id")})
        next_action = "Review run error"

    return {
        "level": level,
        "run_status": run_status,
        "worker_freshness": worker_freshness,
        "last_heartbeat_label": None if heartbeat_age is None else f"{heartbeat_age}s",
        "interpretation": interpretation,
        "next_action": next_action,
        "alerts": alerts,
    }


def _board_ops_health(columns: List[Dict[str, Any]], counts: Dict[str, int]) -> Dict[str, Any]:
    tickets = [ticket for column in columns for ticket in column.get("tickets", [])]
    blocked = [t for t in tickets if t.get("status") == "blocked"]
    unassigned_ready = [t for t in tickets if t.get("status") == "ready" and not t.get("assignee")]
    stale_running = [t for t in tickets if t.get("status") == "running" and (t.get("heartbeat_age_seconds") is None or int(t.get("heartbeat_age_seconds") or 0) > 300)]
    failed = [t for t in tickets if (t.get("latest_run") or {}).get("error")]
    alerts: List[Dict[str, Any]] = []

    for ticket in stale_running[:4]:
        alerts.append({"level": "critical", "label": "Stale running worker", "detail": ticket.get("title") or ticket.get("id"), "ticket_id": ticket.get("id")})
    if blocked:
        alerts.append({"level": "warning", "label": "Blocked tickets", "detail": f"{len(blocked)} ticket(s) require operator input."})
    if unassigned_ready:
        alerts.append({"level": "warning", "label": "Ready but unassigned", "detail": f"{len(unassigned_ready)} ready ticket(s) have no assignee."})
    if failed:
        alerts.append({"level": "critical", "label": "Run errors", "detail": f"{len(failed)} latest run(s) reported errors."})

    if stale_running or failed:
        level = "critical"
        summary = "Critical worker/run issue requires attention"
        next_action = "Inspect running or failed tickets"
    elif blocked or unassigned_ready:
        level = "warning"
        summary = "Operator review recommended"
        next_action = "Review blocked or unassigned tickets"
    elif int(counts.get("running", 0) or 0):
        level = "notice"
        summary = "Workers are active"
        next_action = "Monitor running tickets"
    else:
        level = "healthy"
        summary = "No active operational issues"
        next_action = "None required"

    return {
        "level": level,
        "summary": summary,
        "next_action": next_action,
        "alerts": alerts,
        "counts": {
            "failed_attempts": len(failed),
            "blocked_tickets": len(blocked),
            "stale_workers": len(stale_running),
            "unassigned_ready": len(unassigned_ready),
            "running": int(counts.get("running", 0) or 0),
        },
    }


def _linked_task_brief(row: sqlite3.Row) -> Dict[str, Any]:
    task = _row_dict(row)
    task["skills"] = _json_loads(task.get("skills"), [])
    run_hint = task.get("current_run_id")
    return {
        "id": task.get("id"),
        "title": task.get("title") or task.get("id"),
        "status": task.get("status") or "unknown",
        "assignee": task.get("assignee") or None,
        "priority": int(task.get("priority") or 0),
        "current_run_id": run_hint,
        "created_at": task.get("created_at"),
        "last_heartbeat_at": task.get("last_heartbeat_at"),
        "skills": task.get("skills") or [],
        "output_preview": _compact_text(task.get("result"), task.get("body"), limit=180),
    }


def _dependency_tasks(conn: sqlite3.Connection, task_id: str) -> Dict[str, List[Dict[str, Any]]]:
    parent_rows = conn.execute(
        """
        SELECT t.*
        FROM task_links l
        JOIN tasks t ON t.id = l.parent_id
        WHERE l.child_id = ?
        ORDER BY t.status = 'done' DESC, t.priority DESC, t.created_at DESC
        """,
        (task_id,),
    ).fetchall()
    child_rows = conn.execute(
        """
        SELECT t.*
        FROM task_links l
        JOIN tasks t ON t.id = l.child_id
        WHERE l.parent_id = ?
        ORDER BY t.status = 'done', t.priority DESC, t.created_at DESC
        """,
        (task_id,),
    ).fetchall()
    return {
        "parents": [_linked_task_brief(row) for row in parent_rows],
        "children": [_linked_task_brief(row) for row in child_rows],
    }


def _dependency_summary(conn: sqlite3.Connection, task_id: str) -> Dict[str, Any]:
    linked = _dependency_tasks(conn, task_id)
    parents = linked["parents"]
    children = linked["children"]
    blocking = [item for item in parents if item.get("status") != "done"]
    parents_done = len(parents) - len(blocking)
    waiting_children = [item for item in children if item.get("status") in {"todo", "triage"}]
    ready_children = [item for item in children if item.get("status") == "ready"]
    running_children = [item for item in children if item.get("status") == "running"]
    next_assignees: List[str] = []
    for child in children:
        assignee = child.get("assignee")
        if assignee and assignee not in next_assignees:
            next_assignees.append(str(assignee))

    if blocking:
        state = "waiting"
        names = []
        for item in blocking[:2]:
            names.append(str(item.get("assignee") or item.get("title") or item.get("id")))
        label = "Waiting for " + " + ".join(names)
        if len(blocking) > 2:
            label += f" +{len(blocking) - 2}"
    elif children:
        state = "unlocks"
        if next_assignees:
            label = "Unlocks " + " + ".join(next_assignees[:2])
            if len(next_assignees) > 2:
                label += f" +{len(next_assignees) - 2}"
        else:
            label = f"Unlocks {len(children)} ticket" + ("" if len(children) == 1 else "s")
    elif parents:
        state = "mixed"
        label = f"Parents {parents_done}/{len(parents)} done"
    else:
        state = "none"
        label = "No chain"

    return {
        "parent_count": len(parents),
        "parents_done": parents_done,
        "parents_blocking": len(blocking),
        "child_count": len(children),
        "children_waiting": len(waiting_children),
        "children_ready": len(ready_children),
        "children_running": len(running_children),
        "next_assignees": next_assignees,
        "blocked_by": blocking[:4],
        "unlocks": children[:4],
        "label": label,
        "state": state,
    }


def _task_ops_card(conn: sqlite3.Connection, row: sqlite3.Row, include_log: bool = False) -> Dict[str, Any]:
    task = _row_dict(row)
    now = int(time.time())
    created_at = task.get("created_at") or now
    last_heartbeat_at = task.get("last_heartbeat_at")
    task["age_seconds"] = max(0, now - int(created_at))
    task["heartbeat_age_seconds"] = max(0, now - int(last_heartbeat_at)) if last_heartbeat_at else None
    task["skills"] = _json_loads(task.get("skills"), [])

    run = _latest_run(conn, task["id"])
    event = _latest_event(conn, task["id"])
    log_info = _log_preview(task["id"], tail_bytes=6000 if include_log else 1600)
    output_preview = _compact_text(
        (run or {}).get("summary"),
        task.get("result"),
        (run or {}).get("error"),
        (event or {}).get("payload"),
        log_info.get("preview"),
        task.get("body"),
        limit=360,
    )
    task.update({
        "latest_run": run,
        "latest_event": event,
        "log": log_info if include_log else {k: log_info[k] for k in ("exists", "path", "size_bytes", "truncated", "preview")},
        "output_preview": output_preview,
        "progress": _progress(task, run),
        "health": _ticket_health(task, run, log_info),
        "dependency_summary": _dependency_summary(conn, task["id"]),
    })
    return task


def _status_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    counts = {status: 0 for status in [*STATUS_ORDER, "archived"]}
    for row in conn.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"):
        counts[str(row["status"])] = int(row["count"])
    return counts


def _timeline(conn: sqlite3.Connection, limit: int = 40, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where = ""
    if task_id:
        where = "WHERE e.task_id = ?"
        params.append(task_id)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.id, e.task_id, e.run_id, e.kind, e.payload, e.created_at,
               t.title, t.assignee, t.status
        FROM task_events e
        LEFT JOIN tasks t ON t.id = e.task_id
        {where}
        ORDER BY e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    events: List[Dict[str, Any]] = []
    for row in rows:
        item = _row_dict(row)
        item["payload"] = _json_loads(item.get("payload"), {})
        item["summary"] = _compact_text(item["payload"], limit=220)
        events.append(item)
    return events


def _profile_metadata() -> Dict[str, Dict[str, Any]]:
    try:
        from hermes_cli.profiles import list_profiles  # type: ignore
    except Exception:
        return {}
    try:
        profiles = list_profiles()
    except Exception as exc:  # pragma: no cover - defensive for mixed Hermes versions
        log.debug("h-ops profile metadata unavailable: %s", exc)
        return {}
    meta: Dict[str, Dict[str, Any]] = {}
    for profile in profiles or []:
        name = getattr(profile, "name", None) or (profile.get("name") if isinstance(profile, dict) else None)
        if not name:
            continue
        def get(field: str) -> Any:
            return getattr(profile, field, None) if not isinstance(profile, dict) else profile.get(field)
        meta[str(name)] = {
            "name": str(name),
            "on_disk": True,
            "path": str(get("path")) if get("path") else None,
            "gateway_running": bool(get("gateway_running")),
            "model": get("model"),
            "provider": get("provider"),
            "has_env": get("has_env"),
            "skill_count": int(get("skill_count") or 0),
            "alias_path": str(get("alias_path")) if get("alias_path") else None,
        }
    return meta


def _agent_availability(agent: Dict[str, Any]) -> str:
    name = agent.get("name")
    if not agent.get("on_disk") and name != "unassigned":
        return "unconfigured"
    if int(agent.get("stale_running_count") or 0) > 0:
        return "stale"
    if int(agent.get("running_count") or 0) > 0:
        return "running"
    if int(agent.get("blocked_count") or 0) > 0:
        return "blocked"
    if int(agent.get("ready_count") or 0) > 0:
        return "queued"
    if agent.get("has_env") is False:
        return "offline"
    if agent.get("gateway_running") is False:
        return "stopped"
    return "idle"


def _agents(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    try:
        known = kanban_db.known_assignees(conn)
    except Exception:
        known = []
    known_names = {str(a.get("name") if isinstance(a, dict) else a) for a in known if a}
    profile_meta = _profile_metadata()
    all_names = {n for n in known_names if n} | set(profile_meta.keys())
    rows = conn.execute(
        """
        SELECT COALESCE(assignee, '') AS name,
               COUNT(*) AS task_count,
               SUM(CASE WHEN status = 'triage' THEN 1 ELSE 0 END) AS triage_count,
               SUM(CASE WHEN status = 'todo' THEN 1 ELSE 0 END) AS todo_count,
               SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready_count,
               SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_count,
               SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_count,
               SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
               SUM(CASE WHEN status = 'running' AND (last_heartbeat_at IS NULL OR (? - last_heartbeat_at) > 300) THEN 1 ELSE 0 END) AS stale_running_count,
               MAX(last_heartbeat_at) AS task_last_seen_at
        FROM tasks
        WHERE status != 'archived'
        GROUP BY COALESCE(assignee, '')
        """,
        (int(time.time()),),
    ).fetchall()
    by_name: Dict[str, Dict[str, Any]] = {}

    def base_entry(name: str, source: str) -> Dict[str, Any]:
        meta = profile_meta.get(name, {})
        return {
            "name": name,
            "source": source,
            "task_count": 0,
            "triage_count": 0,
            "todo_count": 0,
            "ready_count": 0,
            "running_count": 0,
            "blocked_count": 0,
            "done_count": 0,
            "stale_running_count": 0,
            "last_seen_at": None,
            "on_disk": bool(meta.get("on_disk")),
            "path": meta.get("path"),
            "gateway_running": meta.get("gateway_running"),
            "model": meta.get("model"),
            "provider": meta.get("provider"),
            "has_env": meta.get("has_env"),
            "skill_count": meta.get("skill_count"),
            "alias_path": meta.get("alias_path"),
        }

    for name in all_names:
        by_name[name] = base_entry(name, "profile")

    for row in rows:
        name = row["name"] or "unassigned"
        entry = by_name.setdefault(name, base_entry(name, "task-history"))
        if entry["source"] == "profile" and not entry.get("on_disk"):
            entry["source"] = "task-history"
        task_last_seen = row["task_last_seen_at"]
        entry.update({
            "task_count": int(row["task_count"] or 0),
            "triage_count": int(row["triage_count"] or 0),
            "todo_count": int(row["todo_count"] or 0),
            "ready_count": int(row["ready_count"] or 0),
            "running_count": int(row["running_count"] or 0),
            "blocked_count": int(row["blocked_count"] or 0),
            "done_count": int(row["done_count"] or 0),
            "stale_running_count": int(row["stale_running_count"] or 0),
            "last_seen_at": task_last_seen,
        })
    run_rows = conn.execute(
        "SELECT COALESCE(profile, '') AS profile, MAX(COALESCE(last_heartbeat_at, started_at)) AS last_seen_at FROM task_runs GROUP BY COALESCE(profile, '')"
    ).fetchall()
    for row in run_rows:
        name = row["profile"] or "unassigned"
        entry = by_name.setdefault(name, base_entry(name, "run-history"))
        if row["last_seen_at"] and (entry.get("last_seen_at") is None or int(row["last_seen_at"]) > int(entry.get("last_seen_at") or 0)):
            entry["last_seen_at"] = row["last_seen_at"]
    labels = {
        "running": "running",
        "queued": "queued",
        "blocked": "blocked",
        "stale": "stale worker",
        "idle": "idle",
        "unconfigured": "missing profile",
        "offline": "env missing",
        "stopped": "profile stopped",
    }
    for entry in by_name.values():
        availability = _agent_availability(entry)
        entry["availability"] = availability
        entry["availability_label"] = labels.get(availability, availability)
    return sorted(by_name.values(), key=lambda a: (a["name"] == "unassigned", a.get("availability") not in {"stale", "running", "queued", "blocked"}, -(a.get("running_count") or 0), a["name"]))


def _assignee_names(conn: sqlite3.Connection) -> List[str]:
    try:
        raw = kanban_db.known_assignees(conn)
    except Exception:
        raw = []
    names = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name) not in names:
            names.append(str(name))
    return sorted(names)


class CreateTicketPayload(BaseModel):
    title: str = Field(..., min_length=1)
    body: Optional[str] = None
    assignee: Optional[str] = None
    priority: int = 0
    triage: bool = False
    tenant: Optional[str] = None
    skills: Optional[List[str]] = None
    parents: List[str] = []


class AssignPayload(BaseModel):
    assignee: Optional[str] = None


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "plugin": "h-ops", "version": "0.2.0"}


@router.get("/ops-board")
def ops_board(limit_per_column: int = Query(80, ge=1, le=250)) -> Dict[str, Any]:
    with _conn() as conn:
        columns = []
        for status in STATUS_ORDER:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY priority DESC, COALESCE(last_heartbeat_at, created_at) DESC
                LIMIT ?
                """,
                (status, limit_per_column),
            ).fetchall()
            columns.append({"name": status, "tickets": [_task_ops_card(conn, r) for r in rows]})
        counts = _status_counts(conn)
        visible_count = sum(counts.get(s, 0) for s in STATUS_ORDER)
        shown_count = sum(len(column["tickets"]) for column in columns)
        return {
            "generated_at": int(time.time()),
            "status_counts": counts,
            # Match the bundled Kanban board: all non-archived workflow columns.
            # Keep active_count separately so a quiet board with completed tickets does not look empty.
            "visible_count": visible_count,
            "shown_count": shown_count,
            "active_count": sum(counts.get(s, 0) for s in ACTIVE_STATUSES),
            "archived_count": counts.get("archived", 0),
            "assignees": _assignee_names(conn),
            "agents": _agents(conn),
            "ops_health": _board_ops_health(columns, counts),
            "columns": columns,
            "events": _timeline(conn, limit=35),
        }


@router.get("/overview")
def overview() -> Dict[str, Any]:
    return ops_board()


@router.get("/tickets/{task_id}")
def ticket(task_id: str) -> Dict[str, Any]:
    with _conn() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="ticket not found")
        runs = conn.execute("SELECT * FROM task_runs WHERE task_id = ? ORDER BY id DESC", (task_id,)).fetchall()
        run_items = [_run_dict(row) for row in runs]
        comments = conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
        parents = conn.execute("SELECT parent_id FROM task_links WHERE child_id = ? ORDER BY parent_id", (task_id,)).fetchall()
        children = conn.execute("SELECT child_id FROM task_links WHERE parent_id = ? ORDER BY child_id", (task_id,)).fetchall()
        dependency_tasks = _dependency_tasks(conn, task_id)
        ticket_item = _task_ops_card(conn, task, include_log=True)
        event_items = _timeline(conn, limit=100, task_id=task_id)
        artifacts = _artifact_candidates(
            ticket_item.get("body"),
            ticket_item.get("result"),
            ticket_item.get("output_preview"),
            ticket_item.get("log", {}).get("content"),
            run_items,
            event_items,
        )
        return {
            "ticket": ticket_item,
            "runs": run_items,
            "events": event_items,
            "comments": [_row_dict(row) for row in comments],
            "artifacts": artifacts,

            "dependencies": {
                "parents": [row["parent_id"] for row in parents],
                "children": [row["child_id"] for row in children],
                "parent_tasks": dependency_tasks["parents"],
                "child_tasks": dependency_tasks["children"],
                "summary": ticket_item.get("dependency_summary") or _dependency_summary(conn, task_id),
            },
        }


@router.get("/tickets/{task_id}/log")
def ticket_log(task_id: str, tail: int = Query(12000, ge=1, le=250000)) -> Dict[str, Any]:
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
            raise HTTPException(status_code=404, detail="ticket not found")
    return {"task_id": task_id, **_log_preview(task_id, tail_bytes=tail)}


@router.post("/tickets")
def create_ticket(payload: CreateTicketPayload) -> Dict[str, Any]:
    with _conn() as conn:
        try:
            task_id = kanban_db.create_task(
                conn,
                title=payload.title,
                body=payload.body,
                assignee=payload.assignee or None,
                priority=payload.priority,
                triage=payload.triage,
                tenant=payload.tenant,
                created_by="h-ops",
                skills=payload.skills,
                parents=payload.parents or (),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return {"ok": True, "ticket": _task_ops_card(conn, row) if row else {"id": task_id}}


@router.patch("/tickets/{task_id}/assign")
def assign_ticket(task_id: str, payload: AssignPayload) -> Dict[str, Any]:
    with _conn() as conn:
        try:
            ok = kanban_db.assign_task(conn, task_id, payload.assignee or None)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=404, detail="ticket not found")
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return {"ok": True, "ticket": _task_ops_card(conn, row) if row else None}


@router.get("/agents")
def agents() -> Dict[str, Any]:
    with _conn() as conn:
        return {"agents": _agents(conn), "assignees": _assignee_names(conn)}


def _edge_state(parent: Dict[str, Any], child: Dict[str, Any]) -> str:
    if parent.get("status") != "done":
        return "waiting"
    if child.get("status") in {"running", "done", "blocked"}:
        return str(child.get("status"))
    return "unlocked"


def _workflow_graph(conn: sqlite3.Connection, limit: int = 200, focus: Optional[str] = None, depth: int = 2) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 200), 500))
    params: List[Any] = []
    where = "WHERE status != 'archived'"
    if focus:
        # Keep v1 intentionally simple: include focus plus immediate neighbours.
        ids = {focus}
        for row in conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (focus,)).fetchall():
            ids.add(row["parent_id"])
        for row in conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?", (focus,)).fetchall():
            ids.add(row["child_id"])
        placeholders = ",".join("?" for _ in ids)
        where = f"WHERE id IN ({placeholders})"
        params.extend(sorted(ids))
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM tasks
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    nodes = [_linked_task_brief(row) for row in rows]
    by_id = {node["id"]: node for node in nodes}
    if not by_id:
        return {"nodes": [], "edges": [], "generated_at": int(time.time())}
    placeholders = ",".join("?" for _ in by_id)
    link_rows = conn.execute(
        f"""
        SELECT parent_id, child_id
        FROM task_links
        WHERE parent_id IN ({placeholders}) AND child_id IN ({placeholders})
        ORDER BY parent_id, child_id
        """,
        [*by_id.keys(), *by_id.keys()],
    ).fetchall()
    edges = []
    for row in link_rows:
        parent = by_id.get(row["parent_id"], {})
        child = by_id.get(row["child_id"], {})
        edges.append({"parent_id": row["parent_id"], "child_id": row["child_id"], "state": _edge_state(parent, child)})
    return {"nodes": nodes, "edges": edges, "generated_at": int(time.time()), "focus": focus, "depth": depth}


@router.get("/workflow-graph")
def workflow_graph(limit: int = Query(200, ge=1, le=500), focus: Optional[str] = None, depth: int = Query(2, ge=1, le=6)) -> Dict[str, Any]:
    with _conn() as conn:
        return _workflow_graph(conn, limit=limit, focus=focus, depth=depth)


@router.get("/events")
def events(limit: int = Query(50, ge=1, le=300), task_id: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as conn:
        return {"events": _timeline(conn, limit=limit, task_id=task_id)}


@router.get("/interfaces")
def interfaces() -> Dict[str, Any]:
    return {
        "plugin": "h-ops",
        "interfaces": [
            {"id": "ops-board", "label": "Ops Board", "purpose": "Kanban-like board with assignment, progress, and output previews."},
            {"id": "ticket-dossier", "label": "Ticket Dossier", "purpose": "Run/output/log focused external view of a ticket."},
            {"id": "agent-roster", "label": "Agent Roster", "purpose": "Profile load, heartbeat, and queue health."},
            {"id": "operator-actions", "label": "Operator Actions", "purpose": "Create, assign, dispatch, unblock, retry, and comment."},
        ],
    }
