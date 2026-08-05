BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_inflow (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    from_sido text NOT NULL,
    from_sigungu text NOT NULL,
    inflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_inflow_key
    ON clean.clean_inflow (
        date,
        region_sido,
        region_sigungu,
        from_sido,
        from_sigungu
    );

CREATE TABLE IF NOT EXISTS clean.clean_inflow_sex (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    from_sido text NOT NULL,
    from_sigungu text NOT NULL,
    sex text NOT NULL,
    inflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_inflow_sex_key
    ON clean.clean_inflow_sex (
        date,
        region_sido,
        region_sigungu,
        from_sido,
        from_sigungu,
        sex
    );

CREATE TABLE IF NOT EXISTS clean.clean_inflow_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    from_sido text NOT NULL,
    from_sigungu text NOT NULL,
    age text NOT NULL,
    inflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_inflow_age_key
    ON clean.clean_inflow_age (
        date,
        region_sido,
        region_sigungu,
        from_sido,
        from_sigungu,
        age
    );

CREATE TABLE IF NOT EXISTS clean.clean_inflow_sex_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    from_sido text NOT NULL,
    from_sigungu text NOT NULL,
    sex text NOT NULL,
    age text NOT NULL,
    inflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_inflow_sex_age_key
    ON clean.clean_inflow_sex_age (
        date,
        region_sido,
        region_sigungu,
        from_sido,
        from_sigungu,
        sex,
        age
    );

CREATE TABLE IF NOT EXISTS clean.clean_outflow (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    to_sido text NOT NULL,
    to_sigungu text NOT NULL,
    outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_outflow_key
    ON clean.clean_outflow (
        date,
        region_sido,
        region_sigungu,
        to_sido,
        to_sigungu
    );

CREATE TABLE IF NOT EXISTS clean.clean_outflow_sex (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    to_sido text NOT NULL,
    to_sigungu text NOT NULL,
    sex text NOT NULL,
    outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_outflow_sex_key
    ON clean.clean_outflow_sex (
        date,
        region_sido,
        region_sigungu,
        to_sido,
        to_sigungu,
        sex
    );

CREATE TABLE IF NOT EXISTS clean.clean_outflow_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    to_sido text NOT NULL,
    to_sigungu text NOT NULL,
    age text NOT NULL,
    outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_outflow_age_key
    ON clean.clean_outflow_age (
        date,
        region_sido,
        region_sigungu,
        to_sido,
        to_sigungu,
        age
    );

CREATE TABLE IF NOT EXISTS clean.clean_outflow_sex_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    to_sido text NOT NULL,
    to_sigungu text NOT NULL,
    sex text NOT NULL,
    age text NOT NULL,
    outflow bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_outflow_sex_age_key
    ON clean.clean_outflow_sex_age (
        date,
        region_sido,
        region_sigungu,
        to_sido,
        to_sigungu,
        sex,
        age
    );

CREATE TEMP TABLE clean_migration_od_missing_dates ON COMMIT DROP AS
SELECT DISTINCT raw_mo."statsYm"::integer AS date
FROM raw.migration_od AS raw_mo
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow_sex AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow_age AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow_sex_age AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow_sex AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow_age AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow_sex_age AS existing
    WHERE existing.date = raw_mo."statsYm"::integer
);

CREATE TEMP TABLE migration_od_standardized ON COMMIT DROP AS
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
prepared AS (
    SELECT
        raw_mo."statsYm"::integer AS date,
        btrim(raw_mo."mvinAdmmCd") AS destination_code,
        btrim(raw_mo."mvinCtpvNm") AS destination_sido_raw,
        btrim(raw_mo."mvinSggNm") AS destination_sigungu_raw,
        btrim(raw_mo."mvtAdmmCd") AS origin_code,
        btrim(raw_mo."mvtCtpvNm") AS origin_sido_raw,
        btrim(raw_mo."mvtSggNm") AS origin_sigungu_raw,
        coalesce(nullif(regexp_replace(raw_mo."totNmprCnt", '[^0-9-]', '', 'g'), ''), '0')::bigint
            AS total_count,
        coalesce(nullif(regexp_replace(raw_mo."maleNmprCnt", '[^0-9-]', '', 'g'), ''), '0')::bigint
            AS male_count,
        coalesce(nullif(regexp_replace(raw_mo."femlNmprCnt", '[^0-9-]', '', 'g'), ''), '0')::bigint
            AS female_count,
        to_jsonb(raw_mo) AS raw_json
    FROM raw.migration_od AS raw_mo
    JOIN clean_migration_od_missing_dates AS md
      ON raw_mo."statsYm"::integer = md.date
),
standardized_names AS (
    SELECT
        p.*,
        ds.region_sido AS destination_sido,
        os.region_sido AS origin_sido,
        CASE
            WHEN ds.region_sido = '세종'
                THEN '세종시'
            WHEN p.destination_sigungu_raw LIKE '%시 %구'
                THEN split_part(p.destination_sigungu_raw, ' ', 1)
            WHEN p.destination_sigungu_raw = '창원시(통합)'
                THEN '창원시'
            ELSE p.destination_sigungu_raw
        END AS destination_sigungu,
        CASE
            WHEN os.region_sido = '세종'
                THEN '세종시'
            WHEN p.origin_sigungu_raw LIKE '%시 %구'
                THEN split_part(p.origin_sigungu_raw, ' ', 1)
            WHEN p.origin_sigungu_raw = '창원시(통합)'
                THEN '창원시'
            ELSE p.origin_sigungu_raw
        END AS origin_sigungu
    FROM prepared AS p
    LEFT JOIN sido_by_name AS ds
      ON p.destination_sido_raw = ds.raw_sido
    LEFT JOIN sido_by_name AS os
      ON p.origin_sido_raw = os.raw_sido
)
SELECT *
FROM standardized_names;

CREATE TEMP TABLE migration_od_unmapped_regions ON COMMIT DROP AS
SELECT
    'destination' AS side,
    destination_code AS raw_code,
    destination_sido_raw AS raw_sido,
    destination_sigungu_raw AS raw_sigungu,
    destination_sido AS region_sido,
    destination_sigungu AS region_sigungu,
    count(*) AS row_count
FROM migration_od_standardized AS st
LEFT JOIN region_merge_key AS rk
  ON st.destination_sido = rk.region_sido
 AND st.destination_sigungu = rk.region_sigungu
WHERE rk.region_sido IS NULL
GROUP BY
    destination_code,
    destination_sido_raw,
    destination_sigungu_raw,
    destination_sido,
    destination_sigungu
UNION ALL
SELECT
    'origin' AS side,
    origin_code AS raw_code,
    origin_sido_raw AS raw_sido,
    origin_sigungu_raw AS raw_sigungu,
    origin_sido AS region_sido,
    origin_sigungu AS region_sigungu,
    count(*) AS row_count
FROM migration_od_standardized AS st
LEFT JOIN region_merge_key AS rk
  ON st.origin_sido = rk.region_sido
 AND st.origin_sigungu = rk.region_sigungu
WHERE rk.region_sido IS NULL
GROUP BY
    origin_code,
    origin_sido_raw,
    origin_sigungu_raw,
    origin_sido,
    origin_sigungu;

CREATE TEMP TABLE migration_od_unmapped_guard (
    side text NOT NULL,
    raw_code text,
    raw_sido text,
    raw_sigungu text,
    region_sido text,
    region_sigungu text,
    row_count bigint,
    CONSTRAINT no_unmapped_migration_od_region CHECK (false)
) ON COMMIT DROP;

INSERT INTO migration_od_unmapped_guard (
    side,
    raw_code,
    raw_sido,
    raw_sigungu,
    region_sido,
    region_sigungu,
    row_count
)
SELECT
    side,
    raw_code,
    raw_sido,
    raw_sigungu,
    region_sido,
    region_sigungu,
    row_count
FROM migration_od_unmapped_regions;

CREATE TEMP TABLE migration_od_canonical ON COMMIT DROP AS
SELECT
    st.date,
    dest.region_sido AS destination_sido,
    dest.region_sigungu AS destination_sigungu,
    org.region_sido AS origin_sido,
    org.region_sigungu AS origin_sigungu,
    st.total_count,
    st.male_count,
    st.female_count,
    st.raw_json
FROM migration_od_standardized AS st
JOIN region_merge_key AS dest
  ON st.destination_sido = dest.region_sido
 AND st.destination_sigungu = dest.region_sigungu
JOIN region_merge_key AS org
  ON st.origin_sido = org.region_sido
 AND st.origin_sigungu = org.region_sigungu
WHERE NOT (
    dest.region_sido = org.region_sido
    AND dest.region_sigungu = org.region_sigungu
);

CREATE TEMP TABLE migration_od_age_component ON COMMIT DROP AS
SELECT
    canonical.date,
    canonical.destination_sido,
    canonical.destination_sigungu,
    canonical.origin_sido,
    canonical.origin_sigungu,
    CASE WHEN kv.key LIKE 'male%' THEN 'male' ELSE 'female' END AS sex,
    CASE
        WHEN substring(kv.key FROM '[0-9]+')::integer >= 80
            THEN '80-'
        ELSE (
            ((substring(kv.key FROM '[0-9]+')::integer / 5) * 5)::text
            || '-'
            || (((substring(kv.key FROM '[0-9]+')::integer / 5) * 5) + 4)::text
        )
    END AS age,
    coalesce(nullif(regexp_replace(kv.value, '[^0-9-]', '', 'g'), ''), '0')::bigint
        AS move_count
FROM migration_od_canonical AS canonical
CROSS JOIN LATERAL jsonb_each_text(canonical.raw_json) AS kv(key, value)
WHERE kv.key ~ '^(male|feml)[0-9]+AgeNmprCnt$';

CREATE TEMP TABLE migration_od_dimension_base ON COMMIT DROP AS
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    'all'::text AS sex,
    'all'::text AS age,
    SUM(total_count)::bigint AS move_count
FROM migration_od_canonical
GROUP BY
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu
UNION ALL
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    'male'::text AS sex,
    'all'::text AS age,
    SUM(male_count)::bigint AS move_count
FROM migration_od_canonical
GROUP BY
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu
UNION ALL
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    'female'::text AS sex,
    'all'::text AS age,
    SUM(female_count)::bigint AS move_count
FROM migration_od_canonical
GROUP BY
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu
UNION ALL
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    'all'::text AS sex,
    age,
    SUM(move_count)::bigint AS move_count
FROM migration_od_age_component
GROUP BY
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    age
UNION ALL
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    sex,
    age,
    SUM(move_count)::bigint AS move_count
FROM migration_od_age_component
GROUP BY
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    sex,
    age;

INSERT INTO clean.clean_inflow (
    date,
    region_sido,
    region_sigungu,
    from_sido,
    from_sigungu,
    inflow
)
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    move_count
FROM migration_od_dimension_base
WHERE sex = 'all'
  AND age = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_inflow AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, destination_sido, destination_sigungu, origin_sido, origin_sigungu
ON CONFLICT (date, region_sido, region_sigungu, from_sido, from_sigungu) DO NOTHING;

INSERT INTO clean.clean_inflow_sex (
    date,
    region_sido,
    region_sigungu,
    from_sido,
    from_sigungu,
    sex,
    inflow
)
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    sex,
    move_count
FROM migration_od_dimension_base
WHERE age = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_inflow_sex AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, destination_sido, destination_sigungu, origin_sido, origin_sigungu, sex
ON CONFLICT (date, region_sido, region_sigungu, from_sido, from_sigungu, sex) DO NOTHING;

INSERT INTO clean.clean_inflow_age (
    date,
    region_sido,
    region_sigungu,
    from_sido,
    from_sigungu,
    age,
    inflow
)
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    age,
    move_count
FROM migration_od_dimension_base
WHERE sex = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_inflow_age AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, destination_sido, destination_sigungu, origin_sido, origin_sigungu, age
ON CONFLICT (date, region_sido, region_sigungu, from_sido, from_sigungu, age) DO NOTHING;

INSERT INTO clean.clean_inflow_sex_age (
    date,
    region_sido,
    region_sigungu,
    from_sido,
    from_sigungu,
    sex,
    age,
    inflow
)
SELECT
    date,
    destination_sido,
    destination_sigungu,
    origin_sido,
    origin_sigungu,
    sex,
    age,
    move_count
FROM migration_od_dimension_base
WHERE move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_inflow_sex_age AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, destination_sido, destination_sigungu, origin_sido, origin_sigungu, sex, age
ON CONFLICT (date, region_sido, region_sigungu, from_sido, from_sigungu, sex, age)
DO NOTHING;

INSERT INTO clean.clean_outflow (
    date,
    region_sido,
    region_sigungu,
    to_sido,
    to_sigungu,
    outflow
)
SELECT
    date,
    origin_sido,
    origin_sigungu,
    destination_sido,
    destination_sigungu,
    move_count
FROM migration_od_dimension_base
WHERE sex = 'all'
  AND age = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_outflow AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, origin_sido, origin_sigungu, destination_sido, destination_sigungu
ON CONFLICT (date, region_sido, region_sigungu, to_sido, to_sigungu) DO NOTHING;

INSERT INTO clean.clean_outflow_sex (
    date,
    region_sido,
    region_sigungu,
    to_sido,
    to_sigungu,
    sex,
    outflow
)
SELECT
    date,
    origin_sido,
    origin_sigungu,
    destination_sido,
    destination_sigungu,
    sex,
    move_count
FROM migration_od_dimension_base
WHERE age = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_outflow_sex AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, origin_sido, origin_sigungu, destination_sido, destination_sigungu, sex
ON CONFLICT (date, region_sido, region_sigungu, to_sido, to_sigungu, sex) DO NOTHING;

INSERT INTO clean.clean_outflow_age (
    date,
    region_sido,
    region_sigungu,
    to_sido,
    to_sigungu,
    age,
    outflow
)
SELECT
    date,
    origin_sido,
    origin_sigungu,
    destination_sido,
    destination_sigungu,
    age,
    move_count
FROM migration_od_dimension_base
WHERE sex = 'all'
  AND move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_outflow_age AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, origin_sido, origin_sigungu, destination_sido, destination_sigungu, age
ON CONFLICT (date, region_sido, region_sigungu, to_sido, to_sigungu, age) DO NOTHING;

INSERT INTO clean.clean_outflow_sex_age (
    date,
    region_sido,
    region_sigungu,
    to_sido,
    to_sigungu,
    sex,
    age,
    outflow
)
SELECT
    date,
    origin_sido,
    origin_sigungu,
    destination_sido,
    destination_sigungu,
    sex,
    age,
    move_count
FROM migration_od_dimension_base
WHERE move_count > 0
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_outflow_sex_age AS existing
      WHERE existing.date = migration_od_dimension_base.date
  )
ORDER BY date, origin_sido, origin_sigungu, destination_sido, destination_sigungu, sex, age
ON CONFLICT (date, region_sido, region_sigungu, to_sido, to_sigungu, sex, age)
DO NOTHING;

COMMIT;
