# Rural Basic Income Web

농어촌기본소득 연구용 자체 호스팅 웹 프로젝트입니다.

현재 `v0.3.0` 브랜치는 데이터 갱신을 canonical `rbi` CLI와 host systemd timer 구조로 정리하고, Redis/Celery 기반 비동기 TWFE 분석, 지도 기반 지역 선택, 저장된 지표/분석, CSV/DTA export를 제공하는 버전입니다.

## Branch Workflow

- `main`: 안정 릴리즈 기준점
- `v0.3.0`: v0.3.0 기능 통합 브랜치
- `feat/v0.3.0-*`: `v0.3.0`에서 분기하는 개별 기능 브랜치

기능 구현은 `v0.3.0`에서 기능 브랜치를 만들고, 검증 후 다시 `v0.3.0`으로 머지합니다.

## Scope

이미 구현된 v0.1.0 기능:

- FastAPI health check
- PostgreSQL 연결
- KOSIS 인구, 이동, 세대 raw import
- raw to clean SQL transformation
- 지역 목록 및 시계열 API
- Jinja2, Vanilla JavaScript, Plotly.js 기반 그래프
- Podman Quadlet 배포 골격

v0.2.0에서 구현한 방향:

- worker 중심 구조 정리
- 수동 데이터 갱신 command path 추가
- source x period 단위 raw transaction
- dataset SQL file 단위 clean transaction 유지
- KOSIS 인구, 이동, 세대 source 분리
- 전력사용량, 지역화폐 결제정보 source 추가
- 전력사용량, 지역화폐 결제정보 clean SQL 추가
- 신규 clean table을 기존 웹에서 조회
- CSV/DTA export 기반 마련

v0.3.0에서 구현한 방향:

- canonical `rbi` CLI
- `rbi update --latest`
- `rbi clean --rebuild`
- `rbi status`
- `rbi export`
- `--latest` 범위 전체 scan 후 성공 source-period만 skip
- update-level advisory lock
- host user systemd timer가 `podman exec rbi-web rbi update --latest` 실행
- scheduled updater container 제거
- PyFixest 기반 traditional TWFE DiD 및 event-study core
- clean table에서 선택 region, period, filter만 읽는 analysis data loader
- Redis/Celery 기반 비동기 analysis task queue
- analysis API와 polling frontend
- 지도 기반 treatment/control 및 지표 지역 선택
- 지표와 분석의 저장, 불러오기, 업데이트, 삭제
- `age`, `sex` checkbox 다중 선택
- professor-facing CSV/DTA export

v0.3.0에서 현재 제외하는 기능:

- updater container
- data update Celery task
- container 내부 cron/systemd timer
- 로그인 및 관리자 페이지
- React 또는 Vue 기반 SPA
- 별도 migration framework
- 새로운 외부 데이터 source

## Repository Layout

```text
.
├── Containerfile
├── README.md
├── deploy/
│   └── quadlet/
├── docs/
├── sql/
│   └── clean/
├── src/
│   └── rural_basic_income/
│       ├── analysis/
│       ├── db/
│       ├── worker/
│       └── web/
└── tests/
```

`docs/AI/`는 ignored 경로이며 ChatGPT Work와 Codex 사이의 handoff 문서에만 사용합니다.
`src/rural_basic_income/worker/`가 데이터 다운로드, raw 적재, clean SQL 실행을 담당합니다.
`src/rural_basic_income/analysis/`는 분석 specification, panel loader, regression core, Celery task, cache를 담당합니다.
`src/rural_basic_income/indicators/`는 저장된 지표 같은 지표 관련 server-side 기능을 담당합니다.

## Local Development

The application image uses Python 3.13. Use Python 3.11, 3.12, or 3.13 for local development. Python 3.14 can currently fail to install PyFixest's table-rendering dependency chain on some systems.

Install the project with development dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Run the web server:

```bash
.venv/bin/uvicorn rural_basic_income.web.main:app --reload
```

Check the live health endpoint:

```bash
curl http://127.0.0.1:8000/health/live
```

When PostgreSQL is running, check the readiness endpoint:

```bash
curl http://127.0.0.1:8000/health/ready
```

## Local PostgreSQL

The local database settings are:

```text
POSTGRES_USER=rbi
POSTGRES_PASSWORD=passrbi
POSTGRES_DB=rural_basic_income
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
```

The actual `.env` file is ignored by Git. Use `.env.example` as the shared template.

