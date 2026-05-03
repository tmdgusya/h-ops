# H-OPS Interface Map

H-OPS is an operator-facing read model over Hermes Kanban.

## Mental model

Kanban remains the kernel/source-of-truth:

- `tasks` = tickets / missions
- `task_runs` = agent attempts / execution traces
- `task_events` = operational signal feed
- `task_links` = dependency graph
- `task_comments` = operator/agent notes
- profiles/assignees = agent roster

H-OPS is the cockpit layer that makes that operational state legible.

## Mission Control

Purpose: show the global operational picture without opening individual Kanban cards.

Current data:

- status counts: triage/todo/ready/running/blocked/done
- active count: ready + running + blocked
- operational health summary
- blocked/unassigned/stale/error counts
- profile roster summary
- filter/search controls

Future controls:

- dispatch ready queue
- pause/resume auto-dispatch
- filter by tenant/profile/workspace
- show only tasks needing operator input

## Ticket Intel / Dossier

Purpose: answer “what is this agent task doing?” directly.

Current fields:

- ticket id/title/body/status/priority
- assignee/profile
- current run id
- current run status/outcome
- heartbeat age and interpretation
- ticket-level health/risk summary
- output/result preview
- worker log preview
- event timeline scoped to ticket
- run history table
- detected text/Markdown artifacts

Future controls:

- retry/requeue
- unblock with comment
- add operator note
- fork ticket into follow-up
- open original Kanban drawer
- open Hermes worker context/log

## Agent Roster

Purpose: profile-centric view of Hermes agents.

Current fields:

- profile name
- source: configured profile, task history, run history
- assigned task count
- ready/running/blocked counts
- last seen timestamp when available

Future controls:

- filter board by profile
- open profile config
- route new ticket to profile
- mark profile unavailable / drain queue

## Dependency Map

Purpose: make multi-agent task graphs visible.

Future data:

- nodes: tasks
- edges: parent → child from `task_links`
- node color by status
- node badges: assignee, priority, blockers
- critical path highlighting

## Event Stream

Purpose: SOC-style signal feed for the board.

Current data:

- task event id
- task id/title/assignee/status
- event kind
- payload JSON summary
- run id
- created_at

Future controls:

- live WebSocket tail
- severity mapping
- filter by event kind/profile/task
- pin event to ticket dossier

## Operator Actions

Purpose: make H-OPS not only observational but operational.

Current safe actions:

- create ticket
- assign/reassign
- copy ticket ID
- copy ticket link
- open output/logs
- copy/download output/log content

Planned actions:

- retry
- requeue
- reopen
- archive
- add comment
- unblock / request clarification
- create dependency

Safety:

- H-OPS should preserve Kanban event history.
- Mutating actions need explicit operator affordance.
- Do not expose fake buttons that appear to mutate state but do nothing.
