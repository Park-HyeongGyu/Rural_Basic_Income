# Project Instructions

If present locally, read `docs/AI/HANDOFF_v0.3.1.md` and the latest
`docs/AI/TO_GPT_*.md` before making release or follow-up changes. Files under
`docs/AI/` are ignored and are used only for AI-to-AI handoff notes.

## Current Status

The project is at the end of the v0.3.1 Migration OD & Living Population Data
Integration release. v0.3.0 already includes:

- canonical `rbi` CLI commands: `rbi update`, `rbi clean`, `rbi status`,
  and `rbi export`
- per-source `rbi update --latest`
- source x period raw transactions
- dataset SQL file clean transactions
- explicit raw force refresh and clean rebuild semantics
- update-level PostgreSQL advisory lock
- host user systemd timer templates that call
  `podman exec rbi-web rbi update --latest --export`
- CSV export for `raw.*` and `clean.*`; the Stata DTA export code is retained
  but no longer invoked by the public CLI because large OD tables can exceed
  server memory
- Redis/Celery async analysis jobs
- `rbi-redis` and `rbi-analysis` Quadlet examples
- traditional TWFE DiD and traditional TWFE Event Study via PyFixest
- analysis API, polling frontend, and Plotly result views
- map-based region selection for indicators and analysis
- saved indicators and saved analyses stored in PostgreSQL under
  `saved.saved_indicator` and `saved.saved_analysis`

v0.3.1 adds data-only pipeline work:

- `migration_od` source for 행정안전부 지역별 인구이동 현황
- OD definition: `mvt` is origin/outflow, `mvin` is destination/inflow
- `raw.migration_od` plus raw_json payload preservation
- migration clean tables:
  `clean_inflow`, `clean_inflow_sex`, `clean_inflow_age`,
  `clean_inflow_sex_age`, `clean_outflow`, `clean_outflow_sex`,
  `clean_outflow_age`, and `clean_outflow_sex_age`
- `living_population` manual CSV import via
  `rbi import living-population --file PATH`
- `raw.living_population` long-format file import rows with SHA-256
  idempotency
- living clean tables:
  `clean_living_population` and `clean_living_population_age`
- `rbi status` reports the latest manual living-population import status
- 신규 clean tables are exported, but OD tables are not exposed through the
  generic dashboard or analysis options in v0.3.1

v0.3.1 is still data-only: no OD frontend, no living-population-specific UI,
and no new analysis estimator.

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
- `rbi export` writes latest flat CSV files for `raw.*` and `clean.*` only; it
  intentionally excludes `raw_json` and `metadata`. Stata DTA export functions
  remain in the codebase but are not called by the public CLI.
- `migration_od` is included in the default `rbi update --latest` raw source and
  clean dataset list. Existing successful source-periods must still be skipped.
- `living_population` is a manual file import source and must not be included
  in `rbi update --latest`.
- Living population imports use SHA-256 idempotency and replace only periods
  covered by the incoming cumulative file.
- A missing or unpublished migration OD month must not block other sources.

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
- OD clean tables include extra `from_*` or `to_*` dimensions. Keep them hidden
  from generic `/api/data-status`, `/api/series`, and analysis options until a
  dedicated OD API/UI exists.
- Living population tables have ordinary regional time-series grain and may be
  exposed like other compatible clean tables.

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
