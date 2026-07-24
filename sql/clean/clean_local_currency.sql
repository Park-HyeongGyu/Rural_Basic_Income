BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_local_currency_sex_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    age text NOT NULL,
    payment_amount bigint NOT NULL,
    payment_count bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_local_currency_sex_age_key
    ON clean.clean_local_currency_sex_age (
        date,
        region_sido,
        region_sigungu,
        sex,
        age
    );

CREATE TABLE IF NOT EXISTS clean.clean_local_currency_age (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    age text NOT NULL,
    payment_amount bigint NOT NULL,
    payment_count bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_local_currency_age_key
    ON clean.clean_local_currency_age (date, region_sido, region_sigungu, age);

CREATE TABLE IF NOT EXISTS clean.clean_local_currency_sex (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    sex text NOT NULL,
    payment_amount bigint NOT NULL,
    payment_count bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_local_currency_sex_key
    ON clean.clean_local_currency_sex (date, region_sido, region_sigungu, sex);

CREATE TABLE IF NOT EXISTS clean.clean_local_currency (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    payment_amount bigint NOT NULL,
    payment_count bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_local_currency_key
    ON clean.clean_local_currency (date, region_sido, region_sigungu);

-- Existing clean dates are immutable in normal runs. If cleaning rules change,
-- rebuild the affected clean tables explicitly before rerunning this SQL.
CREATE TEMP TABLE clean_local_currency_missing_dates ON COMMIT DROP AS
SELECT DISTINCT raw_lc.crtr_ym::integer AS date
FROM raw.local_currency AS raw_lc
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_local_currency_sex_age AS existing
    WHERE existing.date = raw_lc.crtr_ym::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_local_currency_age AS existing
    WHERE existing.date = raw_lc.crtr_ym::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_local_currency_sex AS existing
    WHERE existing.date = raw_lc.crtr_ym::integer
)
   OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_local_currency AS existing
    WHERE existing.date = raw_lc.crtr_ym::integer
);

CREATE TEMP TABLE local_currency_unmapped_usage_rgn_cd ON COMMIT DROP AS
SELECT raw_codes.usage_rgn_cd
FROM (
    SELECT DISTINCT
        CASE
            WHEN length(btrim(raw_lc.usage_rgn_cd)) BETWEEN 1 AND 4
                THEN lpad(btrim(raw_lc.usage_rgn_cd), 5, '0')
            ELSE btrim(raw_lc.usage_rgn_cd)
        END AS usage_rgn_cd
    FROM raw.local_currency AS raw_lc
    JOIN clean_local_currency_missing_dates AS md
      ON raw_lc.crtr_ym::integer = md.date
    WHERE NULLIF(btrim(raw_lc.usage_rgn_cd), '') IS NOT NULL
) AS raw_codes
LEFT JOIN local_currency_region_code AS region_code
  ON raw_codes.usage_rgn_cd = region_code.usage_rgn_cd
WHERE region_code.usage_rgn_cd IS NULL;

CREATE TEMP TABLE local_currency_unmapped_guard (
    usage_rgn_cd text NOT NULL,
    CONSTRAINT no_unmapped_local_currency_usage_rgn_cd CHECK (false)
) ON COMMIT DROP;

INSERT INTO local_currency_unmapped_guard (usage_rgn_cd)
SELECT usage_rgn_cd
FROM local_currency_unmapped_usage_rgn_cd;

CREATE TEMP TABLE local_currency_unmatched_regions ON COMMIT DROP AS
SELECT
    region_code.usage_rgn_cd,
    region_code.region_sido,
    region_code.region_sigungu
FROM local_currency_region_code AS region_code
LEFT JOIN region_merge_key AS rk
  ON region_code.region_sido = rk.region_sido
 AND region_code.region_sigungu = rk.region_sigungu
WHERE coalesce(region_code.drop_reason, '') = ''
  AND rk.region_sido IS NULL;

CREATE TEMP TABLE local_currency_unmatched_region_guard (
    usage_rgn_cd text NOT NULL,
    region_sido text,
    region_sigungu text,
    CONSTRAINT no_unmatched_local_currency_region CHECK (false)
) ON COMMIT DROP;

INSERT INTO local_currency_unmatched_region_guard (
    usage_rgn_cd,
    region_sido,
    region_sigungu
)
SELECT
    usage_rgn_cd,
    region_sido,
    region_sigungu
FROM local_currency_unmatched_regions;

CREATE TEMP TABLE clean_local_currency_sex_age_base ON COMMIT DROP AS
WITH prepared AS (
    SELECT
        raw_lc.crtr_ym::integer AS date,
        rk.region_sido,
        rk.region_sigungu,
        CASE regexp_replace(btrim(coalesce(raw_lc.par_gend, '')), '[[:space:]]+', '', 'g')
            WHEN 'M' THEN 'male'
            WHEN 'F' THEN 'female'
            ELSE 'unknown'
        END AS sex,
        CASE lpad(
            nullif(
                regexp_replace(
                    btrim(coalesce(raw_lc.par_ag, '')),
                    '\.0$',
                    ''
                ),
                ''
            ),
            2,
            '0'
        )
            WHEN '01' THEN '0-19'
            WHEN '02' THEN '20-29'
            WHEN '03' THEN '30-39'
            WHEN '04' THEN '40-49'
            WHEN '05' THEN '50-59'
            WHEN '06' THEN '60-'
            WHEN '99' THEN 'unknown'
            ELSE 'unknown'
        END AS age,
        coalesce(nullif(replace(btrim(raw_lc.stlm_amt), ',', ''), ''), '0')::bigint
            AS payment_amount,
        coalesce(nullif(replace(btrim(raw_lc.stlm_nocs), ',', ''), ''), '0')::bigint
            AS payment_count
    FROM raw.local_currency AS raw_lc
    JOIN clean_local_currency_missing_dates AS md
      ON raw_lc.crtr_ym::integer = md.date
    JOIN local_currency_region_code AS region_code
      ON (
          CASE
              WHEN length(btrim(raw_lc.usage_rgn_cd)) BETWEEN 1 AND 4
                  THEN lpad(btrim(raw_lc.usage_rgn_cd), 5, '0')
              ELSE btrim(raw_lc.usage_rgn_cd)
          END
      ) = region_code.usage_rgn_cd
    JOIN region_merge_key AS rk
      ON region_code.region_sido = rk.region_sido
     AND region_code.region_sigungu = rk.region_sigungu
    WHERE coalesce(region_code.drop_reason, '') = ''
)
SELECT
    date,
    region_sido,
    region_sigungu,
    CASE WHEN GROUPING(sex) = 1 THEN 'all' ELSE sex END AS sex,
    CASE WHEN GROUPING(age) = 1 THEN 'all' ELSE age END AS age,
    SUM(payment_amount)::bigint AS payment_amount,
    SUM(payment_count)::bigint AS payment_count
FROM prepared
GROUP BY GROUPING SETS (
    (date, region_sido, region_sigungu, sex, age),
    (date, region_sido, region_sigungu, sex),
    (date, region_sido, region_sigungu, age),
    (date, region_sido, region_sigungu)
);

INSERT INTO clean.clean_local_currency_sex_age (
    date,
    region_sido,
    region_sigungu,
    sex,
    age,
    payment_amount,
    payment_count
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.age,
    base.payment_amount,
    base.payment_count
FROM clean_local_currency_sex_age_base AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_local_currency_sex_age AS existing
    WHERE existing.date = base.date
)
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex, base.age
ON CONFLICT (date, region_sido, region_sigungu, sex, age) DO NOTHING;

INSERT INTO clean.clean_local_currency_age (
    date,
    region_sido,
    region_sigungu,
    age,
    payment_amount,
    payment_count
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.age,
    base.payment_amount,
    base.payment_count
FROM clean_local_currency_sex_age_base AS base
WHERE base.sex = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_local_currency_age AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.age
ON CONFLICT (date, region_sido, region_sigungu, age) DO NOTHING;

INSERT INTO clean.clean_local_currency_sex (
    date,
    region_sido,
    region_sigungu,
    sex,
    payment_amount,
    payment_count
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.sex,
    base.payment_amount,
    base.payment_count
FROM clean_local_currency_sex_age_base AS base
WHERE base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_local_currency_sex AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu, base.sex
ON CONFLICT (date, region_sido, region_sigungu, sex) DO NOTHING;

INSERT INTO clean.clean_local_currency (
    date,
    region_sido,
    region_sigungu,
    payment_amount,
    payment_count
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.payment_amount,
    base.payment_count
FROM clean_local_currency_sex_age_base AS base
WHERE base.sex = 'all'
  AND base.age = 'all'
  AND NOT EXISTS (
      SELECT 1
      FROM clean.clean_local_currency AS existing
      WHERE existing.date = base.date
  )
ORDER BY base.date, base.region_sido, base.region_sigungu
ON CONFLICT (date, region_sido, region_sigungu) DO NOTHING;

COMMIT;
