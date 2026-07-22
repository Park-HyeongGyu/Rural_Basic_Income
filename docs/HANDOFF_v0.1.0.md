# Rural Basic Income Web — v0.1.0 Handoff

작성일: 2026-07-22  
상태: 설계 확정, 구현 시작 전

## 1. 문서 목적

이 문서는 농어촌기본소득 연구용 자체 호스팅 웹 프로젝트를 VS Code Codex에서 이어서 구현하기 위한 인수인계 문서다.

이 문서에서는 다음을 확정한다.

- 프로젝트 전체 방향과 기술 스택
- 버전별 기능 범위
- v0.1.0의 완료 조건
- 저장소와 배포 구조
- 이미 결정된 사항과 아직 결정하지 않은 사항의 경계

데이터 테이블에 들어갈 구체적인 변수, 원자료별 스키마, 정제 규칙과 SQL 구현은 실제 데이터 파일을 확인하면서 Codex에서 별도로 설계한다.

## 2. 프로젝트 목표

농어촌기본소득 관련 행정·통계 데이터를 지속적으로 축적하고, 지역과 기간을 선택해 시계열 변화와 향후 계량분석 결과를 웹에서 확인할 수 있는 연구용 플랫폼을 만든다.

장기적으로는 다음 기능을 지원한다.

- 외부 API 및 파일 기반 데이터 자동 갱신
- raw/clean 데이터의 재현 가능한 정제 파이프라인
- 지역별·지표별 시계열 시각화
- 사전에 정의된 연구 결과 게시
- 조건을 사용자가 선택하는 비동기 계량분석
- 분석 결과 캐시와 다운로드

다만 첫 버전에서는 전체 기능을 한꺼번에 만들지 않는다. v0.1.0은 월별 인구 시계열 한 종류가 DB에서 웹 그래프까지 연결되는 최소 수직 단면을 완성하는 데 집중한다.

## 3. 확정된 기술 스택

### 애플리케이션

- 언어: Python
- 웹 프레임워크: FastAPI
- ASGI 서버: Uvicorn
- HTML 템플릿: Jinja2
- 브라우저 코드: Vanilla JavaScript
- 그래프: Plotly.js
- DB 접근: SQLAlchemy Core
- PostgreSQL 드라이버: psycopg
- DB 스키마 버전 관리: Alembic

SQLAlchemy ORM 중심으로 개발하지 않는다. 연구용 SQL을 명시적으로 유지하면서 SQLAlchemy Core로 연결, 트랜잭션, 파라미터 바인딩을 관리한다.

### 데이터베이스

- PostgreSQL을 중앙 데이터베이스로 사용한다.
- `raw`, `clean`, `metadata` 등의 PostgreSQL schema로 데이터 계층을 구분한다.
- `raw.population_monthly`, `clean.population_monthly`처럼 schema-qualified name을 사용한다.
- FastAPI 웹 프로세스는 원칙적으로 raw/clean 연구 테이블을 읽기만 한다.
- 데이터 적재 및 정제 프로세스만 raw/clean 연구 테이블을 변경한다.

### 컨테이너 및 배포

- 컨테이너 엔진: rootless Podman
- 서비스 관리: systemd user service + Quadlet
- 외부 연결: 기존 nginx에서 리버스 프록시
- Git 저장소: `rural-basic-income`
- Python package: `rural_basic_income`
- OCI image: `localhost/rural-basic-income:<version>`
- PostgreSQL DB 이름: `rural_basic_income`
- Pod 이름: `rbi-pod`
- v0.1.0 컨테이너:
  - `rbi-web`
  - `rbi-postgres`

v0.1.0에서는 Redis와 Celery를 배포하지 않는다.

## 4. 데이터와 SQL 관리 원칙

### 역할 분리

- Alembic: schema, table, column, constraint, index 등 DB 구조 변경
- `.sql` 파일: raw 데이터를 clean 테이블로 변환하는 반복 실행 가능한 로직
- Python pipeline: 데이터 적재, SQL 실행 순서, 트랜잭션, 검증, 실행 로그 관리

### SQL 버전 고정

