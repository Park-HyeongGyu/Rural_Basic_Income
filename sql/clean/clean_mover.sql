BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_mover_sex_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    age text NOT NULL,
    inflow bigint NOT NULL,
    outflow bigint NOT NULL,
    net_migration bigint NOT NULL,
    within_sigungu_migration bigint NOT NULL,
    intra_sido_inflow bigint NOT NULL,
    intra_sido_outflow bigint NOT NULL,
    inter_sido_inflow bigint NOT NULL,
    inter_sido_outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_mover_sex_age_key
    ON clean.clean_mover_sex_age (date, region_sido, region_sigungu, sex, age);

CREATE TABLE IF NOT EXISTS clean.clean_mover_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    age text NOT NULL,
    inflow bigint NOT NULL,
    outflow bigint NOT NULL,
    net_migration bigint NOT NULL,
    within_sigungu_migration bigint NOT NULL,
    intra_sido_inflow bigint NOT NULL,
    intra_sido_outflow bigint NOT NULL,
    inter_sido_inflow bigint NOT NULL,
    inter_sido_outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_mover_age_key
    ON clean.clean_mover_age (date, region_sido, region_sigungu, age);

CREATE TABLE IF NOT EXISTS clean.clean_mover_sex (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    inflow bigint NOT NULL,
    outflow bigint NOT NULL,
    net_migration bigint NOT NULL,
    within_sigungu_migration bigint NOT NULL,
    intra_sido_inflow bigint NOT NULL,
    intra_sido_outflow bigint NOT NULL,
    inter_sido_inflow bigint NOT NULL,
    inter_sido_outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_mover_sex_key
    ON clean.clean_mover_sex (date, region_sido, region_sigungu, sex);

CREATE TABLE IF NOT EXISTS clean.clean_mover (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    inflow bigint NOT NULL,
    outflow bigint NOT NULL,
    net_migration bigint NOT NULL,
    within_sigungu_migration bigint NOT NULL,
    intra_sido_inflow bigint NOT NULL,
    intra_sido_outflow bigint NOT NULL,
    inter_sido_inflow bigint NOT NULL,
    inter_sido_outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_mover_key
    ON clean.clean_mover (date, region_sido, region_sigungu);

-- Existing clean dates are immutable in normal runs. If cleaning rules change,
-- rebuild the affected clean tables explicitly before rerunning this SQL.
CREATE TEMP TABLE clean_mover_sex_age_base ON COMMIT DROP AS
WITH
sido_by_prefix(region_prefix, region_sido) AS (
    VALUES
        ('11', '서울'), ('26', '부산'), ('27', '대구'), ('28', '인천'),
        ('29', '광주'), ('30', '대전'), ('31', '울산'), ('36', '세종'),
        ('41', '경기'), ('42', '강원'), ('43', '충북'), ('44', '충남'),
        ('45', '전북'), ('46', '전남'), ('47', '경북'), ('48', '경남'),
        ('50', '제주'), ('51', '강원'), ('52', '전북')
),
missing_dates AS (
    SELECT DISTINCT raw_mv."시점"::integer AS date
    FROM raw.mover AS raw_mv
    WHERE NOT EXISTS (
        SELECT 1
        FROM clean.clean_mover_sex_age AS existing
        WHERE existing.date = raw_mv."시점"::integer
    )
       OR NOT EXISTS (
        SELECT 1
        FROM clean.clean_mover_age AS existing
        WHERE existing.date = raw_mv."시점"::integer
    )
       OR NOT EXISTS (
        SELECT 1
        FROM clean.clean_mover_sex AS existing
        WHERE existing.date = raw_mv."시점"::integer
    )
       OR NOT EXISTS (
        SELECT 1
        FROM clean.clean_mover AS existing
        WHERE existing.date = raw_mv."시점"::integer
    )
),
prepared AS (
    SELECT
        raw_mv."시점"::integer AS date,
        btrim(raw_mv."C행정구역(시군구)별") AS region_code,
        regexp_replace(coalesce(raw_mv."행정구역(시군구)별", ''), '[[:space:]]+', '', 'g')
            AS raw_region_sigungu,
        regexp_replace(coalesce(raw_mv."성별", ''), '[[:space:]]+', '', 'g') AS sex_raw,
        regexp_replace(coalesce(raw_mv."연령별", ''), '[[:space:]]+', '', 'g') AS age_raw,
        NULLIF(replace(raw_mv."시도내이동-시군구내 (명)", ',', ''), '')::bigint
            AS within_sigungu_migration,
        NULLIF(replace(raw_mv."시도내이동-시군구간 전입 (명)", ',', ''), '')::bigint
            AS intra_sido_inflow,
        NULLIF(replace(raw_mv."시도내이동-시군구간 전출 (명)", ',', ''), '')::bigint
            AS intra_sido_outflow,
        NULLIF(replace(raw_mv."시도간전입 (명)", ',', ''), '')::bigint AS inter_sido_inflow,
        NULLIF(replace(raw_mv."시도간전출 (명)", ',', ''), '')::bigint AS inter_sido_outflow
    FROM raw.mover AS raw_mv
    JOIN missing_dates AS md
      ON raw_mv."시점"::integer = md.date
    WHERE length(btrim(raw_mv."C행정구역(시군구)별")) >= 5
),
standardized AS (
    SELECT
        p.date,
        s.region_sido,
        CASE p.raw_region_sigungu
            WHEN '세종특별자치시' THEN '세종시'
            WHEN '창원시(통합)' THEN '창원시'
            ELSE p.raw_region_sigungu
        END AS region_sigungu,
        CASE p.sex_raw
            WHEN '계' THEN 'all'
            WHEN '남자' THEN 'male'
            WHEN '여자' THEN 'female'
            ELSE NULL
        END AS sex,
        CASE
            WHEN p.age_raw = '계' THEN 'all'
            WHEN p.age_raw = '80세이상' THEN '80-'
            WHEN p.age_raw ~ '^[0-9]+-[0-9]+세$' THEN regexp_replace(p.age_raw, '세$', '')
            ELSE NULL
        END AS age,
        p.within_sigungu_migration,
        p.intra_sido_inflow,
        p.intra_sido_outflow,
        p.inter_sido_inflow,
        p.inter_sido_outflow
    FROM prepared AS p
    JOIN sido_by_prefix AS s
      ON substring(p.region_code from 1 for 2) = s.region_prefix
)
SELECT
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.sex,
    st.age,
    -- KOSIS 총전입/총전출에는 시군구 내부 이동이 포함된다.
    -- clean inflow/outflow는 시군구 경계를 넘는 이동만 보기 위해
    -- 시도내이동-시군구내 값을 제외하고 시군구간 이동 + 시도간 이동만 합산한다.
    SUM(st.intra_sido_inflow + st.inter_sido_inflow)::bigint AS inflow,
    SUM(st.intra_sido_outflow + st.inter_sido_outflow)::bigint AS outflow,
    SUM(
        st.intra_sido_inflow + st.inter_sido_inflow
        - st.intra_sido_outflow - st.inter_sido_outflow
    )::bigint AS net_migration,
    SUM(st.within_sigungu_migration)::bigint AS within_sigungu_migration,
    SUM(st.intra_sido_inflow)::bigint AS intra_sido_inflow,
    SUM(st.intra_sido_outflow)::bigint AS intra_sido_outflow,
    SUM(st.inter_sido_inflow)::bigint AS inter_sido_inflow,
    SUM(st.inter_sido_outflow)::bigint AS inter_sido_outflow
FROM standardized AS st
JOIN region_merge_key AS rk
  ON st.region_sido = rk.region_sido
 AND st.region_sigungu = rk.region_sigungu
WHERE st.sex IS NOT NULL
  AND st.age IS NOT NULL
GROUP BY
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.sex,
    st.age;

INSERT INTO clean.clean_mover_sex_age (
    date,
    region_sido,
    region_sigungu,
    sex,
    age,
    inflow,
    outflow,
    net_migration,
    within_sigungu_migration,
    intra_sido_inflow,
    intra_sido_outflow,
    inter_sido_inflow,
    inter_sido_outflow
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.age,
    base.inflow,
    base.outflow,
    base.net_migration,
    base.within_sigungu_migration,
    base.intra_sido_inflow,
    base.intra_sido_outflow,
    base.inter_sido_inflow,
    base.inter_sido_outflow
FROM clean_mover_sex_age_base AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_mover_sex_age AS existing
    WHERE existing.date = base.date
)
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex, base.age
ON CONFLICT (date, region_sido, region_sigungu, sex, age) DO NOTHING;

INSERT INTO clean.clean_mover_age (
    date,
    region_sido,
    region_sigungu,
    age,
    inflow,
    outflow,
    net_migration,
    within_sigungu_migration,
    intra_sido_inflow,
    intra_sido_outflow,
    inter_sido_inflow,
    inter_sido_outflow
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.age,
    base.inflow,
    base.outflow,
    base.net_migration,
    base.within_sigungu_migration,
    base.intra_sido_inflow,
    base.intra_sido_outflow,
    base.inter_sido_inflow,
    base.inter_sido_outflow
FROM clean_mover_sex_age_base AS base
WHERE base.sex = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_mover_age AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.age
ON CONFLICT (date, region_sido, region_sigungu, age) DO NOTHING;

INSERT INTO clean.clean_mover_sex (
    date,
    region_sido,
    region_sigungu,
    sex,
    inflow,
    outflow,
    net_migration,
    within_sigungu_migration,
    intra_sido_inflow,
    intra_sido_outflow,
    inter_sido_inflow,
    inter_sido_outflow
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.inflow,
    base.outflow,
    base.net_migration,
    base.within_sigungu_migration,
    base.intra_sido_inflow,
    base.intra_sido_outflow,
    base.inter_sido_inflow,
    base.inter_sido_outflow
FROM clean_mover_sex_age_base AS base
WHERE base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_mover_sex AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex
ON CONFLICT (date, region_sido, region_sigungu, sex) DO NOTHING;

INSERT INTO clean.clean_mover (
    date,
    region_sido,
    region_sigungu,
    inflow,
    outflow,
    net_migration,
    within_sigungu_migration,
    intra_sido_inflow,
    intra_sido_outflow,
    inter_sido_inflow,
    inter_sido_outflow
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.inflow,
    base.outflow,
    base.net_migration,
    base.within_sigungu_migration,
    base.intra_sido_inflow,
    base.intra_sido_outflow,
    base.inter_sido_inflow,
    base.inter_sido_outflow
FROM clean_mover_sex_age_base AS base
WHERE base.sex = 'all'
  AND base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_mover AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu
ON CONFLICT (date, region_sido, region_sigungu) DO NOTHING;

COMMIT;
