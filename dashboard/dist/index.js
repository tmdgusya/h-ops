(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const hooks = SDK.hooks;
  const h = React.createElement;
  const C = SDK.components || {};
  const Button = C.Button || function (props) { return h("button", props, props.children); };
  const Select = C.Select || function (props) { return h("select", props, props.children); };
  const SelectOption = C.SelectOption || function (props) { return h("option", props, props.children); };

  function api(path, options) {
    return SDK.fetchJSON("/api/plugins/h-ops" + path, options);
  }

  function request(path, method, body) {
    return api(path, {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    try { return new Date(Number(ts) * 1000).toLocaleString(); }
    catch (_err) { return String(ts); }
  }

  function age(seconds) {
    if (seconds == null) return "no signal";
    if (seconds < 60) return seconds + "s ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    return Math.floor(seconds / 86400) + "d ago";
  }

  function shortId(id) {
    if (!id) return "—";
    const s = String(id);
    return s.length > 12 ? s.slice(0, 8) + "…" : s;
  }

  function statusClass(status) {
    return "hops-pill hops-status-" + String(status || "unknown").replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
  }

  function normalizeSelect(fn) {
    return function (valueOrEvent) {
      const value = valueOrEvent && valueOrEvent.target ? valueOrEvent.target.value : valueOrEvent;
      fn(value || "");
    };
  }

  function AssigneeSelect(props) {
    return h(Select, {
      value: props.value || "",
      onValueChange: normalizeSelect(props.onChange),
      onChange: normalizeSelect(props.onChange),
      className: props.className || "hops-select",
      title: props.title || "Assign a Hermes profile",
      "aria-label": props.label || "Assignee profile",
    },
      h(SelectOption, { value: "" }, props.emptyLabel || "— unassigned —"),
      (props.assignees || []).map(function (name) {
        return h(SelectOption, { key: name, value: name }, name);
      })
    );
  }

  function Metric(props) {
    return h("div", { className: "hops-metric" },
      h("span", null, props.label),
      h("strong", null, props.value),
      h("small", null, props.hint || "")
    );
  }

  function healthClass(level) {
    return "hops-health-level-" + String(level || "healthy").toLowerCase();
  }

  function OpsHealthPanel({ health }) {
    health = health || { level: "healthy", summary: "No active operational issues", next_action: "None required", alerts: [], counts: {} };
    const counts = health.counts || {};
    const alerts = health.alerts || [];
    return h("section", { className: "hops-health-panel " + healthClass(health.level) },
      h("div", { className: "hops-health-main" },
        h("p", { className: "hops-kicker" }, "OPS HEALTH"),
        h("h2", null, String(health.level || "healthy").toUpperCase()),
        h("p", null, health.summary || "No active operational issues"),
        h("div", { className: "hops-next-action" }, "Next action: ", h("b", null, health.next_action || "None required"))
      ),
      h("div", { className: "hops-health-counts" },
        h(Metric, { label: "Failed", value: counts.failed_attempts || 0, hint: "latest run errors" }),
        h(Metric, { label: "Blocked", value: counts.blocked_tickets || 0, hint: "operator input" }),
        h(Metric, { label: "Stale", value: counts.stale_workers || 0, hint: "worker signal" }),
        h(Metric, { label: "Unassigned", value: counts.unassigned_ready || 0, hint: "ready tickets" })
      ),
      h("div", { className: "hops-alert-list" },
        alerts.length ? alerts.slice(0, 4).map(function (alert, index) {
          return h("div", { key: index, className: "hops-alert-row hops-alert-" + (alert.level || "notice") },
            h("i", null),
            h("span", null, alert.label || "Alert"),
            h("small", null, alert.detail || "")
          );
        }) : h("div", { className: "hops-alert-row hops-alert-healthy" }, h("i", null), h("span", null, "No active alerts"), h("small", null, "Board is quiet."))
      )
    );
  }

  function DossierHealthPanel({ health }) {
    health = health || { level: "healthy", interpretation: "No active operational issue detected.", next_action: "None required", alerts: [] };
    return h("section", { className: "hops-dossier-health " + healthClass(health.level) },
      h("div", null,
        h("p", { className: "hops-kicker" }, "RUN HEALTH"),
        h("h3", null, String(health.level || "healthy").toUpperCase(), " · ", health.run_status || "unknown"),
        h("p", null, health.interpretation || "No active operational issue detected.")
      ),
      h("div", { className: "hops-health-facts" },
        h("span", null, "Freshness: ", h("b", null, health.worker_freshness || "unknown")),
        h("span", null, "Next: ", h("b", null, health.next_action || "None required"))
      ),
      (health.alerts || []).length ? h("div", { className: "hops-alert-list" }, (health.alerts || []).map(function (alert, index) {
        return h("div", { key: index, className: "hops-alert-row hops-alert-" + (alert.level || "notice") }, h("i", null), h("span", null, alert.label), h("small", null, alert.detail || ""));
      })) : null
    );
  }

  function BoardFilterBar({ filters, onChange, assignees, resultCount, totalCount }) {
    function set(key, value) { onChange(Object.assign({}, filters, { [key]: value })); }
    function reset() { onChange({ q: "", status: "", assignee: "", problems: false, unassigned: false }); }
    return h("section", { className: "hops-filter-bar" },
      h("input", { className: "hops-input", value: filters.q || "", onChange: function (e) { set("q", e.target.value); }, placeholder: "Search tickets, output, IDs…" }),
      h("select", { className: "hops-select", value: filters.status || "", onChange: function (e) { set("status", e.target.value); } },
        h("option", { value: "" }, "All statuses"),
        ["triage", "todo", "ready", "running", "blocked", "done"].map(function (s) { return h("option", { key: s, value: s }, s); })
      ),
      h("select", { className: "hops-select", value: filters.assignee || "", onChange: function (e) { set("assignee", e.target.value); } },
        h("option", { value: "" }, "All assignees"),
        h("option", { value: "__unassigned" }, "Unassigned"),
        (assignees || []).map(function (name) { return h("option", { key: name, value: name }, name); })
      ),
      h("label", { className: "hops-check" }, h("input", { type: "checkbox", checked: !!filters.problems, onChange: function (e) { set("problems", e.target.checked); } }), " problems only"),
      h("label", { className: "hops-check" }, h("input", { type: "checkbox", checked: !!filters.unassigned, onChange: function (e) { set("unassigned", e.target.checked); } }), " unassigned"),
      h("div", { className: "hops-filter-count" }, "Showing ", h("b", null, resultCount), " / ", totalCount),
      h(Button, { onClick: reset }, "Reset")
    );
  }

  function ticketNeedsAttention(ticket) {
    const level = ((ticket.health || {}).level || "healthy").toLowerCase();
    return level === "warning" || level === "critical" || ticket.status === "blocked" || (ticket.status === "ready" && !ticket.assignee) || !!((ticket.latest_run || {}).error);
  }

  function filterColumns(columns, filters) {
    const q = String(filters.q || "").trim().toLowerCase();
    const active = !!(q || filters.status || filters.assignee || filters.problems || filters.unassigned);
    return (columns || []).map(function (column) {
      const tickets = (column.tickets || []).filter(function (ticket) {
        if (filters.status && ticket.status !== filters.status) return false;
        if (filters.assignee === "__unassigned" && ticket.assignee) return false;
        if (filters.assignee && filters.assignee !== "__unassigned" && ticket.assignee !== filters.assignee) return false;
        if (filters.unassigned && ticket.assignee) return false;
        if (filters.problems && !ticketNeedsAttention(ticket)) return false;
        if (q) {
          const hay = [ticket.id, ticket.title, ticket.body, ticket.output_preview, ticket.assignee, ticket.status].join(" ").toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        return true;
      });
      return Object.assign({}, column, { tickets: tickets, filtered: active });
    });
  }

  function ProgressBar({ ticket }) {
    const progress = ticket.progress || { percent: 0, label: "unknown" };
    return h("div", { className: "hops-progress-wrap", title: progress.label },
      h("div", { className: "hops-progress-label" }, "Progress"),
      h("div", { className: "hops-progress-line" },
        h("i", { style: { width: Math.max(0, Math.min(100, progress.percent || 0)) + "%" } })
      ),
      h("div", { className: "hops-progress-copy" },
        h("span", null, progress.label),
        h("b", null, (progress.percent || 0) + "%")
      )
    );
  }

  function Composer({ assignees, onCreated }) {
    const [open, setOpen] = hooks.useState(false);
    const [title, setTitle] = hooks.useState("");
    const [body, setBody] = hooks.useState("");
    const [assignee, setAssignee] = hooks.useState("");
    const [priority, setPriority] = hooks.useState(0);
    const [triage, setTriage] = hooks.useState(false);
    const [busy, setBusy] = hooks.useState(false);
    const [error, setError] = hooks.useState(null);

    function submit() {
      const t = title.trim() || body.trim().split("\n")[0];
      if (!t) { setError("Title or mission brief is required."); return; }
      setBusy(true); setError(null);
      request("/tickets", "POST", {
        title: t.slice(0, 160),
        body: body.trim() || title.trim(),
        assignee: assignee || null,
        priority: Number(priority) || 0,
        triage: !!triage,
      }).then(function (res) {
        setTitle(""); setBody(""); setAssignee(""); setPriority(0); setTriage(false);
        onCreated(res.ticket && res.ticket.id);
      }).catch(function (err) { setError(err.message || String(err)); })
        .finally(function () { setBusy(false); });
    }

    if (!open) {
      return h("section", { className: "hops-composer hops-composer-closed" },
        h(Button, { onClick: function () { setOpen(true); } }, "+ New Ops Ticket")
      );
    }
    return h("section", { className: "hops-composer" },
      h("div", { className: "hops-composer-head" },
        h("div", null,
          h("p", { className: "hops-kicker" }, "OPERATOR COMPOSER"),
          h("h2", null, "Create and route agent work")
        ),
        h(Button, { onClick: function () { setOpen(false); } }, "Collapse")
      ),
      h("div", { className: "hops-composer-grid" },
        h("input", {
          value: title,
          onChange: function (e) { setTitle(e.target.value); },
          placeholder: "Ticket title / first line",
          className: "hops-input hops-title-input",
        }),
        h(AssigneeSelect, { value: assignee, onChange: setAssignee, assignees: assignees, className: "hops-select" }),
        h("input", {
          type: "number",
          value: String(priority),
          onChange: function (e) { setPriority(e.target.value); },
          className: "hops-input hops-priority-input",
          title: "Priority",
        })
      ),
      h("textarea", {
        value: body,
        onChange: function (e) { setBody(e.target.value); },
        placeholder: "Mission brief: what should the agent do, what does success look like, what context matters?",
        className: "hops-textarea",
        rows: 5,
      }),
      h("div", { className: "hops-composer-actions" },
        h("label", { className: "hops-check" },
          h("input", { type: "checkbox", checked: triage, onChange: function (e) { setTriage(e.target.checked); } }),
          " park in triage"
        ),
        h("span", { className: assignee ? "hops-route-ok" : "hops-route-warn" },
          assignee ? "Will route to " + assignee : "Unassigned tickets will not dispatch"
        ),
        error ? h("span", { className: "hops-error" }, error) : null,
        h(Button, { onClick: submit, disabled: busy }, busy ? "Creating…" : "Create ticket")
      )
    );
  }

  function TicketCard({ ticket, assignees, selected, onSelect, onAssigned }) {
    const run = ticket.latest_run || {};
    const progress = ticket.progress || {};
    const live = ticket.status === "running";
    const blocked = ticket.status === "blocked";
    const stale = progress.stale;
    return h("article", {
      className: "hops-ticket-card" + (selected ? " is-selected" : "") + (live ? " is-live" : "") + (blocked ? " is-blocked" : "") + (stale ? " is-stale" : ""),
    },
      h("button", { className: "hops-ticket-open", onClick: function () { onSelect(ticket.id); } },
        h("div", { className: "hops-card-top" },
          h("span", { className: statusClass(ticket.status) }, ticket.status || "unknown"),
          h("span", { className: ticket.assignee ? "hops-assigned" : "hops-unassigned" }, ticket.assignee || "UNASSIGNED")
        ),
        h("h3", null, ticket.title || ticket.id),
        h(ProgressBar, { ticket: ticket }),
        h("p", { className: "hops-output-preview" }, ticket.output_preview || "No output yet. Waiting for worker signal."),
        h("div", { className: "hops-card-meta" },
          h("span", null, shortId(ticket.id)),
          h("span", null, run.status ? "run " + run.status : "no run"),
          h("span", null, "heartbeat " + age(ticket.heartbeat_age_seconds))
        )
      ),
      h("div", { className: "hops-card-assign" },
        h(AssigneeSelect, {
          value: ticket.assignee || "",
          onChange: function (value) { onAssigned(ticket.id, value); },
          assignees: assignees,
          className: "hops-select hops-card-select",
          emptyLabel: "unassigned",
        })
      )
    );
  }

  function OpsColumn({ column, assignees, selectedId, onSelect, onAssigned }) {
    const labels = {
      triage: "raw ideas / needs spec",
      todo: "waiting / dependency queue",
      ready: "assigned and dispatchable",
      running: "claimed by worker",
      blocked: "operator input needed",
      done: "completed output",
    };
    return h("section", { className: "hops-column hops-column-" + column.name },
      h("div", { className: "hops-column-head" },
        h("div", null,
          h("h2", null, column.name),
          h("p", null, labels[column.name] || "")
        ),
        h("strong", null, (column.tickets || []).length + " ticket" + ((column.tickets || []).length === 1 ? "" : "s"))
      ),
      h("div", { className: "hops-card-stack" },
        (column.tickets || []).length ? column.tickets.map(function (ticket) {
          return h(TicketCard, {
            key: ticket.id,
            ticket: ticket,
            assignees: assignees,
            selected: selectedId === ticket.id,
            onSelect: onSelect,
            onAssigned: onAssigned,
          });
        }) : h("div", { className: "hops-empty" }, column.filtered ? "No matching tickets in " + column.name : "No tickets in " + column.name)
      )
    );
  }

  function looksMarkdown(text, label) {
    const source = String(text || "");
    const name = String(label || "").toLowerCase();
    return /\.(md|markdown|mdx)$/.test(name) || /(^|\n)\s{0,3}#{1,6}\s+/.test(source) || /(^|\n)\s*[-*+]\s+\S/.test(source) || /```/.test(source) || /(^|\n)\|.+\|/.test(source);
  }

  function viewerModeFor(item) {
    if (!item) return "plain";
    const title = item.title || item.name || item.path || "";
    if (item.mode) return item.mode;
    if (looksMarkdown(item.content, title)) return "markdown";
    if (/\.(log)$/.test(String(title).toLowerCase())) return "log";
    return "plain";
  }

  function InlineText({ text }) {
    const parts = String(text || "").split(/(`[^`]+`)/g);
    return h(React.Fragment, null, parts.map(function (part, i) {
      if (/^`[^`]+`$/.test(part)) return h("code", { key: i }, part.slice(1, -1));
      return part;
    }));
  }

  function MarkdownRender({ text }) {
    const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    const nodes = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^```\s*(.*)$/);
      if (fence) {
        const lang = fence[1] || "";
        const body = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) { body.push(lines[i]); i += 1; }
        if (i < lines.length) i += 1;
        nodes.push(h("pre", { key: nodes.length, className: "hops-md-code" }, h("code", null, body.join("\n")), lang ? h("small", null, lang) : null));
        continue;
      }
      if (!line.trim()) { i += 1; continue; }
      const head = line.match(/^(#{1,6})\s+(.+)$/);
      if (head) {
        const level = Math.min(4, Math.max(2, head[1].length + 1));
        nodes.push(h("h" + level, { key: nodes.length }, h(InlineText, { text: head[2] })));
        i += 1;
        continue;
      }
      if (/^\s*[-*+]\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*[-*+]\s+/, "")); i += 1;
        }
        nodes.push(h("ul", { key: nodes.length }, items.map(function (item, idx) { return h("li", { key: idx }, h(InlineText, { text: item })); })));
        continue;
      }
      if (/^\s*\d+[.)]\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*\d+[.)]\s+/, "")); i += 1;
        }
        nodes.push(h("ol", { key: nodes.length }, items.map(function (item, idx) { return h("li", { key: idx }, h(InlineText, { text: item })); })));
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        const quotes = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) { quotes.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
        nodes.push(h("blockquote", { key: nodes.length }, quotes.join("\n")));
        continue;
      }
      const paras = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^(#{1,6})\s+/.test(lines[i]) && !/^```/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) { paras.push(lines[i]); i += 1; }
      nodes.push(h("p", { key: nodes.length }, h(InlineText, { text: paras.join(" ") })));
    }
    return h("div", { className: "hops-markdown-body" }, nodes.length ? nodes : h("p", null, "No content."));
  }

  function ViewerModal({ item, onClose }) {
    const [tab, setTab] = hooks.useState(viewerModeFor(item));
    if (!item) return null;
    const content = item.content || "";
    function copy() {
      if (navigator.clipboard) navigator.clipboard.writeText(content).catch(function () {});
    }
    return h("div", { className: "hops-modal-backdrop", role: "dialog", "aria-modal": "true", onClick: onClose },
      h("section", { className: "hops-viewer-modal", onClick: function (e) { e.stopPropagation(); } },
        h("div", { className: "hops-viewer-head" },
          h("div", { className: "hops-viewer-titleblock" },
            h("div", { className: "hops-viewer-kind" }, item.kind || "OUTPUT VIEWER"),
            h("h1", null, item.title || item.name || "Output"),
            item.path ? h("code", { className: "hops-viewer-path" }, item.path) : null
          ),
          h("div", { className: "hops-viewer-actions" },
            h(Button, { onClick: function () { setTab("markdown"); }, className: tab === "markdown" ? "is-active" : "" }, "Rendered"),
            h(Button, { onClick: function () { setTab("plain"); }, className: tab === "plain" ? "is-active" : "" }, "Raw"),
            h(Button, { onClick: copy }, "Copy"),
            h(Button, { onClick: onClose }, "Close")
          )
        ),
        item.truncated ? h("div", { className: "hops-viewer-warn" }, "Large file/output truncated for dashboard viewing.") : null,
        h("div", { className: "hops-viewer-body" }, tab === "markdown" ? h(MarkdownRender, { text: content }) : h("pre", null, content || "No content."))
      )
    );
  }

  function OutputPanel({ title, item, onOpen }) {
    const content = item && item.content ? item.content : "";
    function copy() { if (content && navigator.clipboard) navigator.clipboard.writeText(content).catch(function () {}); }
    function download() {
      if (!content) return;
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = ((item && (item.title || item.name)) || title || "hops-output").replace(/[^a-z0-9가-힣_.-]+/gi, "-") + ".txt";
      a.click();
      URL.revokeObjectURL(url);
    }
    const isLog = /log/i.test(title || "");
    const emptyCopy = isLog
      ? "No worker log content was recorded for this attempt. This can happen when the task completed through backend events only, logging is disabled, or the log file has not been created yet."
      : "No output has been recorded yet. When a worker produces a result, it will appear here with copy/download controls.";
    return h("section", { className: "hops-output-panel" },
      h("div", { className: "hops-panel-bar" },
        h("div", { className: "hops-panel-title" }, title),
        h("div", { className: "hops-panel-actions" },
          h(Button, { onClick: copy, disabled: !content }, "Copy"),
          h(Button, { onClick: download, disabled: !content }, "Download"),
          h(Button, { onClick: function () { onOpen(item); }, disabled: !content }, isLog ? "Open worker logs" : (looksMarkdown(content, title) ? "Open rendered output" : "Open output"))
        )
      ),
      h("pre", null, content || emptyCopy)
    );
  }

  function TicketActionsBar({ ticket, outputItem, logItem, onOpen }) {
    const [copied, setCopied] = hooks.useState("");
    function copyText(label, text) {
      if (!text || !navigator.clipboard) return;
      navigator.clipboard.writeText(text).then(function () { setCopied(label); setTimeout(function () { setCopied(""); }, 1400); }).catch(function () {});
    }
    const url = window.location.origin + window.location.pathname + "?ticket=" + encodeURIComponent(ticket.id || "");
    return h("section", { className: "hops-actions-bar" },
      h("div", null,
        h("p", { className: "hops-kicker" }, "OPERATOR ACTIONS"),
        h("span", null, copied ? "Copied " + copied : "Safe actions only — no state mutation")
      ),
      h("div", { className: "hops-action-buttons" },
        h(Button, { onClick: function () { copyText("ticket ID", ticket.id); } }, "Copy ID"),
        h(Button, { onClick: function () { copyText("link", url); } }, "Copy Link"),
        h(Button, { onClick: function () { onOpen(outputItem); }, disabled: !(outputItem && outputItem.content) }, "Open Output"),
        h(Button, { onClick: function () { onOpen(logItem); }, disabled: !(logItem && logItem.content) }, "Open Logs"),
        h(Button, { disabled: true, title: "Retry/requeue needs a backend state transition endpoint." }, "Retry Soon")
      )
    );
  }

  function RunHistoryTable({ runs, events }) {
    runs = runs || [];
    events = events || [];
    return h("div", { className: "hops-run-table-wrap" },
      runs.length ? h("table", { className: "hops-run-table" },
        h("thead", null, h("tr", null,
          h("th", null, "Attempt"), h("th", null, "Profile"), h("th", null, "Status"), h("th", null, "Outcome"), h("th", null, "Heartbeat"), h("th", null, "Summary")
        )),
        h("tbody", null, runs.slice(0, 10).map(function (r) {
          const hb = r.last_heartbeat_at || r.completed_at || r.started_at;
          return h("tr", { key: r.id },
            h("td", null, "#" + r.id),
            h("td", null, r.profile || "profile?"),
            h("td", null, r.status || "—"),
            h("td", null, r.outcome || (r.error ? "error" : "open")),
            h("td", null, fmtTime(hb)),
            h("td", null, r.error || r.summary || "—")
          );
        }))
      ) : h("div", { className: "hops-empty" }, "No runs yet."),
      h("div", { className: "hops-event-timeline" },
        events.slice(0, 8).map(function (e) {
          return h("div", { key: e.id, className: "hops-event-row" },
            h("b", null, e.kind || "event"),
            h("span", null, e.summary || JSON.stringify(e.payload || {})),
            h("small", null, fmtTime(e.created_at))
          );
        })
      )
    );
  }

  function Dossier({ ticketId, assignees, onAssigned, refreshKey, selectionNonce }) {
    const [data, setData] = hooks.useState(null);
    const [error, setError] = hooks.useState(null);
    const [viewerItem, setViewerItem] = hooks.useState(null);
    const [dossierOpen, setDossierOpen] = hooks.useState(false);

    hooks.useEffect(function () {
      if (ticketId && selectionNonce > 0) setDossierOpen(true);
    }, [ticketId, selectionNonce]);

    hooks.useEffect(function () {
      if (!ticketId) { setData(null); setViewerItem(null); setDossierOpen(false); return; }
      let cancelled = false;
      setError(null);
      api("/tickets/" + encodeURIComponent(ticketId))
        .then(function (res) { if (!cancelled) setData(res); })
        .catch(function (err) { if (!cancelled) setError(err.message || String(err)); });
      return function () { cancelled = true; };
    }, [ticketId, refreshKey]);

    if (!ticketId) return h("section", { className: "hops-selected-strip" },
      h("div", null,
        h("p", { className: "hops-kicker" }, "SELECTED TICKET"),
        h("h2", null, "Click a card to open its dossier")
      ),
      h("p", null, "Dossier, output, logs, and run history now open as a large popup instead of living under the board.")
    );
    if (error) return h("section", { className: "hops-selected-strip is-error" }, h("h2", null, "Dossier error"), h("p", null, error));
    if (!data) return h("section", { className: "hops-selected-strip" }, h("h2", null, "Loading selected ticket…"));

    const ticket = data.ticket || {};
    const run = ticket.latest_run || {};
    const log = ticket.log || {};
    const currentOutput = ticket.result || run.summary || ticket.output_preview || "";
    const logContent = log.content || log.preview || "";
    const outputItem = { kind: "CURRENT OUTPUT", title: ticket.title || ticket.id, content: currentOutput, mode: looksMarkdown(currentOutput, ticket.title) ? "markdown" : "plain" };
    const logItem = { kind: "WORKER LOG", title: (ticket.id || "ticket") + " worker log", path: log.path, content: logContent, mode: "plain", truncated: log.truncated };
    const dossierBody = h("aside", { className: "hops-dossier" },
        h("div", { className: "hops-dossier-head" },
          h("p", { className: "hops-kicker" }, "SELECTED TICKET DOSSIER / WORKER LOGS"),
          h("p", { className: "hops-dossier-note" }, "Showing one selected card from the board above — not the full Done list."),
          h("span", { className: statusClass(ticket.status) }, ticket.status),
          h("h2", null, ticket.title || ticket.id),
          h("p", null, ticket.body || "No mission brief."),
          h("div", { className: "hops-dossier-assign" },
            h("span", null, "Assign"),
            h(AssigneeSelect, { value: ticket.assignee || "", onChange: function (v) { onAssigned(ticket.id, v); }, assignees: assignees, className: "hops-select" })
          )
        ),
        h(DossierHealthPanel, { health: ticket.health }),
        h(TicketActionsBar, { ticket: ticket, outputItem: outputItem, logItem: logItem, onOpen: setViewerItem }),
        h(ProgressBar, { ticket: ticket }),
        h("div", { className: "hops-dossier-metrics" },
          h(Metric, { label: "Current run", value: run.id || "—", hint: run.status || "no run" }),
          h(Metric, { label: "Outcome", value: run.outcome || ticket.status || "—", hint: run.error || "latest attempt" }),
          h(Metric, { label: "Heartbeat", value: age(ticket.heartbeat_age_seconds), hint: "worker signal freshness" }),
          h(Metric, { label: "Log", value: log.exists ? Math.round((log.size_bytes || 0) / 1024) + " KB" : "none", hint: log.path || "worker has not spawned" })
        ),
        h(OutputPanel, { title: "Current output", item: outputItem, onOpen: setViewerItem }),
        h(OutputPanel, { title: "Worker log preview", item: logItem, onOpen: setViewerItem }),
        (data.artifacts || []).length ? h("section", { className: "hops-output-panel hops-artifacts" },
          h("div", { className: "hops-panel-title" }, "Detected files"),
          h("div", { className: "hops-artifact-list" }, (data.artifacts || []).map(function (artifact) {
            const item = { kind: "MARKDOWN / TEXT FILE", title: artifact.name, path: artifact.path, content: artifact.content, mode: looksMarkdown(artifact.content, artifact.name) ? "markdown" : "plain", truncated: artifact.truncated };
            return h("button", { key: artifact.path, className: "hops-artifact", onClick: function () { setViewerItem(item); } },
              h("strong", null, artifact.name),
              h("span", null, artifact.path),
              h("small", null, artifact.suffix + " · " + Math.round((artifact.size_bytes || 0) / 1024) + " KB")
            );
          }))
        ) : null,
        h("section", { className: "hops-output-panel" },
          h("div", { className: "hops-panel-title" }, "Run history & events"),
          h(RunHistoryTable, { runs: data.runs || [], events: data.events || [] })
        )
      );
    return h(React.Fragment, null,
      h("section", { className: "hops-selected-strip" },
        h("div", null,
          h("p", { className: "hops-kicker" }, "SELECTED TICKET"),
          h("h2", null, ticket.title || ticket.id),
          h("p", null, "Click the selected card or Open dossier to inspect output, logs, run history, and events in a large popup.")
        ),
        h("div", { className: "hops-selected-actions" },
          h("span", { className: statusClass(ticket.status) }, ticket.status),
          h(Button, { onClick: function () { setDossierOpen(true); } }, "Open dossier")
        )
      ),
      dossierOpen ? h("div", { className: "hops-dossier-backdrop", role: "dialog", "aria-modal": "true", onClick: function () { setDossierOpen(false); } },
        h("section", { className: "hops-dossier-modal", onClick: function (e) { e.stopPropagation(); } },
          h("div", { className: "hops-dossier-modal-head" },
            h("div", null,
              h("div", { className: "hops-viewer-kind" }, "SELECTED TICKET DOSSIER"),
              h("h1", null, ticket.title || ticket.id),
              h("p", null, "Worker output, logs, run history, events, and assignment controls")
            ),
            h("div", { className: "hops-viewer-actions" },
              h(Button, { onClick: function () { setDossierOpen(false); } }, "Close")
            )
          ),
          h("div", { className: "hops-dossier-modal-body" }, dossierBody)
        )
      ) : null,
      h(ViewerModal, { item: viewerItem, onClose: function () { setViewerItem(null); } })
    );
  }

  function StatusStrip({ counts }) {
    const statuses = ["triage", "todo", "ready", "running", "blocked", "done"];
    return h("section", { className: "hops-status-strip", "aria-label": "Kanban status counts" },
      statuses.map(function (status) {
        const count = Number((counts || {})[status] || 0);
        return h("div", { key: status, className: "hops-status-tile hops-status-tile-" + status + (count ? " has-tickets" : "") },
          h("span", null, status),
          h("strong", null, count),
          h("small", null, count === 1 ? "ticket" : "tickets")
        );
      })
    );
  }

  function AgentStrip({ agents }) {
    return h("section", { className: "hops-agent-strip" },
      (agents || []).map(function (agent) {
        const hot = Number(agent.running_count || 0) > 0;
        const warn = agent.name === "unassigned" || Number(agent.blocked_count || 0) > 0;
        return h("article", { key: agent.name, className: "hops-agent-chip" + (hot ? " is-hot" : "") + (warn ? " is-warn" : "") },
          h("i", null),
          h("strong", null, agent.name),
          h("span", null, "ready " + (agent.ready_count || 0) + " · run " + (agent.running_count || 0) + " · block " + (agent.blocked_count || 0))
        );
      })
    );
  }

  function HOpsPage() {
    const [board, setBoard] = hooks.useState(null);
    const [selectedId, setSelectedId] = hooks.useState(null);
    const [selectionNonce, setSelectionNonce] = hooks.useState(0);
    const [error, setError] = hooks.useState(null);
    const [refreshKey, setRefreshKey] = hooks.useState(0);
    const [filters, setFilters] = hooks.useState({ q: "", status: "", assignee: "", problems: false, unassigned: false });

    function load(keepSelection) {
      setError(null);
      return api("/ops-board").then(function (res) {
        setBoard(res);
      }).catch(function (err) { setError(err.message || String(err)); });
    }

    function selectTicket(id) {
      setSelectedId(id);
      setSelectionNonce(function (v) { return v + 1; });
    }

    function refresh() {
      return load(true).then(function () { setRefreshKey(function (v) { return v + 1; }); });
    }

    function assign(ticketId, assignee) {
      return request("/tickets/" + encodeURIComponent(ticketId) + "/assign", "PATCH", { assignee: assignee || null })
        .then(refresh)
        .catch(function (err) { setError(err.message || String(err)); });
    }

    hooks.useEffect(function () { load(false); const id = setInterval(refresh, 15000); return function () { clearInterval(id); }; }, []);

    if (error && !board) return h("div", { className: "hops-page" }, h("section", { className: "hops-hero" }, h("h1", null, "H-OPS"), h("p", null, error), h(Button, { onClick: refresh }, "Retry")));
    if (!board) return h("div", { className: "hops-page" }, h("section", { className: "hops-hero" }, h("p", { className: "hops-kicker" }, "HERMES OPS"), h("h1", null, "H-OPS"), h("p", null, "Loading agent operations board…")));

    const filteredColumns = filterColumns(board.columns || [], filters);
    const totalTickets = (board.columns || []).reduce(function (sum, column) { return sum + (column.tickets || []).length; }, 0);
    const filteredTickets = filteredColumns.reduce(function (sum, column) { return sum + (column.tickets || []).length; }, 0);

    return h("div", { className: "hops-page" },
      h("section", { className: "hops-hero" },
        h("div", { className: "hops-hero-copy" },
          h("p", { className: "hops-kicker" }, "HERMES OPS / KANBAN MIRROR"),
          h("h1", null, "Ops Board"),
          h("p", null, "Same Kanban tickets, with assignment, worker progress, output, and logs surfaced for operators."),
          h("div", { className: "hops-board-note" },
            h("span", null, "Kanban-visible tickets: ", h("b", null, board.visible_count == null ? board.shown_count || 0 : board.visible_count)),
            h("span", null, "Archived: ", h("b", null, board.archived_count || 0)),
            h("span", null, "Profiles: ", h("b", null, (board.assignees || []).length))
          )
        ),
        h("div", { className: "hops-hero-metrics" },
          h("section", { className: "hops-ops-status" },
            h("div", { className: "hops-ops-status-head" },
              h("i", null),
              h("span", null, "OPS PROFILE LIVE")
            ),
            h("strong", null, "KANBAN SYNCED"),
            h("p", null, "Reading tasks, runs, worker logs, events, and profile routing state."),
            h("div", { className: "hops-scan-bars", "aria-hidden": "true" }, h("b", null), h("b", null), h("b", null))
          ),
          h(Metric, { label: "Board total", value: board.visible_count == null ? board.shown_count || 0 : board.visible_count, hint: "matches Kanban columns" }),
          h(Metric, { label: "Active", value: board.active_count || 0, hint: "ready/running/blocked" }),
          h(Metric, { label: "Done", value: (board.status_counts || {}).done || 0, hint: "completed tickets" }),
          h("div", { className: "hops-refresh-cell" }, h(Button, { onClick: refresh }, "Refresh"))
        )
      ),
      error ? h("div", { className: "hops-error-banner" }, error) : null,
      h(OpsHealthPanel, { health: board.ops_health }),
      h(Composer, { assignees: board.assignees || [], onCreated: function (id) { selectTicket(id); refresh(); } }),
      h(BoardFilterBar, { filters: filters, onChange: setFilters, assignees: board.assignees || [], resultCount: filteredTickets, totalCount: totalTickets }),
      h(StatusStrip, { counts: board.status_counts || {} }),
      h(AgentStrip, { agents: board.agents || [] }),
      h("div", { className: "hops-board-scroll-hint" }, "Full Kanban mirror: all six lanes are visible here. Click any card to open its selected-ticket dossier as a large popup."),
      h("div", { className: "hops-workspace" },
        h("main", { className: "hops-board" },
          (filteredColumns || []).map(function (column) {
            return h(OpsColumn, {
              key: column.name,
              column: column,
              assignees: board.assignees || [],
              selectedId: selectedId,
              onSelect: selectTicket,
              onAssigned: assign,
            });
          })
        ),
        h(Dossier, { ticketId: selectedId, assignees: board.assignees || [], onAssigned: assign, refreshKey: refreshKey, selectionNonce: selectionNonce })
      )
    );
  }

  window.__HERMES_PLUGINS__.register("h-ops", HOpsPage);
})();
