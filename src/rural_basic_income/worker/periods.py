from __future__ import annotations


def validate_period(period: str) -> str:
    if len(period) != 6 or not period.isdigit():
        raise ValueError(f"period must be YYYYMM: {period}")

    month = int(period[4:6])
    if month < 1 or month > 12:
        raise ValueError(f"period month must be 01-12: {period}")

    return period


def iter_month_periods(start_period: str, end_period: str) -> list[str]:
    start = validate_period(start_period)
    end = validate_period(end_period)
    start_year = int(start[:4])
    start_month = int(start[4:6])
    end_year = int(end[:4])
    end_month = int(end[4:6])

    if (start_year, start_month) > (end_year, end_month):
        raise ValueError("start_period must be before or equal to end_period")

    periods = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        periods.append(f"{year:04d}{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1

    return periods
