# H-OPS Profile Status + Chain UX Implementation Plan

## Goal

Improve H-OPS from a Kanban mirror into a more intuitive multi-agent operations cockpit by adding:

1. **Profile status visibility** — show which Hermes profiles/agents exist, whether they are configured, their workload, queue/running/blocked state, and recent worker activity.
2. **Chain/dependency visibility** — make `task_links` legible in the board/card/dossier UI so operators can understand “when this ticket finishes, which agent/task starts next?”
3. **Chain creation UX** — provide an operator-friendly way to create the next agent task without manually typing parent task IDs.
4. **Future graph view foundation** — design backend data shapes so a later Workflow Graph tab can render the same dependency data without another backend rewrite.

This plan is intentionally staged. The first implementation should be read-only observability, then mutation/actions, then graph view.

---

## Current Context / Assumptions

### Repository

Active workspace:

```text
/Users/roach/h-ops
```

Relevant files currently in H-OPS:

```text
dashboard/plugin_api.py
dashboard/dist/index.js
dashboard/dist/style.css
docs/interfaces.md
tests/test_ops_health.py
README.md
```

### Hermes Kanban data model

Hermes Kanban already has durable dependency and run state:

```sql
tasks
  id
  title
  body
  assignee
  status
  priority
  created_at
  started_at
  completed_at
  worker_pid
  last_heartbeat_at
  current_run_id
  skills
  ...

task_links
  parent_id
  child_id

task_runs
  task_id
  profile
  status
  worker_pid
  last_heartbeat_at
  started_at
  ended_at
  outcome
  summary
  metadata
  error

task_events
  task_id
  run_id
  kind
  payload
  created_at
```

`hermes_cli.kanban_db` already exposes:

- `known_assignees(conn)`
- `parent_ids(conn, task_id)`
- `child_ids(conn, task_id)`
- `link_tasks(conn, parent_id, child_id)`
- `create_task(..., parents=...)`
- `recompute_ready(conn)`

`hermes_cli.profiles` exposes richer profile metadata:

- `list_profiles()`
- `ProfileInfo.name`
- `ProfileInfo.path`
- `ProfileInfo.gateway_running`
- `ProfileInfo.model`
- `ProfileInfo.provider`
- `ProfileInfo.has_env`
- `ProfileInfo.skill_count`
- `ProfileInfo.alias_path`

### Current H-OPS backend behavior

`dashboard/plugin_api.py` already has:

- `/api/plugins/h-ops/ops-board`
- `/api/plugins/h-ops/tickets/{task_id}`
- `/api/plugins/h-ops/agents`
- `_agents(conn)` with workload counts and `last_seen_at`
- `_task_ops_card(conn, row, include_log=False)` with health/progress/run/log previews
- ticket detail dependency output as ID-only:

```json
"dependencies": {
  "parents": ["t_parent"],
  "children": ["t_child"]
}
```

### Current H-OPS frontend behavior

`dashboard/dist/index.js` currently includes:

- `AgentStrip({ agents })` as simple chips
- `TicketCard(...)`
- `Dossier(...)`
- `Composer(...)`
- `ProgressBar(...)`
- board filters and status strip

Current UI already has gradients/progress bars, so this work should build on the existing visual language instead of introducing a totally different style.

---

## Proposed UX Direction

### UX principle

Do not expose Kanban internals as raw database concepts first. Translate them into operator language:

- `task_links.parent_id` → “waiting for” / “after this finishes”
- `task_links.child_id` → “unlocks next” / “will spawn”
- `assignee` → “agent profile”
- `ready_count` → “queued for this profile”
- `running_count` + heartbeat → “live worker” or “stale worker”

### Main surfaces

#### 1. Profile Status Strip

Upgrade the current AgentStrip into a richer profile roster.

Example card:

```text
backend
● idle
ready 0 · running 0 · blocked 0
skills 90 · env ok
last seen 2h ago
```

Possible profile states:

| State | Meaning | Visual treatment |
|---|---|---|
| `running` | profile has running task and fresh heartbeat | teal/green pulse |
| `queued` | profile has ready tasks but none running | blue outline / “next up” |
| `blocked` | profile has blocked tasks | amber warning |
| `stale` | running task has stale/missing heartbeat | red warning |
| `idle` | configured, no active work | muted neutral |
| `unconfigured` | assignee appears in tasks but profile missing on disk | red/dashed |
| `offline` | profile exists but missing env/config signal | gray warning |