- 정제 SQL은 Git 저장소에 포함한다.
- 정제 SQL은 애플리케이션 이미지에 함께 복사한다.
- 실행 중인 이미지 버전과 정제 SQL 버전이 일치해야 한다.
- 서버에서 마운트한 SQL 파일을 즉석 수정하는 방식을 기본 운영 방식으로 사용하지 않는다.
- SQL 수정은 Git commit과 새 이미지 버전으로 배포한다.

### 재현성과 안전성

- 가능한 정제 작업은 다시 실행해도 중복이나 손상이 발생하지 않는 멱등 구조로 작성한다.
- 여러 정제 SQL은 하나의 DB transaction 안에서 실행한다.
- 정제 또는 검증에 실패하면 전체 작업을 rollback한다.
- 적재 시각, 데이터 기준 시점, 성공 여부, row count, 애플리케이션/SQL 버전을 기록할 수 있는 metadata 구조를 마련한다.
- 구체적인 metadata table 설계는 v0.1.0 구현 과정에서 정한다.

## 5. 전체 데이터 흐름

```text
원본 CSV/API
    │
    ▼
Python loader
    │
    ▼
raw.* tables
    │
    ▼
Git과 이미지에 고정된 SQL transformation
    │
    ▼
clean.* tables
    │
    ▼
FastAPI read-only query
    │
    ▼
Jinja2 page + JavaScript + Plotly.js
```

v0.1.0에서는 CSV를 수동으로 적재한다. 외부 API 자동 수집과 예약 실행은 후속 버전에서 추가한다.

## 6. v0.1.0 목표

### 핵심 목표

PostgreSQL의 월별 인구 데이터를 FastAPI가 조회하고, 사용자가 웹에서 지역을 선택하면 Plotly.js 꺾은선 시계열 그래프로 표시한다.

### 포함 기능

1. 프로젝트와 Python package 기본 골격
2. 환경변수 기반 설정
3. PostgreSQL 연결
4. Alembic 초기 설정과 최초 DB 구조 생성
5. 월별 인구 CSV 수동 적재 명령
6. raw 인구 테이블에서 clean 인구 테이블을 생성·갱신하는 SQL 파이프라인
7. 최소 데이터 검증과 갱신 상태 기록
8. 다음 FastAPI endpoint
   - `GET /health/live`
   - `GET /health/ready`
   - `GET /api/regions`
   - `GET /api/series`
   - `GET /api/data-status`
9. 지역 선택 UI
10. 지역별 월별 인구 Plotly 꺾은선 그래프
11. 기본 오류 및 빈 데이터 표시
12. 애플리케이션 Containerfile
13. Podman Quadlet 기반 `rbi-pod`, `rbi-web`, `rbi-postgres` 배포 설정
14. nginx 리버스 프록시 예시 설정
15. 최소 테스트와 실행 문서

### 명시적으로 제외하는 기능

- Redis
- Celery worker
- 요청 시 회귀분석
- Stata 또는 R 실행 환경
- matching, synthetic control, TWFE, staggered DiD, event study
- 분석 결과 캐시
- 데이터 자동 다운로드 및 예약 갱신
- 관리자 페이지
- React, Vue 등 별도 SPA 프레임워크
- 사용자 계정과 로그인
- 여러 종류의 연구 지표

## 7. v0.1.0 완료 조건

다음 시나리오가 처음부터 끝까지 작동하면 v0.1.0을 완료한 것으로 본다.

1. PostgreSQL과 웹 컨테이너를 Podman/Quadlet로 실행한다.
2. Alembic migration으로 필요한 DB 구조를 생성한다.
3. 명령행에서 인구 CSV를 수동 적재한다.
4. raw 데이터가 정제 SQL을 거쳐 clean 인구 테이블에 반영된다.
5. 웹에 접속하면 지역 선택 목록이 표시된다.
6. 지역을 선택하면 해당 지역의 월별 인구 시계열이 Plotly 그래프로 표시된다.
7. DB 연결이 끊기면 readiness health check가 실패 상태를 반환한다.
8. 잘못된 지역 또는 데이터가 없는 조건에 대해 이해 가능한 오류/빈 상태가 표시된다.
9. 컨테이너를 새 이미지로 교체해도 PostgreSQL 데이터는 영속 volume에 보존된다.
10. README만 읽고 개발 환경 실행, CSV 적재, 테스트, 컨테이너 배포 절차를 재현할 수 있다.

## 8. v0.1.0 권장 구현 순서

### 단계 1: 저장소와 문서

