"""Reading the league iCal feed: times across DST, titles with scores, forfeits, filtering."""
import datetime as dt

import pytest

import fetch_results
from check_feed import parse_feed
from helpers import read
from fetch_results import feed_rows, parse_score

D = dt.date


def vevent(dtstart, summary, desc="", status="CONFIRMED", url=None):
    lines = ["BEGIN:VEVENT", f"DTSTART:{dtstart}", f"SUMMARY:{summary}", f"DESCRIPTION:{desc}", f"STATUS:{status}"]
    if url:
        lines.append(f"URL:{url}")
    return "\r\n".join(lines + ["END:VEVENT"])


def cal(*events):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", *events, "END:VCALENDAR"]) + "\r\n"


@pytest.fixture(scope="module")
def feed():
    return parse_feed(read("league.ics"))


def test_feed_only_cuesta_mens_games(feed):
    text = read("league.ics")
    assert text.count("BEGIN:VEVENT") > len(feed)       # fixture keeps other teams' games to filter out
    assert len(feed) == 32
    assert all("Cuesta" not in f["opponent"] for f in feed)


# ---------------------------------------------------------------- time zones
@pytest.mark.parametrize("dtstart, date, time", [
    ("20261114T210000Z", D(2026, 11, 14), "13:00"),   # the Shasta bug: after DST ends Nov 1 -> 1:00 PM PST, not 2:00
    ("20261031T200000Z", D(2026, 10, 31), "13:00"),   # day before the change -> PDT
    ("20261101T090000Z", D(2026, 11, 1), "01:00"),    # 1 AM on change day, second time round (PST)
    ("20261106T020000Z", D(2026, 11, 5), "18:00"),    # 6 PM PT game lands on the NEXT UTC date
    ("20270315T020000Z", D(2027, 3, 14), "19:00"),    # DST back on (Mar 14 2027)
    ("20261114T130000", D(2026, 11, 14), "13:00"),    # floating local time is taken as Pacific
    ("20261218", D(2026, 12, 18), None),              # all-day
])
def test_feed_converts_times_to_pacific(dtstart, date, time):
    (row,) = parse_feed(cal(vevent(dtstart, "(Men's Basketball) Cuesta vs. Shasta")))
    assert (row["date"], row["time"]) == (date, time)


def test_feed_fixture_times_around_dst(feed):
    by = {(f["date"], f["opponent"]): f for f in feed}
    assert by[(D(2025, 10, 4), "Bakersfield")]["time"] == "13:00"       # PDT, 20:00Z
    assert by[(D(2025, 11, 4), "De Anza")]["time"] == "18:00"           # PST, stamped 2025-11-05T02:00Z
    assert by[(D(2025, 11, 14), "San Joaquin Delta")]["time"] == "13:00"
    assert by[(D(2025, 9, 27), "NorCal Fall JUCO Jamboree")]["time"] is None


# ---------------------------------------------------------------- titles and scores
def test_feed_strips_score_from_title_and_attributes_it(feed):
    oxnard_home = next(f for f in feed if f["date"] == D(2026, 1, 17))
    assert oxnard_home["title"] == "Oxnard at Cuesta"           # was "Oxnard at Cuesta (62-78)"
    assert (oxnard_home["opponent"], oxnard_home["site"]) == ("Oxnard", "home")
    assert (oxnard_home["us"], oxnard_home["them"]) == (78, 62)   # title order: Oxnard 62, Cuesta 78
    de_anza = next(f for f in feed if f["opponent"] == "De Anza")
    assert (de_anza["site"], de_anza["us"], de_anza["them"]) == ("away", 78, 102)


@pytest.mark.parametrize("summary, opp, site, us, them", [
    ("(Men's Basketball) Cuesta at Ventura (83-112)", "Ventura", "away", 83, 112),
    ("(Men's Basketball) Ventura at Cuesta (114-101)", "Ventura", "home", 101, 114),
    ("(Men's Basketball) Cuesta vs. Cypress (70-65)", "Cypress", "neutral", 70, 65),
    ("(Men's Basketball) Redwoods vs. Cuesta (81-64)", "Redwoods", "neutral", 64, 81),
    ("(Men's Basketball) Cuesta at Santa Ana", "Santa Ana", "away", None, None),
])
def test_feed_title_forms(summary, opp, site, us, them):
    (row,) = parse_feed(cal(vevent("20261229T230000Z", summary, "Final")))
    assert (row["opponent"], row["site"], row.get("us"), row.get("them")) == (opp, site, us, them)


