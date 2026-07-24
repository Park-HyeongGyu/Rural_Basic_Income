BEGIN;

CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.clean_electricity (
    date integer NOT NULL,
    region_sido text NOT NULL,
    region_sigungu text NOT NULL,
    contract_type text NOT NULL,
    customer_count bigint NOT NULL,
    power_usage bigint NOT NULL,
    bill bigint NOT NULL,
    unit_cost numeric NOT NULL,
    contract_power bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS clean_electricity_key
    ON clean.clean_electricity (
        date,
        region_sido,
        region_sigungu,
        contract_type
    );

-- Existing clean dates are immutable in normal runs. If cleaning rules change,
-- rebuild the affected clean tables explicitly before rerunning this SQL.
CREATE TEMP TABLE clean_electricity_base ON COMMIT DROP AS
WITH
sido_by_name(metro, region_sido) AS (
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
missing_dates AS (
    SELECT DISTINCT (btrim(raw_el.year) || lpad(btrim(raw_el.month), 2, '0'))::integer AS date
    FROM raw.electricity AS raw_el
    WHERE NOT EXISTS (
        SELECT 1
        FROM clean.clean_electricity AS existing
        WHERE existing.date = (btrim(raw_el.year) || lpad(btrim(raw_el.month), 2, '0'))::integer
    )
),
prepared AS (
    SELECT
        (btrim(raw_el.year) || lpad(btrim(raw_el.month), 2, '0'))::integer AS date,
        btrim(raw_el.metro) AS raw_metro,
        btrim(raw_el.city) AS raw_region_sigungu,
        regexp_replace(coalesce(raw_el.cntr, ''), '[[:space:]]+', '', 'g') AS contract_type,
        NULLIF(replace(raw_el."custCnt", ',', ''), '')::bigint AS customer_count,
        NULLIF(replace(raw_el."powerUsage", ',', ''), '')::bigint AS power_usage,
        NULLIF(replace(raw_el.bill, ',', ''), '')::bigint AS bill,
        NULLIF(replace(raw_el."unitCost", ',', ''), '')::numeric AS unit_cost,
        NULLIF(replace(raw_el."cntrPwr", ',', ''), '')::bigint AS contract_power
    FROM raw.electricity AS raw_el
    JOIN missing_dates AS md
      ON (btrim(raw_el.year) || lpad(btrim(raw_el.month), 2, '0'))::integer = md.date
),
standardized AS (
    SELECT
        p.date,
        s.region_sido,
        p.raw_region_sigungu AS region_sigungu,
        p.contract_type,
        p.customer_count,
        p.power_usage,
        p.bill,
        p.unit_cost,
        p.contract_power
    FROM prepared AS p
    JOIN sido_by_name AS s
      ON p.raw_metro = s.metro
    WHERE p.contract_type <> ''
      AND p.customer_count IS NOT NULL
      AND p.power_usage IS NOT NULL
      AND p.bill IS NOT NULL
      AND p.unit_cost IS NOT NULL
      AND p.contract_power IS NOT NULL
)
SELECT
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.contract_type,
    SUM(st.customer_count)::bigint AS customer_count,
    SUM(st.power_usage)::bigint AS power_usage,
    SUM(st.bill)::bigint AS bill,
    MAX(st.unit_cost) AS unit_cost,
    SUM(st.contract_power)::bigint AS contract_power
FROM standardized AS st
JOIN region_merge_key AS rk
  ON st.region_sido = rk.region_sido
 AND st.region_sigungu = rk.region_sigungu
GROUP BY
    st.date,
    rk.region_sido,
    rk.region_sigungu,
    st.contract_type;

INSERT INTO clean.clean_electricity (
    date,
    region_sido,
    region_sigungu,
    contract_type,
    customer_count,
    power_usage,
    bill,
    unit_cost,
    contract_power
)
SELECT
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.contract_type,
    base.customer_count,
    base.power_usage,
    base.bill,
    base.unit_cost,
    base.contract_power
FROM clean_electricity_base AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM clean.clean_electricity AS existing
    WHERE existing.date = base.date
)
ORDER BY
    base.date,
    base.region_sido,
    base.region_sigungu,
    base.contract_type
ON CONFLICT (date, region_sido, region_sigungu, contract_type) DO NOTHING;

COMMIT;
