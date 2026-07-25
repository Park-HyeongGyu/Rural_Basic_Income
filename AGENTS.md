# Project Instructions

If present locally, read `docs/AI/HANDOFF_v0.3.0.md` before implementing v0.3.0 features. Files under `docs/AI/` are ignored and are used only for AI-to-AI handoff notes.

## Current Target

Build v0.3.0 as the Scheduled Update & Interactive TWFE Analysis release.

Main goals:

1. Keep the v0.2.0 web dashboard and data refresh flow working.
2. Replace the public/operator-facing `rbi-worker` command path with canonical `rbi` CLI commands.
3. Add `rbi update --latest` so each source discovers and refreshes its own latest available periods.
4. Remove the scheduled updater container pattern; use a host user systemd timer that runs `podman exec rbi-web rbi update --latest`.
5. Preserve source x period raw transactions and dataset SQL file clean transactions.
6. Add Redis and Celery only for asynchronous web-requested analysis jobs.
7. Add an `rbi-analysis` container that runs Celery workers from the same application image as `rbi-web`.
8. Add an interactive web analysis section for traditional TWFE DiD and traditional TWFE Event Study.

Do not add updater containers, data-update Celery tasks, container-internal cron/systemd timers, login/admin systems, maps, React/Vue/SPAs, arbitrary regression formula editors, new data sources, Alembic, DuckDB/SQLite/MariaDB, R/Stata analysis, matching, synthetic control, or other estimators in v0.3.0 unless the user explicitly asks.

## Data Rules

- Do not commit secrets, `.env`, PostgreSQL data, raw data files, exports, logs, API keys, or image tar files.
- Do not add a migration framework.
- Keep repeatable data transformations in standalone `.sql` files.
- Do not hide cleaning SQL inside Python strings.
- FastAPI should read raw and clean research tables; worker/CLI code performs writes.
- Network/API fetches should finish before opening DB write transactions.
- Raw writes should be atomic at the source x period boundary.
- Clean writes should be atomic at the dataset SQL file boundary.
- PostgreSQL is the canonical research data store. Redis is only for Celery broker, result backend, and analysis cache.
- A source-period marked successful must not be damaged by a failed or unavailable force refresh.
- Raw force refresh and clean rebuild are different operations and must be exposed as different CLI semantics.
- Existing clean rows should not be silently replaced except through an explicit clean rebuild operation.
- Do not silently drop, aggregate, or rewrite ambiguous panel rows during analysis. Return structured errors or warnings.

## Updater Rules

- The canonical CLI command is `rbi`.
- Minimum commands are `rbi update`, `rbi clean`, and `rbi status`.
- `rbi update --latest` must operate per source, not with one global latest period.
- A missing or unpublished month for one source must not block other sources.
- Add an update-level overlap guard, while keeping lower-level raw and clean transaction boundaries.
- Data updates are run by host user systemd through `podman exec rbi-web rbi update --latest`.
- Do not use Celery for data updates.
- Do not keep `rbi-worker.container` as a scheduled updater. Remove or disable that pattern when implementing v0.3.0 deployment.

## Analysis Rules

- Implement only traditional TWFE DiD and traditional TWFE Event Study.
- Treatment regions and control regions are both multi-select.
- Each treatment region has its own `treatment_period`.
- Control regions are untreated for the full analysis period.
- A region cannot be both treatment and control.
- `normalization_base` and `treatment_period` are separate inputs.
- Normalize each region by its own outcome value in the normalization base month, so the region's base value becomes 1.
- If `normalization_base >= treatment_period` for a treatment region, return a warning and continue.
- Hard-error on missing, NULL, zero, or duplicate normalization baseline values.
- Always include region fixed effects and calendar-month fixed effects.
- Always use one-way clustered standard errors at the `region_sido x region_sigungu` level.
- Event Study reference period is fixed at `event_time = -1`.
- Do not expose user-selectable fixed effects, cluster levels, or Event Study reference period in v0.3.0.
- Use a validated Python regression package for fixed effects and clustered covariance; do not hand-roll numerical linear algebra.
- Keep analysis core testable without Celery. Celery tasks should orchestrate, not contain all modeling logic.
- Celery task messages must contain small canonical JSON specs, not DataFrames or large row payloads.
- Cache keys must include canonicalized request fields, analysis code/model version, and data revision.
- Force rerun must not delete a previous successful cached result before the new run succeeds.

## Web and API Rules

- Keep Jinja2, Vanilla JavaScript, Plotly.js, and the existing template/static structure.
- Keep the current v0.2.0 dashboard working.
- Add analysis UI as a section or tab on the existing page; do not redesign the whole frontend unless asked.
- Long regression analysis must not run inside the Uvicorn request process.
- FastAPI analysis endpoints enqueue Celery jobs, expose polling/status, and return structured errors without secrets or internal paths.
- Validate table and variable names through allowlists derived from clean metadata. Do not trust arbitrary SQL identifiers from the client.
- Dimension filters must leave a unique `region x period` panel. If not, return an error and let the user choose filters.
- Public analysis POST endpoints should have at least one operational protection, chosen with the user, such as rate limits, basic auth, task limits, or request size limits.

## Deployment Rules

- `rbi-web` and `rbi-analysis` use the same application image.
- `rbi-web` runs Uvicorn/FastAPI.
- `rbi-analysis` runs Celery and exposes no HTTP port.
- `rbi-redis` stays inside the pod and should not be published externally.
- Initial Celery policy: concurrency 1, prefetch multiplier 1, explicit time limits, JSON serialization, stdout logging.
- Host systemd timer templates belong under `deploy/systemd/`.
- Do not hard-code the user's private absolute project path into reusable systemd templates.

## Implementation Style

- Use Python, FastAPI, Jinja2, Vanilla JavaScript, Plotly.js, SQLAlchemy Core, psycopg, Redis, Celery, and a validated Python regression library.
- Prefer small feature branches from `v0.3.0`.
- Reuse existing KOSIS retry, timeout, chunking, raw conversion, and clean SQL code where possible.
- Inspect actual official API responses or user-provided files before deciding raw columns, clean variables, units, or region mapping.
- Keep web changes minimal unless the user explicitly starts a frontend redesign task.
- Before implementing, perform the v0.3.0 M0 inspection: branch/HEAD/worktree, baseline tests, current Quadlet structure, force-refresh code path, metadata/clean schema, frontend metadata API, regression package choice, Redis/Celery deployment plan, and the first milestone file list.
- Report the M0 findings and wait for user approval before changing feature code.
- Do not push, merge, tag, or release unless the user explicitly asks.