Note: `gateway_running` is not necessarily equivalent to a profile being dispatchable because the current Kanban dispatcher runs inside the main gateway. UI copy should avoid implying each profile must have its own gateway unless the backend confirms that semantics.

#### 2. Ticket Card Dependency Hints

Every ticket card should show a compact dependency summary:

```text
Waiting for backend
```

or:

```text
Unlocks frontend + reviewer
```

or:

```text
No chain
```

Suggested visual elements:

- Small “chain” badge under title/output preview
- Parent progress: `Parents 1/2 done`
- Child preview: `Next: frontend`
- Waiting state: muted/amber when parent incomplete
- Unlock state: teal/blue when child will dispatch after completion

#### 3. Dossier Chain Rail

Inside selected-ticket dossier, add a local chain view using rich dependency data:

```text
✓ backend · Implement API
  done · completed handoff available

↓ unlocks

● frontend · Build UI
  todo · waiting for parent

↓ then

○ reviewer · Review implementation
  todo · waiting
```

For initial version, show only immediate parents and children. Later version can add recursive ancestors/descendants.

#### 4. Add Next Agent

After read-only dependency visibility is stable, add a mutation flow:

```text
Add next agent
```

Modal copy:

```text
When this ticket completes, start another agent task.

Assignee: [frontend ▼]
Title: [Build UI from backend output]
Mission brief: [...]
```

Backend creates a new child task:

```python
kanban_db.create_task(
    conn,
    title=payload.title,
    body=payload.body,
    assignee=payload.assignee,
    parents=[parent_task_id],
    created_by="h-ops",
    ...
)
```

#### 5. Workflow Graph View

Later stage: add a dedicated `Workflow Graph` tab/mode. It should consume a graph endpoint with nodes and edges:

```json
{
  "nodes": [
    {"id":"t_1", "title":"API", "assignee":"backend", "status":"done", "health": {...}},
    {"id":"t_2", "title":"UI", "assignee":"frontend", "status":"todo", "health": {...}}
  ],
  "edges": [
    {"parent_id":"t_1", "child_id":"t_2", "state":"unlocked|waiting|blocked"}
  ]
}
```

Initial graph can be a CSS-based DAG/list rather than a heavy graph library. Avoid adding a dependency like React Flow unless needed.

---

## Step-by-Step Plan

## Phase 1 — Backend Read Model: Profile Status + Dependency Summary

### 1.1 Add profile metadata merge

File:

```text
dashboard/plugin_api.py
```

Enhance `_agents(conn)` to merge three sources:

1. `kanban_db.known_assignees(conn)`
2. task/run counts from `tasks` and `task_runs`
3. `hermes_cli.profiles.list_profiles()` metadata

Implementation notes:

- Import `list_profiles` defensively inside the function so plugin does not hard-fail if Hermes internals differ.
- Convert `ProfileInfo` to plain dict fields.
- Preserve current fields so frontend remains compatible:
  - `name`
  - `source`
  - `task_count`
  - `ready_count`
  - `running_count`
  - `blocked_count`
  - `last_seen_at`
- Add new fields:
  - `on_disk`
  - `gateway_running`
  - `model`
  - `provider`
  - `has_env`
  - `skill_count`
  - `alias_path`
  - `availability`
  - `availability_label`
  - `stale_running_count`
  - `done_count`
  - `todo_count`
  - `triage_count`

Suggested availability function:

```python
def _agent_availability(agent):
    if not agent.get("on_disk") and agent["name"] != "unassigned":
        return "unconfigured"
    if agent.get("stale_running_count", 0) > 0:
        return "stale"
    if agent.get("running_count", 0) > 0:
        return "running"
    if agent.get("blocked_count", 0) > 0:
        return "blocked"
    if agent.get("ready_count", 0) > 0:
        return "queued"
    if agent.get("has_env") is False:
        return "offline"
    return "idle"
```

Do not overstate gateway semantics. If using `gateway_running`, label as profile gateway signal, not dispatcher proof.

### 1.2 Add dependency summary for board cards

File:

```text
dashboard/plugin_api.py
```

Add helper:

```python
def _dependency_summary(conn, task_id: str) -> dict:
    ...
```

It should return enough for board cards without loading large logs:

```json
{
  "parent_count": 2,
  "parents_done": 1,
  "parents_blocking": 1,
  "child_count": 2,
  "children_waiting": 2,
  "children_ready": 0,
  "children_running": 0,
  "next_assignees": ["frontend", "reviewer"],
  "blocked_by": [
    {"id":"t_1", "title":"API", "status":"running", "assignee":"backend"}
  ],
  "unlocks": [
    {"id":"t_2", "title":"UI", "status":"todo", "assignee":"frontend"}
  ],
  "label": "Waiting for backend",
  "state": "waiting|unlocks|none|mixed"
}
```

