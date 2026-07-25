# Project Instructions

If present locally, read `docs/AI/HANDOFF_v0.2.0.md` before implementing v0.2.0 features. Files under `docs/AI/` are ignored and are used only for AI-to-AI handoff notes.

## Current Target

Build v0.2.0 as the Worker & Indicators release.

Main goals:

1. Keep the v0.1.0 web dashboard working.
2. Add a manual one-shot `rbi-worker` command path.
3. Move data refresh work toward source-by-period raw transactions.
4. Keep clean SQL execution at dataset SQL file transaction boundaries.
5. Add electricity, local currency, and permits datasets after inspecting official sources.

Do not add Redis, Celery, systemd timers, login, admin pages, regression analysis, maps, new page structures, or SPA frameworks in v0.2.0.

## Data Rules

- Do not commit secrets, `.env`, PostgreSQL data, raw data files, exports, logs, API keys, or image tar files.
- Do not add a migration framework.
- Keep repeatable data transformations in standalone `.sql` files.
- Do not hide cleaning SQL inside Python strings.
- FastAPI should read raw and clean research tables; worker and pipeline code perform writes.
- Network/API fetches should finish before opening DB write transactions.
- Raw writes should be atomic at the source x period boundary.
- Clean writes should be atomic at the dataset SQL file boundary.

## Implementation Style

- Use Python, FastAPI, Jinja2, Vanilla JavaScript, Plotly.js, SQLAlchemy Core, and psycopg.
- Prefer small feature branches from `v0.2.0`.
- Reuse existing KOSIS retry, timeout, chunking, raw conversion, and clean SQL code where possible.
- Inspect actual official API responses or user-provided files before deciding raw columns, clean variables, units, or region mapping.
- Keep web changes minimal unless the user explicitly starts a frontend redesign task.