The development Quadlet files are in `deploy/quadlet/`. PostgreSQL uses the named volume `rbi-postgres-data` for database files:

```ini
Volume=rbi-postgres-data:/var/lib/postgresql/data
```

To install and start the PostgreSQL user service manually without the web container:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/rbi-pod.pod deploy/quadlet/rbi-postgres.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start rbi-pod.service
systemctl --user start rbi-postgres.service
systemctl --user status rbi-postgres.service
```

## Current Data Commands

Put API keys in the ignored local `.env` file:

```env
KOSIS_API_KEY=your-api-key
KEPCO_API_KEY=your-api-key
DATA_GO_KR_API_KEY=your-api-key
EXPORT_CSV_DIR=/export/csv
EXPORT_DTA_DIR=/export/dta
RBI_LATEST_START_PERIOD=202501
```

Download raw data for a period range and then run clean SQL:

```bash
.venv/bin/rbi update \
  --start-period 202501 \
  --end-period 202606
```

Scan every source x month from `RBI_LATEST_START_PERIOD` to the current month.
If the environment variable is not set, the built-in fallback is `202501`.
Periods with `metadata.download_status.status = 1` are skipped; missing
metadata and previous `status = 2` rows are requested again:

```bash
.venv/bin/rbi update --latest
```

Override the scan window when needed:

```bash
.venv/bin/rbi update --latest --start-period 202601 --end-period 202606
```

Refresh only missing source-periods and export professor-facing CSV and Stata
DTA files only when raw data was actually written:

```bash
.venv/bin/rbi update --latest --export
```

Limit the raw sources or clean datasets when needed:

```bash
.venv/bin/rbi update \
  --start-period 202601 \
  --end-period 202601 \
  --sources electricity,local_currency \
  --datasets electricity,local_currency
```

Use `--force-raw` only when a raw source x period should be downloaded again and atomically replaced. This does not rebuild existing clean rows:

```bash
.venv/bin/rbi update \
  --start-period 202601 \
  --end-period 202601 \
  --sources electricity \
  --datasets electricity \
  --force-raw
```

If a forced raw refresh receives no usable data, any previous successful raw data and success metadata for that source x period remain canonical.

Rebuild existing clean rows only through the explicit clean command:

```bash
.venv/bin/rbi clean \
  --datasets electricity \
  --start-period 202601 \
  --end-period 202601 \
  --rebuild
```

Add `--export` to an explicit clean rebuild when the rebuilt clean tables should
replace the shared CSV and DTA files:

```bash
.venv/bin/rbi clean \
  --datasets electricity \
  --start-period 202601 \
  --end-period 202601 \
  --rebuild \
  --export