Rules:

- Parent is blocking if parent status is not `done`.
- Child is waiting if child status is `todo` and this task is not done.
- `next_assignees` are child assignees, deduped, excluding empty.
- For large graphs, cap `blocked_by` and `unlocks` at 4 items and include counts.

Call this from `_task_ops_card()` and add:

```python
task["dependency_summary"] = _dependency_summary(conn, task["id"])
```

### 1.3 Expand ticket detail dependencies into rich objects

File:

```text
dashboard/plugin_api.py
```

Currently `/tickets/{task_id}` returns ID arrays. Keep backward-compatible IDs, but add rich objects:

```json
"dependencies": {
  "parents": ["t_1"],
  "children": ["t_2"],
  "parent_tasks": [...],
  "child_tasks": [...],
  "summary": {...}
}
```

Use a lightweight task serializer without logs for parent/child tasks, or reuse `_task_ops_card(conn, row, include_log=False)` if performance is acceptable.

### 1.4 Add graph endpoint foundation

File:

```text
dashboard/plugin_api.py
```

Add read-only endpoint:

```text
GET /api/plugins/h-ops/workflow-graph
```

Query options:

- `limit`: max nodes, default 200
- `focus`: optional selected task id
- `depth`: optional depth around focus, default 2

Initial response:

```json
{
  "nodes": [...],
  "edges": [...],
  "generated_at": 1770000000
}
```

Even if the graph UI is Phase 4, this endpoint allows testing the data model early.

---

## Phase 2 — Frontend Read-Only UX

### 2.1 Upgrade AgentStrip

File:

```text
dashboard/dist/index.js
```

Replace simple chip rendering with richer profile cards:

- Show `availability` with state dot/pulse.
- Show ready/running/blocked counts.
- Show `last_seen_at` via existing `fmtTime()` or a compact age helper.
- Show `provider/model` when available.
- Show `skill_count` and `has_env` as small metadata.

Suggested structure:

```js
function AgentStrip({ agents }) {
  return h("section", { className: "hops-agent-strip" },
    h("div", { className: "hops-strip-head" }, ...),
    h("div", { className: "hops-agent-grid" }, ...)
  );
}
```

### 2.2 Add DependencyBadge component

File:

```text
dashboard/dist/index.js
```

Add:

```js
function DependencyBadge({ summary }) { ... }
```

Behavior:

- If no parents/children, optionally hide or show small `No chain` only in dossier, not on every card.
- If waiting on parents:
  - `Waiting for backend`
  - `Parents 1/2 done`
- If unlocks children:
  - `Unlocks frontend + reviewer`
  - `2 next tasks`
- If both parent and child exist:
  - `Chain 1 → this → 2`

Use in `TicketCard` under the title/output preview and before/near the progress bar.

### 2.3 Add ChainRail component in Dossier

File:

```text
dashboard/dist/index.js
```

Add:

```js
function ChainRail({ dependencies, currentTicket }) { ... }
```

Render:

- parent tasks above/current left
- current task highlighted
- child tasks below/right
- status pills and assignee tags
- click on dependency task can eventually select it; for first version, just display IDs/titles or add a callback if easy.

Use in `Dossier` after `DossierHealthPanel` and before `TicketActionsBar` or after `ProgressBar`.

### 2.4 Style new UI

File:

```text
dashboard/dist/style.css
```

Add styles for:

- `.hops-agent-grid`
- `.hops-agent-chip.is-running`
- `.hops-agent-chip.is-stale`
- `.hops-agent-chip.is-queued`
- `.hops-agent-chip.is-unconfigured`
- `.hops-dependency-badge`
- `.hops-dependency-badge.is-waiting`
- `.hops-dependency-badge.is-unlocks`
- `.hops-chain-rail`
- `.hops-chain-node`
- `.hops-chain-edge`

Keep visual language consistent with current dark tactical UI:

- glassy panels
- teal/blue gradients for healthy/active
- amber for blocked/waiting
- red for stale/errors
- muted gray for idle/no chain

---

## Phase 3 — Chain Creation: “Add Next Agent”

Only start after Phase 1–2 are working and visually validated.

### 3.1 Backend: create child ticket endpoint

File:

```text
dashboard/plugin_api.py
```

Options:

#### Option A — extend existing `POST /tickets`

Add fields to `CreateTicketPayload`:

