BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_population_sex_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    age text NOT NULL,
    population bigint NOT NULL,
    is_gun smallint NOT NULL CHECK (is_gun IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_population_sex_age_key
    ON clean.clean_population_sex_age (date, region_sido, region_sigungu, sex, age);

CREATE TABLE IF NOT EXISTS clean.clean_population_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    age text NOT NULL,
    population bigint NOT NULL,
    is_gun smallint NOT NULL CHECK (is_gun IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_population_age_key
    ON clean.clean_population_age (date, region_sido, region_sigungu, age);

CREATE TABLE IF NOT EXISTS clean.clean_population_sex (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    population bigint NOT NULL,
    is_gun smallint NOT NULL CHECK (is_gun IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_population_sex_key
    ON clean.clean_population_sex (date, region_sido, region_sigungu, sex);

CREATE TABLE IF NOT EXISTS clean.clean_population (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    population bigint NOT NULL,
    is_gun smallint NOT NULL CHECK (is_gun IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_population_key
    ON clean.clean_population (date, region_sido, region_sigungu);

-- Existing clean dates are immutable in normal runs. If cleaning rules change,
-- rebuild the affected clean tables explicitly before rerunning this SQL.
CREATE TEMP TABLE clean_population_sex_age_base ON COMMIT DROP AS
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
raw_long AS (
    SELECT
        "시점"::integer AS date,
        btrim("C행정구역(시군구)별") AS region_code,
        regexp_replace(coalesce("행정구역(시군구)별", ''), '[[:space:]]+', '', 'g') AS raw_region_sigungu,
        regexp_replace(coalesce("연령별", ''), '[[:space:]]+', '', 'g') AS age_raw,
        'all'::text AS sex,
        NULLIF(replace("총인구수 (명)", ',', ''), '')::bigint AS population
    FROM raw.population
    UNION ALL
    SELECT
        "시점"::integer AS date,
        btrim("C행정구역(시군구)별") AS region_code,
        regexp_replace(coalesce("행정구역(시군구)별", ''), '[[:space:]]+', '', 'g') AS raw_region_sigungu,
        regexp_replace(coalesce("연령별", ''), '[[:space:]]+', '', 'g') AS age_raw,
        'male'::text AS sex,
        NULLIF(replace("남자인구수 (명)", ',', ''), '')::bigint AS population
    FROM raw.population
    UNION ALL
    SELECT
        "시점"::integer AS date,
        btrim("C행정구역(시군구)별") AS region_code,
        regexp_replace(coalesce("행정구역(시군구)별", ''), '[[:space:]]+', '', 'g') AS raw_region_sigungu,
        regexp_replace(coalesce("연령별", ''), '[[:space:]]+', '', 'g') AS age_raw,
        'female'::text AS sex,
        NULLIF(replace("여자인구수 (명)", ',', ''), '')::bigint AS population
    FROM raw.population
),
prepared AS (
    SELECT
        date,
        region_code,
        raw_region_sigungu,
        age_raw,
        NULLIF(substring(age_raw from '^([0-9]+)'), '')::integer AS age_num,
        sex,
        population
    FROM raw_long
    WHERE length(region_code) >= 5
      AND region_code NOT IN (
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
        CASE
            WHEN p.age_raw = '계' THEN 'all'
            WHEN p.age_num >= 80 THEN '80-'
            WHEN p.age_num IS NOT NULL THEN
                ((p.age_num / 5) * 5)::text || '-' || (((p.age_num / 5) * 5) + 4)::text
            ELSE NULL
        END AS age,
        p.sex,
        p.population
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
    SUM(st.population)::bigint AS population,
    rk.is_gun
FROM standardized AS st
JOIN region_merge_key AS rk
  ON st.region_sido = rk.region_sido
 AND st.region_sigungu = rk.region_sigungu
WHERE st.age IS NOT NULL
GROUP BY
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.sex,
    st.age,
    rk.is_gun;

INSERT INTO clean.clean_population_sex_age (
    date,
    region_sido,
    region_sigungu,
    sex,
    age,
    population,
    is_gun
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.age,
    base.population,
    base.is_gun
FROM clean_population_sex_age_base AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_population_sex_age AS existing
    WHERE existing.date = base.date
)
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex, base.age
ON CONFLICT (date, region_sido, region_sigungu, sex, age) DO NOTHING;

INSERT INTO clean.clean_population_age (
    date,
    region_sido,
    region_sigungu,
    age,
    population,
    is_gun
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.age,
    base.population,
    base.is_gun
FROM clean_population_sex_age_base AS base
WHERE base.sex = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_population_age AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.age
ON CONFLICT (date, region_sido, region_sigungu, age) DO NOTHING;

INSERT INTO clean.clean_population_sex (
    date,
    region_sido,
    region_sigungu,
    sex,
    population,
    is_gun
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.population,
    base.is_gun
FROM clean_population_sex_age_base AS base
WHERE base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_population_sex AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex
ON CONFLICT (date, region_sido, region_sigungu, sex) DO NOTHING;

INSERT INTO clean.clean_population (
    date,
    region_sido,
    region_sigungu,
    population,
    is_gun
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.population,
    base.is_gun
FROM clean_population_sex_age_base AS base
WHERE base.sex = 'all'
  AND base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_population AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu
ON CONFLICT (date, region_sido, region_sigungu) DO NOTHING;

COMMIT;