- Git 저장소 초기화
- `README.md`, `AGENTS.md`, 본 handoff 문서 배치
- `pyproject.toml`, package 구조, 테스트 구조 생성

### 단계 2: 최소 웹 서버

- FastAPI app factory 또는 명확한 application entry point 구성
- `/health/live` 구현
- 로컬 Uvicorn 실행 확인

### 단계 3: PostgreSQL 기반

- 설정 모듈과 DB connection layer 작성
- SQLAlchemy Core + psycopg 연결
- Alembic 초기화
- PostgreSQL schema와 테이블 구조 설계
- `/health/ready` 구현

### 단계 4: 인구 데이터 파이프라인

- 실제 인구 CSV 구조 확인
- raw/clean table 변수와 constraint 결정
- 수동 CSV loader 작성
- 정제 `.sql` 파일 작성
- transaction과 validation 구현
- data status 기록

### 단계 5: API 수직 단면

- `/api/regions`
- `/api/series`
- `/api/data-status`
- API 테스트

### 단계 6: 화면

- Jinja2 기본 페이지
- 지역 선택 UI
- 브라우저 fetch 호출
- Plotly 시계열 그래프
- loading/error/empty state

### 단계 7: 컨테이너와 배포

- Containerfile
- PostgreSQL volume
- Quadlet `.pod`/`.container` 파일
- Podman health check 연결
- nginx 예시 설정
- 운영 절차 문서화

## 9. 권장 저장소 구조

구체적인 파일명은 구현 중 조정할 수 있지만 역할 분리는 유지한다.

```text
rural-basic-income/
├── AGENTS.md
├── HANDOFF_v0.1.0.md
├── README.md
├── Containerfile
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── src/
│   └── rural_basic_income/
│       ├── config.py
│       ├── web/
│       │   ├── main.py
│       │   ├── api/
│       │   ├── templates/
│       │   └── static/
│       ├── db/
│       └── pipeline/
├── migrations/
│   └── versions/
├── sql/
│   ├── clean/
│   ├── checks/
│   └── exports/
├── tests/
├── deploy/
│   ├── quadlet/
│   └── nginx/
└── docs/
```

v0.1.0에 필요하지 않은 빈 디렉터리를 미리 과도하게 만들 필요는 없다. 기능이 생길 때 해당 디렉터리를 추가한다.

## 10. 버전별 로드맵

### v0.1.0 — 인구 시계열 최소 기능

- 월별 인구 CSV 수동 적재
- raw → clean SQL 정제
- 지역 목록과 시계열 API
- Plotly 인구 시계열 그래프
- health check
- PostgreSQL 영속화
- Podman/Quadlet 배포

### v0.2.0 — 관측 지표 확장

- 인구 이외의 연구 지표 추가
- 지표 선택 UI
- 지역·지표·기간 조회
- 그래프 단위, 출처, 최신 기준일 표시
- 교수 또는 연구자가 사용할 clean 데이터 export
- 원자료별 데이터 품질 검사 확장

구체적으로 어떤 지표부터 넣을지는 당시 확보된 원자료와 연구 우선순위에 따라 결정한다.

### v0.3.0 — 자동 갱신 파이프라인

- 외부 API/파일 자동 다운로드
- updater 진입점 분리
- systemd timer 또는 별도 updater 컨테이너
- 원본 적재 → 정제 → 검증 → export 자동화
- 갱신 실행 기록과 실패 상태 표시
- 관리자용 최소 데이터 갱신 현황 화면 검토

자동 갱신 로직을 FastAPI request process 안에서 실행하지 않는다. 동일 애플리케이션 이미지의 별도 실행 명령 또는 컨테이너를 사용한다.

### v0.4.0 — 고정 분석 결과 게시

- 사전에 정의된 분석 specification 실행
- TWFE, event study 등 우선순위 분석부터 검토
- 분석 결과 테이블과 그래프 저장
- 웹에서 사전 계산된 분석 결과 조회
- 분석 코드 버전, 데이터 버전, 실행 시각 기록
- 교수와 공유할 결과 export

이 버전에서는 사용자가 자유롭게 조건을 바꾸어 매 요청마다 분석하는 기능은 아직 넣지 않는다.

### v0.5.0 — 인터랙티브 비동기 분석

