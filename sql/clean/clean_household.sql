BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_household (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    household bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_household_key
    ON clean.clean_household (date, region_sido, region_sigungu);

-- Existing clean dates are immutable in normal runs. If cleaning rules change,
-- rebuild the affected clean tables explicitly before rerunning this SQL.
CREATE TEMP TABLE clean_household_base ON COMMIT DROP AS
WITH
dropped_region_codes(region_code) AS (
    VALUES
        ('41111'), ('41113'), ('41115'), ('41117'),
        ('41131'), ('41133'), ('41135'),
        ('41171'), ('41173'),
        ('41192'), ('41194'), ('41196'),
        ('41222'), ('41224'),
        ('41271'), ('41273'),
        ('41281'), ('41285'), ('41287'),
        ('41362'),
        ('41461'), ('41463'), ('41465'),
        ('41592'), ('41594'),
        ('48121'), ('48123'), ('48125'), ('48127'), ('48129'),
        ('48245'), ('48252'), ('48332'),
        ('47111'), ('47113'),
        ('28114'), ('28118'), ('28265'),
        ('52111'), ('52113'),
        ('44131'), ('44133'),
        ('43111'), ('43112'), ('43113'), ('43114')
),
sido_by_prefix(region_prefix, region_sido) AS (
    VALUES
        ('11', '서울'), ('26', '부산'), ('27', '대구'), ('28', '인천'),
        ('29', '광주'), ('30', '대전'), ('31', '울산'), ('36', '세종'),
        ('41', '경기'), ('42', '강원'), ('43', '충북'), ('44', '충남'),
        ('45', '전북'), ('46', '전남'), ('47', '경북'), ('48', '경남'),
        ('50', '제주'), ('51', '강원'), ('52', '전북')
),
missing_dates AS (
    SELECT DISTINCT raw_hh."시점"::integer AS date
    FROM raw.household AS raw_hh
    WHERE NOT EXISTS (
        SELECT 1
        FROM clean.clean_household AS existing
        WHERE existing.date = raw_hh."시점"::integer
    )
),
prepared AS (
    SELECT
        raw_hh."시점"::integer AS date,
        btrim(raw_hh."C행정구역(시군구)별") AS region_code,
        regexp_replace(coalesce(raw_hh."행정구역(시군구)별", ''), '[[:space:]]+', '', 'g')
            AS raw_region_sigungu,
        NULLIF(replace(raw_hh."세대수 (세대)", ',', ''), '')::bigint AS household
    FROM raw.household AS raw_hh
    JOIN missing_dates AS md
      ON raw_hh."시점"::integer = md.date
    WHERE length(btrim(raw_hh."C행정구역(시군구)별")) >= 5
      AND btrim(raw_hh."C행정구역(시군구)별") NOT IN (
          SELECT region_code FROM dropped_region_codes
      )
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
        p.household
    FROM prepared AS p
    JOIN sido_by_prefix AS s
      ON substring(p.region_code from 1 for 2) = s.region_prefix
)
SELECT
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.household
FROM standardized AS st
JOIN region_merge_key AS rk
  ON st.region_sido = rk.region_sido
 AND st.region_sigungu = rk.region_sigungu;

INSERT INTO clean.clean_household (
    date,
    region_sido,
    region_sigungu,
    household
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.household
FROM clean_household_base AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_household AS existing
    WHERE existing.date = base.date
)
ORDER BY base.date, base.region_sido, base.region_sigungu
ON CONFLICT (date, region_sido, region_sigungu) DO NOTHING;

COMMIT;
