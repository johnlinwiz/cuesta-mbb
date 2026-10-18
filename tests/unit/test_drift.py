"""Schedule-change detection: league feed vs schedule.yaml (check_feed.diff)."""
import datetime as dt

import pytest

from check_feed import diff, parse_feed
from common import Event
from helpers import read

D = dt.date
VENUES = {"v": {"name": "Gym", "address": "1 Main St", "city": "X, CA", "lat": 35.0, "lon": -120.0}}
SCHED = {"default_duration_min": 120, "feed_aliases": {"la pierce college": "la pierce"},
         "feed_ignore": ["2026-11-13 American River Tournament"]}
TODAY = D(2026, 10, 18)


def ev(date, opponent, time=None, site="away", type="non-conference", **kw):
    raw = {"date": date, "opponent": opponent, "site": site, "venue": "v", "type": type, **kw}
    if time:
        raw["time"] = time
    return Event(raw, VENUES, {}, SCHED)


def fd(date, opponent, time=None, status="CONFIRMED", site="away"):
    return {"date": D.fromisoformat(date), "time": time, "opponent": opponent, "site": site,
            "status": status, "title": f"Cuesta at {opponent}"}


def run(events, feed, today=TODAY):
    return diff(SCHED, events, feed, today)


def test_no_drift_when_they_agree():
    events = [ev("2026-10-29", "Gavilan", "18:00"), ev("2026-11-07", "Diablo Valley", "15:00", site="home")]
    feed = [fd("2026-10-29", "Gavilan", "18:00"), fd("2026-11-07", "Diablo Valley College", "15:00")]
    assert run(events, feed) == []          # " College" suffix is normalised away


def test_added_game():
    (row,) = run([ev("2026-10-29", "Gavilan", "18:00")],
                 [fd("2026-10-29", "Gavilan", "18:00"), fd("2026-11-03", "Monterey Peninsula", "15:00")])
    assert row.startswith("➕") and "Tue Nov 3 3:00 PM" in row and "Monterey Peninsula" in row


def test_missing_game():
    (row,) = run([ev("2026-10-29", "Gavilan", "18:00"), ev("2026-11-03", "Monterey Peninsula", "15:00")],
                 [fd("2026-10-29", "Gavilan", "18:00")])
    assert row.startswith("➖") and "Monterey Peninsula" in row and "Tue Nov 3" in row


def test_retimed_game():
    (row,) = run([ev("2026-11-14", "Shasta", "13:00", site="neutral")], [fd("2026-11-14", "Shasta", "14:00")])
    assert row.startswith("🕑") and "1:00 PM" in row and "2:00 PM" in row


def test_moved_to_another_day_is_one_added_plus_one_missing():
    rows = run([ev("2026-10-23", "West Valley", "14:00", type="scrimmage")], [fd("2026-10-24", "West Valley", "14:00")])
    assert sorted(r[0] for r in rows) == sorted(["➕", "➖"])


@pytest.mark.parametrize("status", ["CANCELLED", "POSTPONED"])
def test_cancelled_game(status):
    (row,) = run([ev("2026-12-02", "Coalinga", "18:00")], [fd("2026-12-02", "Coalinga", "18:00", status=status)])
    assert row.startswith("❌") and status.title() in row


def test_cancelled_from_real_feed_text():
    text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261203T020000Z\r\n"
            "SUMMARY:(Men's Basketball) Cuesta at Coalinga\r\nDESCRIPTION:Men's Basketball\\, Postponed\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
    (row,) = run([ev("2026-12-02", "Coalinga", "18:00")], parse_feed(text))
    assert row.startswith("❌ **Cancelled")


def test_multi_day_tournament_covers_every_day():
    events = [ev("2026-12-18", "San Joaquin Delta Tournament", end_date="2026-12-20", site="neutral", type="tournament")]
    feed = [fd("2026-12-18", "San Joaquin Delta Tournament"), fd("2026-12-19", "San Joaquin Delta Tournament"),
            fd("2026-12-20", "San Joaquin Delta Tournament")]
    assert run(events, feed) == []


def test_all_day_event_has_no_time_to_compare():
    events = [ev("2026-12-18", "San Joaquin Delta Tournament", end_date="2026-12-20", site="neutral", type="tournament")]
    assert run(events, [fd("2026-12-18", "San Joaquin Delta Tournament", "12:00")]) == []


def test_feed_ignore_and_aliases():
    events = [ev("2026-11-13", "Feather River", "18:00", site="neutral"), ev("2027-01-23", "LA Pierce", "15:00")]
    feed = [fd("2026-11-13", "American River Tournament"),          # deliberately untracked wrapper
            fd("2026-11-13", "Feather River", "18:00"), fd("2027-01-23", "LA Pierce College", "15:00")]
    assert run(events, feed) == []


def test_past_games_are_not_reported():
    events = [ev("2026-10-01", "Old Opponent", "18:00")]
    assert run(events, [fd("2026-10-02", "Someone Else", "18:00")]) == []
    # a multi-day event still in progress counts
    events = [ev("2026-10-17", "Fall Jamboree", end_date="2026-10-19", type="scrimmage")]
    (row,) = run(events, [])
    assert row.startswith("➖") and "Fall Jamboree" in row


def test_last_season_feed_matches_last_season_schedule(season):
    sched, _, _, events = season
    assert diff(sched, events, parse_feed(read("league.ics")), D(2025, 9, 1)) == []
