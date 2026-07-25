# Rural Basic Income Web

농어촌기본소득 연구용 자체 호스팅 웹 프로젝트입니다.

현재 `v0.2.0`은 `v0.1.0`에서 완성한 시계열 웹 대시보드를 유지하면서, 수동 one-shot `rbi-worker`와 신규 지표 적재 기반을 추가합니다.

## Branch Workflow

- `main`: 안정 릴리즈 기준점
- `v0.2.0`: v0.2.0 기능 통합 브랜치
- `feat/v0.2.0-*`: `v0.2.0`에서 분기하는 개별 기능 브랜치

기능 구현은 `v0.2.0`에서 기능 브랜치를 만들고, 검증 후 다시 `v0.2.0`으로 머지합니다.

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
- `rbi-worker update` console command 추가
- source x period 단위 raw transaction
- dataset SQL file 단위 clean transaction 유지
- KOSIS 인구, 이동, 세대 source 분리
- 전력사용량, 지역화폐 결제정보 source 추가
- 전력사용량, 지역화폐 결제정보 clean SQL 추가
- 신규 clean table을 기존 웹에서 조회

v0.2.0에서 제외하는 기능:

- systemd timer
- Redis, Celery
- 상시 실행 worker
- 웹 요청 기반 분석
- 지도 UI
- 로그인 및 관리자 페이지
- React 또는 Vue 기반 SPA
- 별도 migration framework
- 경제적, 통계적 runtime validation
- 인허가 데이터
- worker 정기 실행 timer
- worker export/status 하위 명령

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
│       ├── db/
│       ├── worker/
│       └── web/
└── tests/
```

`docs/AI/`는 ignored 경로이며 ChatGPT Work와 Codex 사이의 handoff 문서에만 사용합니다.
`src/rural_basic_income/worker/`가 데이터 다운로드, raw 적재, clean SQL 실행을 담당합니다.

## Local Development

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
```

Download raw data for a period range and then run clean SQL:

```bash
.venv/bin/rbi-worker update \
  --start-period 202501 \
  --end-period 202606
```

Limit the raw sources or clean datasets when needed:

```bash
.venv/bin/rbi-worker update \
  --start-period 202601 \
  --end-period 202601 \
  --sources electricity,local_currency \
  --datasets electricity,local_currency
```

Use `--force` only when a source x period should be downloaded again and atomically replaced:

```bash
.venv/bin/rbi-worker update \
  --start-period 202601 \
  --end-period 202601 \
  --sources electricity \
  --datasets electricity \
  --force
```

The worker writes raw payload chunks to `raw_json.payloads`, raw rows to `raw.*`, source-period metadata to `metadata.download_status`, and clean tables to `clean.*`. In `metadata.download_status`, `status = 1` means the source-period was written successfully and `status = 2` means the source returned no usable data or a non-standard response and will be retried on a later run.

## Container Image

Build the v0.2.0 image locally:

```bash
podman build -t localhost/rural-basic-income:0.2.0 -f Containerfile .
```

Move the image to another machine with a tar archive:

```bash
podman save localhost/rural-basic-income:0.2.0 -o rural-basic-income-0.2.0.tar
rsync -av rural-basic-income-0.2.0.tar user@server:/tmp/
ssh user@server 'podman load -i /tmp/rural-basic-income-0.2.0.tar'
```

Or stream it over SSH without leaving a tar file locally:

```bash
podman save localhost/rural-basic-income:0.2.0 | ssh user@server 'podman load'
```

## Quadlet Deployment

The deployment assumes the PostgreSQL volume already exists on the server. Install the pod, database, web, and worker Quadlet files:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/rbi-pod.pod deploy/quadlet/rbi-postgres.container deploy/quadlet/rbi-web.container deploy/quadlet/rbi-worker.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start rbi-pod.service
systemctl --user start rbi-postgres.service
systemctl --user start rbi-web.service
```

`rbi-pod.pod` publishes the web service on `127.0.0.1:8000` and PostgreSQL on `127.0.0.1:5432`. The web and database containers share the pod network namespace, so the existing local `127.0.0.1` database settings work inside the deployment pod.

Check the running web service:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Run the one-shot worker manually:

```bash
systemctl --user start rbi-worker.service
systemctl --user status rbi-worker.service
```

Follow worker logs while it downloads, writes raw data, and runs clean SQL:

```bash
journalctl --user -u rbi-worker.service -n 200 -f
```
