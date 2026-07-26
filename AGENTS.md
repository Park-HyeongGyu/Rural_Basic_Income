# Project Instructions

If present locally, read `docs/AI/HANDOFF_v0.3.0.md` and the latest
`docs/AI/TO_GPT_*.md` before making release or follow-up changes. Files under
`docs/AI/` are ignored and are used only for AI-to-AI handoff notes.

## Current Status

The project is at the end of the v0.3.0 Scheduled Update & Interactive TWFE
Analysis work. v0.3.0 currently includes:

- canonical `rbi` CLI commands: `rbi update`, `rbi clean`, `rbi status`,
  and `rbi export`
- per-source `rbi update --latest`
- source x period raw transactions
- dataset SQL file clean transactions
- explicit raw force refresh and clean rebuild semantics
- update-level PostgreSQL advisory lock
- host user systemd timer templates that call
  `podman exec rbi-web rbi update --latest --export`
- CSV and Stata DTA export for `raw.*` and `clean.*`
- Redis/Celery async analysis jobs
- `rbi-redis` and `rbi-analysis` Quadlet examples
- traditional TWFE DiD and traditional TWFE Event Study via PyFixest
- analysis API, polling frontend, and Plotly result views
- map-based region selection for indicators and analysis
- saved indicators and saved analyses stored in PostgreSQL under
  `saved.saved_indicator` and `saved.saved_analysis`

Remaining release-oriented work is mostly image/server smoke testing,
timer/service smoke testing, final documentation review, and
`docs/AI/TO_GPT_v0.3.0.md`.

## Data Rules

- Do not commit secrets, `.env`, PostgreSQL data, raw data files, exports, logs,
  API keys, or image tar files.
- Do not add Alembic or a migration framework unless the user explicitly asks.
- Keep repeatable data transformations in standalone `.sql` files.
- Do not hide cleaning SQL inside Python strings.
- FastAPI should read raw and clean research tables; worker/CLI code performs
  writes.
- Network/API fetches should finish before opening DB write transactions.
- Raw writes should be atomic at the source x period boundary.
- Clean writes should be atomic at the dataset SQL file boundary.
- PostgreSQL is the canonical research data store. Redis is only for Celery
  broker, result backend, and analysis cache.
- A source-period marked successful must not be damaged by a failed or
  unavailable force refresh.
- Raw force refresh and clean rebuild are different operations.
- Existing clean rows should not be replaced except through explicit clean
  rebuild.

## CLI And Update Rules

- The canonical public CLI command is `rbi`; do not reintroduce the
  `rbi-worker` console script.
- `rbi update --latest` scans all source-periods in the requested/latest range
  and skips only rows already recorded as `metadata.download_status.status = 1`.
- A missing or unpublished month for one source must not block other sources.
- Data updates are run by host user systemd through `podman exec rbi-web ...`.
- Do not use Celery for data updates.
- Do not bring back a scheduled updater container.
- `rbi export` writes latest flat CSV/DTA files for `raw.*` and `clean.*` only;
  it intentionally excludes `raw_json` and `metadata`.

## Analysis Rules

- Implement only traditional TWFE DiD and traditional TWFE Event Study unless
  the user explicitly asks for another estimator.
- Treatment regions and control regions are both multi-select.
- Each treatment region has its own `treatment_period`.
- Control regions are untreated for the full analysis period.
- A region cannot be both treatment and control.
- `normalization_base` and `treatment_period` are separate inputs.
- Normalize each region by its own outcome value in the normalization base
  month, so the region's base value becomes 1.
- If `normalization_base >= treatment_period` for a treatment region, return a
  warning and continue.
- Hard-error on missing, NULL, zero, or duplicate normalization baseline values.
- Always include region fixed effects and calendar-month fixed effects.
- Always use one-way clustered standard errors at the
  `region_sido x region_sigungu` level.
- Event Study reference period is fixed at `event_time = -1`.
- Do not expose user-selectable fixed effects, cluster levels, or Event Study
  reference period in v0.3.0.
- Use a validated Python regression package for fixed effects and clustered
  covariance; do not hand-roll numerical linear algebra.
- Keep analysis core testable without Celery. Celery tasks should orchestrate,
  not contain all modeling logic.
- Celery task messages must contain small canonical JSON specs, not DataFrames
  or large row payloads.
- Cache keys must include canonicalized request fields, analysis code/model
  version, and data revision.
- Force rerun must not delete a previous successful cached result before the new
  run succeeds.
- Multi-value `age`/`sex` filters are allowed. Indicator charts draw selected
  filter values as separate series; analysis panels aggregate selected filter
  values to preserve one row per region-period.

## Web And API Rules

- Keep Jinja2, Vanilla JavaScript, Plotly.js, and the existing template/static
  structure.
- Keep the dashboard, analysis, saved indicator, and saved analysis tabs working.
- Long regression analysis must not run inside the Uvicorn request process.
- FastAPI analysis endpoints enqueue Celery jobs, expose polling/status, and
  return structured errors without secrets or internal paths.
- Validate table and variable names through allowlists derived from clean
  metadata. Do not trust arbitrary SQL identifiers from the client.
- Saved indicator endpoints live under `/api/indicators/saved`.
- Saved analysis endpoints live under `/api/analysis/saved`.
- Saved view state belongs in the shared `saved` schema, not in separate
  `analysis_saved` or `indicator_saved` schemas.
- Map assets are generated static web assets. Do not rely on ignored shapefiles
  at runtime.

## Deployment Rules

- `rbi-web` and `rbi-analysis` use the same application image.
- `rbi-web` runs Uvicorn/FastAPI.
- `rbi-analysis` runs Celery and exposes no HTTP port.
- `rbi-redis` stays inside the pod and should not be published externally.
- Initial Celery policy: concurrency 1, prefetch multiplier 1, explicit time
  limits, JSON serialization, stdout logging.
- Host systemd timer templates belong under `deploy/systemd/`.
- Avoid adding new private absolute paths to reusable deployment templates.

## Implementation Style

- Use Python, FastAPI, Jinja2, Vanilla JavaScript, Plotly.js, SQLAlchemy Core,
  psycopg, Redis, Celery, and PyFixest.
- Prefer small feature branches from `v0.3.0` until this release is complete.
- Reuse existing KOSIS retry, timeout, chunking, raw conversion, and clean SQL
  code where possible.
- Inspect actual official API responses or user-provided files before deciding
  raw columns, clean variables, units, or region mapping.
- Do not push, merge, tag, or release unless the user explicitly asks.
- The user manages commits. `git add` is allowed, but always report immediately
  after staging files.