- 사용자가 지역, 기간, 모형 조건을 선택
- 분석 작업 생성과 상태 조회
- Celery worker
- Redis broker/result backend
- 분석 중 UI와 완료 알림
- 동일 조건 결과 캐시
- 강제 재분석
- 분석 결과 영속 저장과 다운로드

Redis는 작업 전달과 일시적 상태에 사용하고, 연구 결과의 영속 저장은 PostgreSQL을 사용한다.

### v1.0.0 후보 기준

- 핵심 데이터의 안정적인 자동 갱신
- 재현 가능한 raw → clean → analysis 흐름
- 운영 가능한 health/status 화면
- 연구자가 신뢰할 수 있는 시계열과 주요 분석 결과
- 백업, 복구, 배포, 데이터 갱신 절차 문서화

v1.0.0의 정확한 범위는 v0.3.0 이후 운영 경험을 바탕으로 다시 확정한다.

## 11. 아직 확정하지 않은 사항

다음은 본 handoff에서 임의로 결정하지 않는다. 실제 데이터와 Codex 구현 세션에서 결정한다.

- 인구 CSV의 실제 열 이름과 인코딩
- 행정구역 코드 체계와 지역명 표준화 방법
- raw 및 clean 인구 테이블의 구체적인 열
- 원본 행을 어느 수준까지 그대로 보존할지
- 수정된 과거 데이터의 처리 방식
- 전체 재구축, UPSERT, snapshot 중 최종 갱신 전략
- validation 규칙과 허용 오차
- metadata/ETL log 테이블의 구체적인 열
- `/api/series`의 최종 query parameter와 JSON response 형식
- 최초 UI의 상세 디자인
- 운영 서버의 실제 경로, domain, port
- PostgreSQL 이미지의 정확한 major version
- Python package manager의 최종 운용 명령

이 항목들은 실제 샘플 CSV, 서버 환경, 첫 API 응답 형식을 확인한 뒤 결정한다.

## 12. Codex 작업 지침

Codex는 구현을 시작하기 전에 다음을 수행한다.

1. 이 문서 전체를 읽고 v0.1.0 범위와 제외 항목을 요약한다.
2. 저장소의 기존 파일과 작업 트리 상태를 확인한다.
3. 실제 인구 CSV가 제공되기 전에는 데이터 열과 행정구역 규칙을 추측하여 확정하지 않는다.
4. 데이터 스키마 설계가 필요한 시점에 샘플 CSV와 요구사항을 사용자에게 확인한다.
5. 한 번에 전체 시스템을 만들기보다 `health → DB → import → API → graph → deployment`의 수직 단면 순서로 구현한다.
6. 변경마다 관련 테스트를 실행하고, 실행하지 못한 검증은 명시한다.
7. v0.1.0에 Redis, Celery, 회귀분석, 자동 갱신을 추가하지 않는다.
8. 정제 SQL을 Python 문자열에 묻지 말고 독립 `.sql` 파일로 관리한다.
9. schema 변경과 반복 데이터 transformation의 역할을 혼합하지 않는다.
10. secrets, `.env`, PostgreSQL data, export 결과, 원본 대용량 데이터는 Git에 commit하지 않는다.

## 13. Codex 첫 요청 예시

```text
HANDOFF_v0.1.0.md를 전부 읽고 현재 저장소를 검사해줘.
아직 파일을 수정하지 말고 다음을 먼저 보고해줘.

1. 네가 이해한 v0.1.0의 목표와 제외 범위
2. handoff 내용과 저장소 상태 사이의 충돌
3. 가장 작은 첫 구현 단계
4. 첫 단계에서 만들거나 수정할 파일 목록
5. 데이터 스키마를 정하기 전에 내가 제공해야 할 자료

보고 후 내 승인을 기다려줘.
```

## 14. 현재 인수인계 상태

- 아키텍처와 v0.1.0 범위: 확정
- 후속 버전의 큰 방향: 확정
- 저장소 scaffold: 미작성
- DB schema와 변수: 미작성
- 데이터 정제 SQL: 미작성
- FastAPI 코드: 미작성
- Containerfile/Quadlet: 미작성
- 테스트: 미작성

따라서 다음 실제 작업은 Git 저장소를 준비하고, 본 문서를 저장소 루트에 둔 뒤, Codex가 저장소 상태를 확인하도록 하는 것이다.
