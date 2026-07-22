# Rural Basic Income Web

농어촌기본소득 연구용 자체 호스팅 웹 프로젝트입니다.

현재 목표는 `v0.1.0`에서 월별 인구 CSV를 PostgreSQL에 적재하고, 정제 SQL을 거쳐 FastAPI와 Plotly.js 화면에서 지역별 인구 시계열을 확인하는 최소 수직 단면을 완성하는 것입니다.

## Branch Workflow

- `main`: 프로젝트 골격과 안정 기준점
- `v0.1.0`: v0.1.0 기능 통합 브랜치
- `feat/v0.1.0-*`: `v0.1.0`에서 분기하는 개별 기능 브랜치

기능 구현은 `v0.1.0`에서 기능 브랜치를 만들고, 검증 후 다시 `v0.1.0`으로 머지합니다. `v0.1.0`이 완료되면 `main`으로 올립니다.

## Scope

v0.1.0에 포함되는 핵심 기능:

- FastAPI health check
- PostgreSQL 연결
- Alembic migration
- 월별 인구 CSV 수동 적재
- raw to clean SQL transformation
- 지역 목록 및 시계열 API
- Jinja2, Vanilla JavaScript, Plotly.js 기반 그래프
- Podman Quadlet 배포 골격

v0.1.0에서 제외하는 기능:

- Redis, Celery
- 자동 데이터 갱신
- 요청 시 회귀분석
- 관리자 페이지
- 로그인
- React 또는 Vue 기반 SPA
- nginx 예시 설정

자세한 인수인계 내용은 [docs/HANDOFF_v0.1.0.md](docs/HANDOFF_v0.1.0.md)를 확인합니다.

## Repository Layout

```text
.
├── docs/
├── src/rural_basic_income/
│   ├── db/
│   ├── pipeline/
│   └── web/
├── migrations/
├── sql/
├── tests/
└── deploy/
```

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

## KOSIS API

Put the KOSIS OpenAPI key in the ignored local `.env` file:

```env
KOSIS_API_KEY=your-api-key
```

To download and import KOSIS raw tables into PostgreSQL:

```bash
.venv/bin/python -m rural_basic_income.pipeline.kosis_raw \
  --start-period 202510 \
  --end-period 202603 \
  --request-sleep-seconds 1 \
  --timeout 30 \
  --max-retries 5 \
  --export
```

This creates or appends `raw_json.kosis_payloads`, `raw.household`, `raw.population`, `raw.mover`, and `metadata.download_status`, then exports CSV snapshots to `data/temp/` when `--export` is set.

Run the clean SQL pipeline after raw data is ready:

```bash
.venv/bin/python -m rural_basic_income.pipeline.run_clean_sql
```

## Container Image

Build the v0.1.0 web image locally:

```bash
podman build -t localhost/rural-basic-income:0.1.0 -f Containerfile .
```

Move the image to another machine with a tar archive:

```bash
podman save localhost/rural-basic-income:0.1.0 -o rural-basic-income-0.1.0.tar
rsync -av rural-basic-income-0.1.0.tar user@server:/tmp/
ssh user@server 'podman load -i /tmp/rural-basic-income-0.1.0.tar'
```

Or stream it over SSH without leaving a tar file locally:

```bash
podman save localhost/rural-basic-income:0.1.0 | ssh user@server 'podman load'
```

## Quadlet Deployment

The v0.1.0 deployment assumes the PostgreSQL volume already exists on the server and contains the imported raw and clean tables. Install the pod, database, and web Quadlet files:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/rbi-pod.pod deploy/quadlet/rbi-postgres.container deploy/quadlet/rbi-web.container ~/.config/containers/systemd/
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
