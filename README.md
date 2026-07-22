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

구체적인 DB schema, 인구 CSV 열 이름, 행정구역 코드 체계는 실제 샘플 데이터를 확인한 뒤 정합니다.

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

Run tests:

```bash
.venv/bin/python -m pytest
```

## Local PostgreSQL

The local database settings are:

```text
POSTGRES_USER=rbi
POSTGRES_PASSWORD=passrbi
POSTGRES_DB=rural_basic_income
```

The actual `.env` file is ignored by Git. Use `.env.example` as the shared template.

The development Quadlet file is at `deploy/quadlet/rbi-postgres.container`. It uses the named volume `rbi-postgres-data` for PostgreSQL data:

```ini
Volume=rbi-postgres-data:/var/lib/postgresql/data
```

To install and start the PostgreSQL user service manually:

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/rbi-postgres.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start rbi-postgres.service
systemctl --user status rbi-postgres.service
```

## KOSIS API

Put the KOSIS OpenAPI key in the ignored local `.env` file:

```env
KOSIS_API_KEY=your-api-key
```

The KOSIS parameter API smoke test is skipped by default. To run it against the live API, provide the target table parameters and opt in explicitly:

```bash
RUN_KOSIS_API_SMOKE_TEST=1 \
KOSIS_SMOKE_ORG_ID=101 \
KOSIS_SMOKE_TBL_ID=your_table_id \
KOSIS_SMOKE_ITM_ID=your_item_id \
KOSIS_SMOKE_OBJ_L1=your_classification_code \
KOSIS_SMOKE_PRD_SE=M \
.venv/bin/python -m pytest tests/test_kosis_live.py
```

To download and import the 2026-01 KOSIS raw test tables into PostgreSQL, opt in explicitly:

```bash
RUN_KOSIS_RAW_IMPORT_TEST=1 .venv/bin/python -m pytest tests/test_kosis_raw_import_live.py
```

This creates `raw_json.kosis_payloads`, `raw.household`, `raw.population`, `raw.mover`, and `metadata.download_status`, then exports them to `data/temp/`.