```

Export the current `raw` and `clean` schemas to both CSV and Stata DTA without
downloading or rebuilding data:

```bash
.venv/bin/rbi export
```

Export writes only the latest flat files to `EXPORT_CSV_DIR` and
`EXPORT_DTA_DIR`, which default to `/export/csv` and `/export/dta` inside the
container. It exports `raw.*` and `clean.*` only; `raw_json` and `metadata` are
intentionally not exported. File names are flat, for example
`raw_population.csv`, `raw_population.dta`, `clean_population.csv`, and
`clean_population.dta`.

Inspect source download status:

```bash
.venv/bin/rbi status
```

The worker writes raw payload chunks to `raw_json.payloads`, raw rows to `raw.*`, source-period metadata to `metadata.download_status`, and clean tables to `clean.*`. In `metadata.download_status`, `status = 1` means the source-period was written successfully and `status = 2` means the source returned no usable data or a non-standard response and will be retried on a later run.

## Analysis Queue

The analysis worker uses the same image as the web container and runs Celery:

```bash
celery -A rural_basic_income.analysis.celery_app:app worker --loglevel=INFO --concurrency=1 --prefetch-multiplier=1
```

Redis is used as the Celery broker, result backend, and analysis result cache. The default local URL is:

```text
REDIS_URL=redis://127.0.0.1:6379/0
```

Quadlet examples for `rbi-redis` and `rbi-analysis` are in `deploy/quadlet/`. The analysis task accepts only a small JSON specification, then reads PostgreSQL itself and writes a JSON-serializable result to the Redis cache after the full analysis succeeds.

The web app exposes the analysis API under `/api/analysis`:

```text
POST /api/analysis/jobs
GET  /api/analysis/jobs/{task_id}
GET  /api/analysis/results/{cache_key}
GET  /api/analysis/options
GET  /api/analysis/saved
POST /api/analysis/saved
GET  /api/analysis/saved/{saved_id}
PATCH /api/analysis/saved/{saved_id}
DELETE /api/analysis/saved/{saved_id}
```

`POST /api/analysis/jobs` checks the Redis result cache before enqueueing Celery work. If the same canonical request is already running, the API returns the existing `task_id` instead of creating a duplicate job. A loose Redis rate limit is applied only to job creation requests; the default is 300 requests per 60 seconds per client address.

## Web Interface

The single Jinja2 page keeps the existing indicator dashboard and adds tabs for analysis, saved indicators, and saved analyses.

- The indicator dashboard can select multiple regions from dropdowns or the map and draw them on one Plotly line chart.
- Tables with `age` or `sex` dimensions expose those filters as checkboxes. In the dashboard, each selected filter value or combination becomes a separate line.
- The analysis tab supports multiple treatment regions, multiple control regions, treatment-specific start months, a separate normalization base month, TWFE results, and Event Study results.
- Saved indicators and saved analyses can be created, loaded, updated, and deleted from the web UI.

Saved view state is stored in PostgreSQL:

```text
saved.saved_indicator
saved.saved_analysis
```

`request_payload` stores the selected table, variables, regions, filters, and periods. `result_payload` stores the result snapshot that was shown when the item was saved.

## Container Image

Build the v0.3.0 image locally:

```bash
podman build -t localhost/rural-basic-income:0.3.0 -f Containerfile .
```

Move the image to another machine with a tar archive:

```bash
podman save localhost/rural-basic-income:0.3.0 -o rural-basic-income-0.3.0.tar
rsync -av rural-basic-income-0.3.0.tar user@server:/tmp/
ssh user@server 'podman load -i /tmp/rural-basic-income-0.3.0.tar'
```

Or stream it over SSH without leaving a tar file locally:

```bash
podman save localhost/rural-basic-income:0.3.0 | ssh user@server 'podman load'
```

## Quadlet Deployment

The deployment assumes the PostgreSQL volume already exists on the server. Install the pod, database, web, Redis, and analysis worker Quadlet files:

```bash
mkdir -p ~/.config/containers/systemd
mkdir -p export/csv export/dta
cp deploy/quadlet/rbi-pod.pod \
  deploy/quadlet/rbi-postgres.container \
  deploy/quadlet/rbi-web.container \
  deploy/quadlet/rbi-redis.container \
  deploy/quadlet/rbi-analysis.container \
  ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start rbi-pod.service
systemctl --user start rbi-postgres.service
systemctl --user start rbi-redis.service
systemctl --user start rbi-web.service
systemctl --user start rbi-analysis.service
```

`rbi-pod.pod` publishes the web service on `127.0.0.1:8000` and PostgreSQL on `127.0.0.1:5432`. Redis is kept inside the shared pod network and is not published to the host by default. The web, database, Redis, and analysis containers share the pod network namespace, so the existing local `127.0.0.1` service settings work inside the deployment pod.

`rbi-web.container` bind mounts the project-local `export/csv/` directory to
`/export/csv` and `export/dta/` to `/export/dta` inside the container. Sharing
files are written flat under those two directories.

Check the running web service:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Run a manual update inside the running web container:

```bash
podman exec rbi-web rbi update --latest
```

`--latest` scans the full configured window and retries missing or previously
failed source-periods while leaving successful source-periods untouched. Add
`--force-raw` only when successful raw source-periods should be redownloaded
and atomically replaced too.

On the server, the default `--latest` scan start is controlled by
`RBI_LATEST_START_PERIOD` in the web container environment. Change that value
in `.env` or `deploy/quadlet/rbi-web.container`, then reload/restart the user
service before the next update.

Run an update and refresh the shared CSV and DTA files only if new raw data was
written:

```bash
podman exec rbi-web rbi update --latest --export
```

Install a host user systemd timer template for scheduled updates:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/rbi-update.service ~/.config/systemd/user/
cp deploy/systemd/rbi-update.timer.example ~/.config/systemd/user/rbi-update.timer
systemctl --user daemon-reload
```

Edit `~/.config/systemd/user/rbi-update.timer` and replace `OnCalendar=<USER_SELECTED_SCHEDULE>` with the desired schedule before enabling it:

```bash
systemctl --user enable --now rbi-update.timer
systemctl --user list-timers
journalctl --user -u rbi-update.service -n 200 -f
```
