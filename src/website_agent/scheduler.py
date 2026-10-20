from datetime import timedelta
from zoneinfo import ZoneInfo

import holidays
from sqlalchemy import select

from website_agent.database import LocationQueue, aware, now
from website_agent.security import Blocked


def workday(day, country, subdivision=None):
    if country not in holidays.list_supported_countries():
        raise Blocked("Holiday calendar unavailable for country; configure/review support first")
    calendar = holidays.country_holidays(country, subdiv=subdivision, years=[day.year])
    return day.weekday() not in calendar.weekend and day not in calendar


def contact_time(at, country, timezone, hours, subdivision=None):
    local = at.astimezone(ZoneInfo(timezone))
    return workday(local.date(), country, subdivision) and hours[0] <= local.hour < hours[1]


def business_due(sent_at, country, timezone, subdivision=None, days=5):
    local = aware(sent_at).astimezone(ZoneInfo(timezone))
    count = 0
    while count < days:
        local += timedelta(days=1)
        count += int(workday(local.date(), country, subdivision))
    return local


def rotate(session, config, country=None, at=None, exclude_cities=None):
    at = at or now()
    for location in config.locations:
        for niche in config.niches:
            row = session.scalar(
                select(LocationQueue).where(
                    LocationQueue.country == location.country,
                    LocationQueue.city == location.city,
                    LocationQueue.niche == niche,
                )
            )
            if not row:
                session.add(LocationQueue(country=location.country, city=location.city, niche=niche))
    session.commit()
    candidates = []
    rows = list(session.scalars(select(LocationQueue)))
    counts = {c: sum(r.searches for r in rows if r.country == c) for c in {r.country for r in rows}}
    configured_countries = {loc.country for loc in config.locations}
    minimum = min((counts[c] for c in configured_countries), default=0)
    for row in rows:
        if exclude_cities and (row.country, row.city) in exclude_cities:
            continue
        location = next(
            (loc for loc in config.locations if loc.country == row.country and loc.city == row.city), None
        )
        if not location or row.niche not in config.niches or (country and row.country != country):
            continue
        # Wait for an underserved country's local window instead of repeatedly selecting
        # countries that happen to be awake at the UTC heartbeat time.
        if not country and counts[row.country] > minimum:
            continue
        if not contact_time(
            at, location.country, location.timezone, config.research_hours, location.subdivision
        ):
            continue
        age = (at - aware(row.last_search)).total_seconds() / 86400 if row.last_search else 100000
        if age < 1:
            continue
        # Country fairness first, then age dominates a bounded relevance preference.
        candidates.append(
            (
                counts[row.country],
                -(age + min(row.relevant / max(row.searches, 1), 1)),
                row.city,
                row.niche,
                row,
                location,
            )
        )
    if not candidates:
        return None
    _, _, _, _, row, location = min(candidates, key=lambda c: c[:4])
    row.last_search, row.searches = at, row.searches + 1
    session.commit()
    return row, location