def test_feed_ignores_other_sports_and_teams():
    rows = parse_feed(cal(
        vevent("20261229T230000Z", "(Women's Basketball) Cuesta at Ventura (60-50)"),
        vevent("20261229T230000Z", "(Men's Basketball) Oxnard at Ventura (60-50)"),
        vevent("20261229T230000Z", "(Men's Basketball) Cuesta at Ventura")))
    assert [r["opponent"] for r in rows] == ["Ventura"]


def test_feed_unfolds_long_lines():
    folded = "BEGIN:VEVENT\r\nDTSTART:20261229T230000Z\r\nSUMMARY:(Men's Basketball) Cuesta at Monterey Pen\r\n insula (70-61)\r\nEND:VEVENT"
    (row,) = parse_feed(cal(folded))
    assert (row["opponent"], row["us"]) == ("Monterey Peninsula", 70)


def test_feed_forfeit_and_overtime(feed):
    shasta = next(f for f in feed if f["opponent"] == "Shasta")
    assert (shasta["us"], shasta["them"], shasta["forfeit"]) == (2, 0, True)
    assert [f["opponent"] for f in feed if f.get("forfeit")] == ["Shasta"]
    assert {(f["date"], f["opponent"]) for f in feed if f.get("ot")} == {
        (D(2025, 11, 13), "San Mateo"), (D(2026, 1, 24), "LA Pierce")}


def test_feed_rows_build_results(monkeypatch):
    monkeypatch.setattr(fetch_results, "fetch_feed", lambda url: read("league.ics"))
    rows = feed_rows({"feed_url": "https://www.cccaasports.org/sports/mbkb/2025-26/schedule?print=ical"})
    assert len(rows) == 28                                   # only scored games
    by = {(r["date"], r["opponent"]): r for r in rows}
    assert by[(D(2026, 1, 17), "Oxnard")]["raw"] == "W, 78-62"
    assert by[(D(2025, 11, 13), "San Mateo")]["raw"] == "L, 70-61 (OT)"
    assert fetch_results.to_result(by[(D(2025, 11, 13), "San Mateo")])["ot"] == "OT"
    assert by[(D(2025, 12, 30), "Shasta")]["forfeit"] is True
    assert by[(D(2025, 11, 4), "De Anza")]["boxscore"].startswith("https://www.cccaasports.org/links/")


def test_feed_matches_team_site_scores():
    """Both sources give the identical date/opponent/score set for last season."""
    from helpers import TEAM_URL
    feed_set = {(f["date"], f["opponent"], f["us"], f["them"]) for f in parse_feed(read("league.ics")) if "us" in f}
    html = fetch_results.parse_page(read("team-schedule.html"), TEAM_URL)
    html_set = {(r["date"], r["opponent"], *parse_score(r["raw"])[1:]) for r in html if parse_score(r["raw"])}
    assert feed_set == html_set and len(feed_set) == 28


@pytest.mark.parametrize("status, desc, expected", [
    ("", "Men's Basketball: Cuesta at Ventura\\, Postponed", "CANCELLED"),   # only said in the description
    ("", "Men's Basketball: Cuesta at Ventura\\, Cancelled", "CANCELLED"),
    ("CANCELLED", "Men's Basketball: Cuesta at Ventura", "CANCELLED"),
    ("CONFIRMED", "Men's Basketball: Cuesta at Ventura", "CONFIRMED"),
])
def test_feed_cancelled_or_postponed(status, desc, expected):
    (row,) = parse_feed(cal(vevent("20261229T230000Z", "(Men's Basketball) Cuesta at Ventura", desc, status=status)))
    assert row["status"] == expected