```python
parents: Optional[List[str]] = None
parent_id: Optional[str] = None
```

Then pass:

```python
parents=payload.parents or ([payload.parent_id] if payload.parent_id else [])
```

#### Option B — add explicit endpoint

```text
POST /api/plugins/h-ops/tickets/{task_id}/children
```

Payload:

```json
{
  "title": "Build frontend UI",
  "body": "Use parent output...",
  "assignee": "frontend",
  "priority": 0,
  "triage": false,
  "skills": []
}
```

Recommendation: use Option B for clearer semantics and less risk to existing composer.

### 3.2 Frontend: AddNextAgent modal

File:

```text
dashboard/dist/index.js
```

Add component:

```js
function AddNextAgentModal({ parentTicket, assignees, onClose, onCreated }) { ... }
```

Fields:

- Assignee select
- Title input
- Mission brief textarea
- Priority
- Park in triage checkbox

Default title suggestion:

```text
Continue: <parent ticket title>
```

Default body suggestion:

```text
This task starts after parent ticket <id> completes.
Read the parent handoff summary, run metadata, comments, and logs before starting.

Goal:
```

Button copy:

```text
Create child task
```

### 3.3 Dossier action

Add button near assignment/actions:

```text
Add next agent
```

After child is created:

- refresh board
- show selected ticket still open
- update ChainRail to include the new child
- maybe show success banner: `frontend will start after this ticket completes`

---

## Phase 4 — Workflow Graph View

### 4.1 Frontend mode toggle

File:

```text
dashboard/dist/index.js
```

Add board view mode state:

```js
const [viewMode, setViewMode] = hooks.useState("board");
```

Toggle:

```text
Board | Workflow Graph | Events
```

Initial implementation can keep board as default.

### 4.2 Graph renderer

Avoid heavy dependencies at first. Use CSS/SVG:

- group nodes by depth/layer
- edges as SVG lines or simple connector rows
- node cards use existing status colors

For first graph version, a vertical DAG list is acceptable:

```text
Root tasks
  ↓
Children
  ↓
Grandchildren
```

Later, if graph complexity grows, evaluate React Flow or D3, but only after native CSS/SVG proves insufficient.

### 4.3 Graph interactions

Initial graph interactions:

- click node → select/open dossier
- filter by profile/status
- focus on selected chain

Future interactions:

- drag-to-link
- unlink edge
- create branch
- create fan-in node from selected tasks

---

## Files Likely to Change

### Backend

```text
dashboard/plugin_api.py
```

Likely additions:

- `_profiles_metadata()`
- `_agent_availability()`
- `_dependency_summary()`
- `_dependency_tasks()`
- `workflow_graph()` route
- optional child-ticket creation route

### Frontend

```text
dashboard/dist/index.js
```

Likely additions/changes:

- `AgentStrip` rewrite
- `DependencyBadge`
- `ChainRail`
- `AddNextAgentModal`
- optional `WorkflowGraphView`
- `Dossier` integration
- `TicketCard` integration
- board view mode state

### Styles

```text
dashboard/dist/style.css
```

Likely additions:

- richer agent cards
- availability states
- dependency badges
- chain rail
- add-next modal
- graph view

### Tests

Existing:

```text
tests/test_ops_health.py
```

Add or extend:

```text
tests/test_ops_dependencies.py
tests/test_ops_agents.py
```

### Docs

```text
docs/interfaces.md
README.md
```

Update after implementation:

- Agent Roster current fields
- Dependency Map current fields
- Operator Actions if Add Next Agent ships
- screenshots after visual QA

---

## Tests / Validation

### Backend unit tests

Add tests for:

1. Agent metadata merge
   - on-disk profile appears even with no tasks
   - task-history assignee appears even if profile missing
   - availability is `running`, `queued`, `blocked`, `stale`, `idle`, or `unconfigured` as expected

2. Dependency summary
   - no dependencies → `state=none`
   - incomplete parent → `state=waiting`
   - all parents done + children exist → `state=unlocks`
   - fan-out children dedupe `next_assignees`
   - parent counts and child counts correct

3. Ticket detail rich dependencies
   - still includes old `parents` and `children` ID arrays
   - includes `parent_tasks`, `child_tasks`, and `summary`

4. Child creation endpoint, if Phase 3 included
   - child task created with `task_links(parent_id, child_id)`
   - child starts as `todo` when parent not done
   - child starts as `ready` when parent already done
   - invalid parent returns 400/404

### Commands

Run from repo root:

```bash
python3 -m py_compile dashboard/plugin_api.py
node --check dashboard/dist/index.js
python3 -m unittest discover -s tests -v
```

