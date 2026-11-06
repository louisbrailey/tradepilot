"""Pinned NYSE session dates, 2026-2028. Unknown years fail closed.
Source: https://www.nyse.com/trade/hours-calendars (checked 2026-11-05).
20:15 ET evaluation also covers published early closes. Unexpected closures
produce a missing-bar hold, never a fabricated session.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
HOLIDAYS = {
    2026: '01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25',
    2027: '01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24',
    2028: '01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25',
}


def session(day):
    if day.year not in HOLIDAYS:
        raise ValueError('Session calendar needs renewal; supported years are 2026–2028')
    return day.weekday() < 5 and day.strftime('%m-%d') not in HOLIDAYS[day.year].split()


def next_session(day):
    day += timedelta(days=1)
    while not session(day):
        day += timedelta(days=1)
    return day


def history_days(day, count=50):
    days = []
    while len(days) < count:
        if session(day):
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(days))


def local_time(now):
    return datetime.fromtimestamp(now, ET)


def ready(now):
    at = local_time(now)
    return session(at.date()) and (at.hour, at.minute) >= (20, 15)
