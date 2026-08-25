BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_inflow_web (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    aggregate_inflow bigint NOT NULL,
    over_300k_inflow bigint NOT NULL,
    population_decline_inflow bigint NOT NULL,
    other_inflow bigint NOT NULL,
    CONSTRAINT clean_inflow_web_nonnegative_values CHECK (
        aggregate_inflow >= 0
        AND over_300k_inflow >= 0
        AND population_decline_inflow >= 0
        AND other_inflow >= 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_inflow_web_key
    ON clean.clean_inflow_web (date, region_sido, region_sigungu);

CREATE TABLE IF NOT EXISTS clean.clean_outflow_web (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    aggregate_outflow bigint NOT NULL,
    over_300k_outflow bigint NOT NULL,
    population_decline_outflow bigint NOT NULL,
    other_outflow bigint NOT NULL,
    CONSTRAINT clean_outflow_web_nonnegative_values CHECK (
        aggregate_outflow >= 0
        AND over_300k_outflow >= 0
        AND population_decline_outflow >= 0
        AND other_outflow >= 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_outflow_web_key
    ON clean.clean_outflow_web (date, region_sido, region_sigungu);

CREATE INDEX IF NOT EXISTS clean_inflow_date_from_region_idx
    ON clean.clean_inflow (date, from_sido, from_sigungu);

CREATE INDEX IF NOT EXISTS clean_outflow_date_to_region_idx
    ON clean.clean_outflow (date, to_sido, to_sigungu);

CREATE TEMP TABLE migration_web_source_date_mismatch ON COMMIT DROP AS
WITH inflow_dates AS (
    SELECT DISTINCT date
    FROM clean.clean_inflow
),
outflow_dates AS (
    SELECT DISTINCT date
    FROM clean.clean_outflow
)
SELECT
    'inflow_without_outflow' AS mismatch_type,
    inflow_dates.date
FROM inflow_dates
LEFT JOIN outflow_dates
    ON outflow_dates.date = inflow_dates.date
WHERE outflow_dates.date IS NULL
UNION ALL
SELECT
    'outflow_without_inflow' AS mismatch_type,
    outflow_dates.date
FROM outflow_dates
LEFT JOIN inflow_dates
    ON inflow_dates.date = outflow_dates.date
WHERE inflow_dates.date IS NULL;

CREATE TEMP TABLE migration_web_source_date_guard (
    mismatch_type text NOT NULL,
    date integer NOT NULL,
    CONSTRAINT no_migration_web_source_date_mismatch CHECK (false)
) ON COMMIT DROP;

INSERT INTO migration_web_source_date_guard (
    mismatch_type,
    date
)
SELECT
    mismatch_type,
    date
FROM migration_web_source_date_mismatch;

CREATE TEMP TABLE clean_migration_web_missing_dates ON COMMIT DROP AS
WITH source_dates AS (
    SELECT DISTINCT date
    FROM clean.clean_inflow
    INTERSECT
    SELECT DISTINCT date
    FROM clean.clean_outflow
)
SELECT source_dates.date
FROM source_dates
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow_web AS existing
    WHERE existing.date = source_dates.date
)
OR NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow_web AS existing
    WHERE existing.date = source_dates.date
)
ORDER BY source_dates.date;

DELETE FROM clean.clean_inflow_web
WHERE date IN (SELECT date FROM clean_migration_web_missing_dates);

DELETE FROM clean.clean_outflow_web
WHERE date IN (SELECT date FROM clean_migration_web_missing_dates);

CREATE TEMP TABLE migration_web_missing_baseline_regions ON COMMIT DROP AS
SELECT DISTINCT
    'inflow_origin' AS region_role,
    inflow.from_sido AS region_sido,
    inflow.from_sigungu AS region_sigungu
FROM clean.clean_inflow AS inflow
JOIN clean_migration_web_missing_dates AS md
    ON md.date = inflow.date
LEFT JOIN population_baseline_202509 AS pop
    ON pop.region_sido = inflow.from_sido
   AND pop.region_sigungu = inflow.from_sigungu
WHERE pop.region_sido IS NULL
UNION
SELECT DISTINCT
    'outflow_destination' AS region_role,
    outflow.to_sido AS region_sido,
    outflow.to_sigungu AS region_sigungu
FROM clean.clean_outflow AS outflow
JOIN clean_migration_web_missing_dates AS md
    ON md.date = outflow.date
LEFT JOIN population_baseline_202509 AS pop
    ON pop.region_sido = outflow.to_sido
   AND pop.region_sigungu = outflow.to_sigungu
WHERE pop.region_sido IS NULL;

CREATE TEMP TABLE migration_web_baseline_guard (
    region_role text NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    CONSTRAINT no_missing_migration_web_population_baseline CHECK (false)
) ON COMMIT DROP;

INSERT INTO migration_web_baseline_guard (
    region_role,
    region_sido,
    region_sigungu
)
SELECT
    region_role,
    region_sido,
    region_sigungu
FROM migration_web_missing_baseline_regions;

CREATE TEMP TABLE migration_web_inflow_grouped ON COMMIT DROP AS
WITH classified AS (
    SELECT
        inflow.date,
        inflow.region_sido,
        inflow.region_sigungu,
        inflow.inflow::bigint AS inflow,
        pop.population >= 300000 AS is_over_300k,
        decline.region_sido IS NOT NULL AS is_population_decline
    FROM clean.clean_inflow AS inflow
    JOIN clean_migration_web_missing_dates AS md
        ON md.date = inflow.date
    JOIN population_baseline_202509 AS pop
        ON pop.region_sido = inflow.from_sido
       AND pop.region_sigungu = inflow.from_sigungu
    LEFT JOIN population_decline_region AS decline
        ON decline.region_sido = inflow.from_sido
       AND decline.region_sigungu = inflow.from_sigungu
)
SELECT
    date,
    region_sido,
    region_sigungu,
    SUM(inflow)::bigint AS aggregate_inflow,
    SUM(CASE WHEN is_over_300k THEN inflow ELSE 0 END)::bigint
        AS over_300k_inflow,
    SUM(
        CASE
            WHEN NOT is_over_300k AND is_population_decline THEN inflow
            ELSE 0
        END
    )::bigint AS population_decline_inflow
FROM classified
GROUP BY
    date,
    region_sido,
    region_sigungu;

CREATE TEMP TABLE migration_web_outflow_grouped ON COMMIT DROP AS
WITH classified AS (
    SELECT
        outflow.date,
        outflow.region_sido,
        outflow.region_sigungu,
        outflow.outflow::bigint AS outflow,
        pop.population >= 300000 AS is_over_300k,
        decline.region_sido IS NOT NULL AS is_population_decline
    FROM clean.clean_outflow AS outflow
    JOIN clean_migration_web_missing_dates AS md
        ON md.date = outflow.date
    JOIN population_baseline_202509 AS pop
        ON pop.region_sido = outflow.to_sido
       AND pop.region_sigungu = outflow.to_sigungu
    LEFT JOIN population_decline_region AS decline
        ON decline.region_sido = outflow.to_sido
       AND decline.region_sigungu = outflow.to_sigungu
)
SELECT
    date,
    region_sido,
    region_sigungu,
    SUM(outflow)::bigint AS aggregate_outflow,
    SUM(CASE WHEN is_over_300k THEN outflow ELSE 0 END)::bigint
        AS over_300k_outflow,
    SUM(
        CASE
            WHEN NOT is_over_300k AND is_population_decline THEN outflow
            ELSE 0
        END
    )::bigint AS population_decline_outflow
FROM classified
GROUP BY
    date,
    region_sido,
    region_sigungu;

INSERT INTO clean.clean_inflow_web (
    date,
    region_sido,
    region_sigungu,
    aggregate_inflow,
    over_300k_inflow,
    population_decline_inflow,
    other_inflow
)
SELECT
    grouped.date,
    grouped.region_sido,
    grouped.region_sigungu,
    grouped.aggregate_inflow,
    grouped.over_300k_inflow,
    grouped.population_decline_inflow,
    grouped.aggregate_inflow
        - grouped.over_300k_inflow
        - grouped.population_decline_inflow AS other_inflow
FROM migration_web_inflow_grouped AS grouped
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_inflow_web AS existing
    WHERE existing.date = grouped.date
      AND existing.region_sido = grouped.region_sido
      AND existing.region_sigungu = grouped.region_sigungu
);

INSERT INTO clean.clean_outflow_web (
    date,
    region_sido,
    region_sigungu,
    aggregate_outflow,
    over_300k_outflow,
    population_decline_outflow,
    other_outflow
)
SELECT
    grouped.date,
    grouped.region_sido,
    grouped.region_sigungu,
    grouped.aggregate_outflow,
    grouped.over_300k_outflow,
    grouped.population_decline_outflow,
    grouped.aggregate_outflow
        - grouped.over_300k_outflow
        - grouped.population_decline_outflow AS other_outflow
FROM migration_web_outflow_grouped AS grouped
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_outflow_web AS existing
    WHERE existing.date = grouped.date
      AND existing.region_sido = grouped.region_sido
      AND existing.region_sigungu = grouped.region_sigungu
);

COMMIT;
