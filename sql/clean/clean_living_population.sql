BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_living_population (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    region_type text NOT NULL,
    living_population numeric,
    registered_population numeric,
    stay_population numeric,
    foreign_population numeric,
    living_population_suppressed boolean NOT NULL,
    registered_population_suppressed boolean NOT NULL,
    stay_population_suppressed boolean NOT NULL,
    foreign_population_suppressed boolean NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_living_population_key
    ON clean.clean_living_population (date, region_sido, region_sigungu);

CREATE TABLE IF NOT EXISTS clean.clean_living_population_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    region_type text NOT NULL,
    age text NOT NULL,
    living_population numeric,
    registered_population numeric,
    stay_population numeric,
    foreign_population numeric,
    living_population_suppressed boolean NOT NULL,
    registered_population_suppressed boolean NOT NULL,
    stay_population_suppressed boolean NOT NULL,
    foreign_population_suppressed boolean NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_living_population_age_key
    ON clean.clean_living_population_age (
        date,
        region_sido,
        region_sigungu,
        age
    );

CREATE TEMP TABLE clean_living_population_missing_dates ON COMMIT DROP AS
SELECT DISTINCT raw_lp.period::integer AS date
FROM raw.living_population AS raw_lp
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_living_population AS existing
    WHERE existing.date = raw_lp.period::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_living_population_age AS existing
    WHERE existing.date = raw_lp.period::integer
);

CREATE TEMP TABLE living_population_prepared ON COMMIT DROP AS
WITH
sido_by_name(raw_sido, region_sido) AS (
    VALUES
        ('서울특별시', '서울'),
        ('부산광역시', '부산'),
        ('대구광역시', '대구'),
        ('인천광역시', '인천'),
        ('광주광역시', '광주'),
        ('대전광역시', '대전'),
        ('울산광역시', '울산'),
        ('세종특별자치시', '세종'),
        ('경기도', '경기'),
        ('강원도', '강원'),
        ('강원특별자치도', '강원'),
        ('충청북도', '충북'),
        ('충청남도', '충남'),
        ('전라북도', '전북'),
        ('전북특별자치도', '전북'),
        ('전라남도', '전남'),
        ('경상북도', '경북'),
        ('경상남도', '경남'),
        ('제주특별자치도', '제주')
),
age_by_raw(age_raw, age) AS (
    VALUES
        ('계', 'all'),
        ('20세 미만', '0-19'),
        ('20대', '20-29'),
        ('30대', '30-39'),
        ('40대', '40-49'),
        ('50대', '50-59'),
        ('60대', '60-69'),
        ('70세 이상', '70-')
),
population_type_by_raw(population_type_raw, variable_name) AS (
    VALUES
        ('계', 'living_population'),
        ('주민등록인구', 'registered_population'),
        ('체류인구', 'stay_population'),
        ('외국인', 'foreign_population')
)
SELECT
    raw_lp.period::integer AS date,
    s.region_sido,
    btrim(raw_lp.region_sigungu_raw) AS region_sigungu,
    btrim(raw_lp.region_type_raw) AS region_type,
    a.age,
    p.variable_name,
    CASE
        WHEN btrim(raw_lp.value_raw) = '*'
            THEN NULL::numeric
        WHEN btrim(raw_lp.value_raw) = ''
            THEN NULL::numeric
        ELSE replace(btrim(raw_lp.value_raw), ',', '')::numeric
    END AS value_numeric,
    CASE WHEN btrim(raw_lp.value_raw) = '*' THEN true ELSE false END AS is_suppressed
FROM raw.living_population AS raw_lp
JOIN clean_living_population_missing_dates AS md
  ON raw_lp.period::integer = md.date
LEFT JOIN sido_by_name AS s
  ON btrim(raw_lp.region_sido_raw) = s.raw_sido
LEFT JOIN age_by_raw AS a
  ON btrim(raw_lp.age_raw) = a.age_raw
LEFT JOIN population_type_by_raw AS p
  ON btrim(raw_lp.population_type_raw) = p.population_type_raw;

CREATE TEMP TABLE living_population_unmapped_regions ON COMMIT DROP AS
SELECT
    prepared.region_sido,
    prepared.region_sigungu,
    count(*) AS row_count
FROM living_population_prepared AS prepared
LEFT JOIN region_merge_key AS rk
  ON prepared.region_sido = rk.region_sido
 AND prepared.region_sigungu = rk.region_sigungu
WHERE rk.region_sido IS NULL
GROUP BY prepared.region_sido, prepared.region_sigungu;

CREATE TEMP TABLE living_population_unmapped_region_guard (
    region_sido text,
    region_sigungu text,
    row_count bigint,
    CONSTRAINT no_unmapped_living_population_region CHECK (false)
) ON COMMIT DROP;

INSERT INTO living_population_unmapped_region_guard (
    region_sido,
    region_sigungu,
    row_count
)
SELECT
    region_sido,
    region_sigungu,
    row_count
FROM living_population_unmapped_regions;

CREATE TEMP TABLE living_population_unknown_tokens ON COMMIT DROP AS
SELECT *
FROM living_population_prepared
WHERE region_sido IS NULL
   OR age IS NULL
   OR variable_name IS NULL
   OR region_type NOT IN ('감소', '관심');

CREATE TEMP TABLE living_population_unknown_token_guard (
    date integer,
    region_sido text,
    region_sigungu text,
    region_type text,
    age text,
    variable_name text,
    CONSTRAINT no_unknown_living_population_token CHECK (false)
) ON COMMIT DROP;

