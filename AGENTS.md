# Project Instructions

Read `docs/HANDOFF_v0.1.0.md` before implementing project features.

## Current Target

Build v0.1.0 as a narrow vertical slice:

1. health checks
2. PostgreSQL connection
3. manual population CSV import
4. raw to clean SQL transformation
5. read-only FastAPI endpoints
6. Jinja2 and Plotly.js population time-series page
7. Podman Quadlet deployment notes

Do not add Redis, Celery, automatic data refresh, login, admin pages, regression analysis, or SPA frameworks in v0.1.0.

## Data Rules

- Do not commit secrets, `.env`, PostgreSQL data, exports, logs, or large raw data files.
- Keep schema changes in Alembic migrations.
- Keep repeatable data transformations in standalone `.sql` files.
- Do not hide cleaning SQL inside Python strings.
- FastAPI should read raw and clean research tables; loaders and pipelines perform writes.

## Implementation Style

- Use Python, FastAPI, Jinja2, Vanilla JavaScript, Plotly.js, SQLAlchemy Core, psycopg, and Alembic.
- Prefer small feature branches from `v0.1.0`.
- Add focused tests with each behavioral change.
- Before designing population table columns, inspect the actual CSV sample.

