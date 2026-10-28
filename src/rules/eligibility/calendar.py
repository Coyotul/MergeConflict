"""Explicit calendar conventions for the synthetic reference policy."""

import calendar
from datetime import date


def add_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, month = divmod(absolute_month, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def completed_years(birth_date: date, on_date: date) -> int:
    return on_date.year - birth_date.year - (
        (on_date.month, on_date.day) < (birth_date.month, birth_date.day)
    )