INSERT INTO living_population_unknown_token_guard (
    date,
    region_sido,
    region_sigungu,
    region_type,
    age,
    variable_name
)
SELECT
    date,
    region_sido,
    region_sigungu,
    region_type,
    age,
    variable_name
FROM living_population_unknown_tokens;

CREATE TEMP TABLE living_population_pivoted ON COMMIT DROP AS
SELECT
    prepared.date,
    rk.region_sido,
    rk.region_sigungu,
    min(prepared.region_type) AS region_type,
    prepared.age,
    max(prepared.value_numeric) FILTER (WHERE prepared.variable_name = 'living_population')
        AS living_population,
    max(prepared.value_numeric) FILTER (WHERE prepared.variable_name = 'registered_population')
        AS registered_population,
    max(prepared.value_numeric) FILTER (WHERE prepared.variable_name = 'stay_population')
        AS stay_population,
    max(prepared.value_numeric) FILTER (WHERE prepared.variable_name = 'foreign_population')
        AS foreign_population,
    bool_or(prepared.is_suppressed) FILTER (WHERE prepared.variable_name = 'living_population')
        AS living_population_suppressed,
    bool_or(prepared.is_suppressed) FILTER (WHERE prepared.variable_name = 'registered_population')
        AS registered_population_suppressed,
    bool_or(prepared.is_suppressed) FILTER (WHERE prepared.variable_name = 'stay_population')
        AS stay_population_suppressed,
    bool_or(prepared.is_suppressed) FILTER (WHERE prepared.variable_name = 'foreign_population')
        AS foreign_population_suppressed,
    count(*) FILTER (WHERE prepared.variable_name = 'living_population') AS living_population_count,
    count(*) FILTER (WHERE prepared.variable_name = 'registered_population') AS registered_population_count,
    count(*) FILTER (WHERE prepared.variable_name = 'stay_population') AS stay_population_count,
    count(*) FILTER (WHERE prepared.variable_name = 'foreign_population') AS foreign_population_count,
    count(DISTINCT prepared.region_type) AS region_type_count
FROM living_population_prepared AS prepared
JOIN region_merge_key AS rk
  ON prepared.region_sido = rk.region_sido
 AND prepared.region_sigungu = rk.region_sigungu
GROUP BY
    prepared.date,
    rk.region_sido,
    rk.region_sigungu,
    prepared.age;

CREATE TEMP TABLE living_population_incomplete_pivot ON COMMIT DROP AS
SELECT
    date,
    region_sido,
    region_sigungu,
    age,
    living_population_count,
    registered_population_count,
    stay_population_count,
    foreign_population_count,
    region_type_count
FROM living_population_pivoted
WHERE living_population_count <> 1
   OR registered_population_count <> 1
   OR stay_population_count <> 1
   OR foreign_population_count <> 1
   OR region_type_count <> 1;

CREATE TEMP TABLE living_population_incomplete_pivot_guard (
    date integer,
    region_sido text,
    region_sigungu text,
    age text,
    living_population_count bigint,
    registered_population_count bigint,
    stay_population_count bigint,
    foreign_population_count bigint,
    region_type_count bigint,
    CONSTRAINT no_incomplete_living_population_pivot CHECK (false)
) ON COMMIT DROP;

INSERT INTO living_population_incomplete_pivot_guard (
    date,
    region_sido,
    region_sigungu,
    age,
    living_population_count,
    registered_population_count,
    stay_population_count,
    foreign_population_count,
    region_type_count
)
SELECT
    date,
    region_sido,
    region_sigungu,
    age,
    living_population_count,
    registered_population_count,
    stay_population_count,
    foreign_population_count,
    region_type_count
FROM living_population_incomplete_pivot;

INSERT INTO clean.clean_living_population (
    date,
    region_sido,
    region_sigungu,
    region_type,
    living_population,
    registered_population,
    stay_population,
    foreign_population,
    living_population_suppressed,
    registered_population_suppressed,
    stay_population_suppressed,
    foreign_population_suppressed
)
SELECT
    date,
    region_sido,
    region_sigungu,
    region_type,
    living_population,
    registered_population,
    stay_population,
    foreign_population,
    coalesce(living_population_suppressed, false),
    coalesce(registered_population_suppressed, false),
    coalesce(stay_population_suppressed, false),
    coalesce(foreign_population_suppressed, false)
FROM living_population_pivoted
WHERE age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_living_population AS existing
      WHERE existing.date = living_population_pivoted.date
  )
ORDER BY date, region_sido, region_sigungu
ON CONFLICT (date, region_sido, region_sigungu) DO NOTHING;

INSERT INTO clean.clean_living_population_age (
    date,
    region_sido,
    region_sigungu,
    region_type,
    age,
    living_population,
    registered_population,
    stay_population,
    foreign_population,
    living_population_suppressed,
    registered_population_suppressed,
    stay_population_suppressed,
    foreign_population_suppressed
)
SELECT
    date,
    region_sido,
    region_sigungu,
    region_type,
    age,
    living_population,
    registered_population,
    stay_population,
    foreign_population,
    coalesce(living_population_suppressed, false),
    coalesce(registered_population_suppressed, false),
    coalesce(stay_population_suppressed, false),
    coalesce(foreign_population_suppressed, false)
FROM living_population_pivoted
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_living_population_age AS existing
    WHERE existing.date = living_population_pivoted.date
)
ORDER BY date, region_sido, region_sigungu, age
ON CONFLICT (date, region_sido, region_sigungu, age) DO NOTHING;

COMMIT;
