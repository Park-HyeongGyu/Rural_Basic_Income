from __future__ import annotations

from dataclasses import dataclass

SEX_PREFIXES = {
    "male": "male",
    "female": "feml",
}
SOURCE_AGES = range(111)


@dataclass(frozen=True)
class AgeBucket:
    label: str
    ages: range

    @property
    def sql_suffix(self) -> str:
        if self.label.endswith("-"):
            return f"{self.label[:-1]}_plus"
        return self.label.replace("-", "_").replace("+", "plus")


AGE_BUCKETS = tuple(
    AgeBucket(f"{start}-{start + 4}", range(start, start + 5))
    for start in range(0, 80, 5)
) + (AgeBucket("80-", range(80, 111)),)

BASIC_RAW_COLUMNS = (
    "statsYm",
    "mvinAdmmCd",
    "mvinCtpvNm",
    "mvinSggNm",
    "mvinDongNm",
    "mvtAdmmCd",
    "mvtCtpvNm",
    "mvtSggNm",
    "mvtDongNm",
    "totNmprCnt",
    "maleNmprCnt",
    "femlNmprCnt",
)
AGE_RAW_COLUMNS = tuple(
    f"{prefix}{age}AgeNmprCnt"
    for prefix in SEX_PREFIXES.values()
    for age in SOURCE_AGES
)
RAW_COLUMNS = (*BASIC_RAW_COLUMNS, *AGE_RAW_COLUMNS, "downloaded_at")


def age_raw_column(sex: str, age: int) -> str:
    prefix = SEX_PREFIXES[sex]
    return f"{prefix}{age}AgeNmprCnt"


def bucket_sql_column(sex: str, bucket: AgeBucket) -> str:
    return f"{sex}_{bucket.sql_suffix}".replace("__", "_")