### Manual API validation

With dashboard running on 9119:

```bash
curl -sS http://127.0.0.1:9119/api/plugins/h-ops/agents | python3 -m json.tool
curl -sS http://127.0.0.1:9119/api/plugins/h-ops/ops-board | python3 -m json.tool
curl -sS http://127.0.0.1:9119/api/plugins/h-ops/workflow-graph | python3 -m json.tool
```

For child creation after Phase 3:

```bash
curl -sS -X POST http://127.0.0.1:9119/api/plugins/h-ops/tickets/<id>/children \
  -H 'Content-Type: application/json' \
  -d '{"title":"Build frontend UI","body":"Use parent output","assignee":"frontend"}' \
  | python3 -m json.tool
```

### Browser visual QA

Use a real dashboard instance and browser QA. Check:

1. Agent strip
   - profiles fit without overflow
   - idle/queued/running/blocked/stale states are visually distinct
   - small screens do not collapse into unreadable chips

2. Board card dependency badges
   - no visual clutter when many cards exist
   - badge text remains readable
   - waiting/unlocks states are obvious

3. Dossier chain rail
   - selected/current ticket is clearly highlighted
   - parent/child statuses are clear
   - long titles wrap safely
   - empty dependency state is not noisy

4. Add Next Agent modal, if included
   - assignee dropdown uses known profiles
   - textarea is large enough
   - success refreshes chain rail
   - errors are shown inline

5. Console
   - no JS errors
   - no failed API calls

---

## Risks / Tradeoffs

### Risk: Profile “status” semantics can be misleading

`gateway_running` may not mean a profile is actively available for Kanban dispatch. Current dispatcher runs in the gateway. Avoid labeling profile gateway state as definitive worker availability. Prefer terms like:

- `configured`
- `has env`
- `recent activity`
- `queued/running/blocked workload`

### Risk: Graph view can become complex quickly

A full DAG layout can become a project by itself. Start with:

1. card badges
2. dossier chain rail
3. simple graph endpoint
4. simple graph view

Do not start with drag-and-drop graph editing.

### Risk: Performance on large boards

Dependency summary can cause N+1 queries if computed per ticket. For small boards this is okay, but for larger boards optimize with batch queries:

- fetch visible task IDs
- fetch all parent/child links for those IDs
- fetch linked task rows in one query

Initial implementation can be straightforward, but keep helper boundaries so batch optimization is easy.

### Risk: H-OPS is currently plain dist JS, not source-built React

`dashboard/dist/index.js` appears to be hand-authored/distributed JS. Changes must be careful and syntax-checked with `node --check`. Avoid large refactors that make the file hard to maintain.

### Risk: Mutating operations need clear operator affordance

Creating child tasks has real cost implications because ready assigned tasks may trigger worker runs. UI should clearly say:

```text
This will create a Kanban task. It may dispatch automatically when dependencies are satisfied and gateway dispatch is running.
```

For Phase 3, child task creation should probably default to `todo` via parent dependency and only become `ready` after parent completion. If parent is already done, warn that it may dispatch immediately.

---

## Open Questions

1. Should the first implementation include only read-only observability, or also “Add next agent”?
   - Recommendation: read-only first, Add Next Agent second.

2. Should graph view be a primary tab or a collapsible panel inside the board?
   - Recommendation: start as a panel/toggle after AgentStrip; promote to tab if it proves useful.

3. Should dependency summaries be recursive or immediate-only?
   - Recommendation: immediate-only for board cards and dossier v1; graph endpoint can support depth later.

4. Should H-OPS support linking two existing tasks in v1?
   - Recommendation: not in first PR. Creating a new child from a selected parent is safer and easier to understand.

5. Should child tasks inherit parent workspace/tenant/skills?
   - Recommendation: inherit `tenant`; do not inherit workspace or skills by default unless the UI explicitly says so. Add optional controls later.

---

## Recommended First PR Scope

Implement **Phase 1 + Phase 2 only**:

- Backend:
  - richer `/agents`
  - `dependency_summary` on board tickets
  - rich dependency objects in ticket detail
  - optional read-only `/workflow-graph` endpoint

- Frontend:
  - richer AgentStrip
  - card DependencyBadge
  - dossier ChainRail

- Tests:
  - agent availability tests
  - dependency summary tests

- Validation:
  - syntax checks
  - unit tests
  - browser visual QA

Do **not** include child creation or graph editing in the first PR. That keeps the initial change safe, observable, and easier to review.
