# H-OPS UX Plan

## Product thesis

H-OPS should feel less like a Trello clone and more like a command center for Hermes agents.

The user should not have to inspect raw Kanban internals to answer:

> What are my agents doing, is anything unhealthy, and what should I do next?

## Current interaction model

1. Open `/h-ops` in the Hermes dashboard.
2. Read the top health summary.
3. Filter/search for tickets that need attention.
4. Scan the six-lane Kanban mirror.
5. Click a card to open the selected-ticket dossier.
6. Inspect run health, output, logs, events, and history.
7. Take safe operator actions such as copy/open/download/reassign.

## Design direction

Use a Kanban-like board as the primary surface, but upgrade each card into an Ops card:

- columns remain familiar: Triage, Todo, Ready, Running, Blocked, Done
- each card foregrounds assignment, run state, heartbeat, progress, and latest output
- active work gets motion/effects: pulse, scanning line, progress bar
- clicking a card opens an Ops dossier focused on worker activity/output

## Must-have concepts

### 1. Ops health

The dashboard should interpret state instead of just displaying raw status.

Examples:

- completed + old heartbeat = acceptable historical signal
- running + stale heartbeat = critical issue
- ready + no assignee = warning
- blocked = operator input required

### 2. Assignment system

H-OPS needs assignment controls using known Hermes profiles:

- create task with assignee dropdown
- reassign ticket from card/dossier
- show `UNASSIGNED` as a warning state because unassigned tasks will not dispatch

### 3. Worker log/output visibility

Surface:

- latest run summary
- latest run outcome/error
- heartbeat freshness
- latest event payload
- short output preview on card
- richer output/log panel in dossier

### 4. Progress/effects

Progress heuristic v0:

- done/archived = 100%
- blocked = 55%
- running = 35–86%, increasing slowly based on age, capped until completion
- ready = 20%
- todo = 10%
- triage = 5%

Visual effects:

- running cards scan/shimmer
- blocked cards show red incident edge
- stale running cards show amber warning
- done cards are calm/green

### 5. Output readability

Dossier should show:

- mission brief
- current run
- latest output/result
- log preview
- run history
- event stream
- dependencies
- operator actions

## Next UX milestones

1. Retry/requeue/reopen flows with real backend state transitions.
2. Dense table mode for operators with large queues.
3. Event severity mapping and live tail mode.
4. Dependency graph with critical path.
5. Audit trail for state-changing actions.
