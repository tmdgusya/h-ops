# Contributing to H-OPS

Thanks for wanting to improve H-OPS.

## Local checks

```bash
python3 -m py_compile dashboard/plugin_api.py
node --check dashboard/dist/index.js
python3 -m unittest discover -s tests -v
```

## Design expectations

- Keep Hermes Kanban as the source of truth.
- Prefer safe, explicit operator actions.
- Do not fake mutating controls without backend behavior.
- Treat old heartbeats differently for completed vs running tickets.
- Keep the UI readable in the Hermes dashboard dark shell.

## Plugin install during development

```bash
ln -s /path/to/h-ops ~/.hermes/plugins/h-ops
hermes plugins enable h-ops
curl http://127.0.0.1:9119/api/dashboard/plugins/rescan
```

Restart `hermes dashboard` after backend API route changes.
