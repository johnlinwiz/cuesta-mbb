"""Reading scores from the team site (PrestoSports HTML) and the 3C2A game log."""
import datetime as dt

import pytest

from helpers import LEAGUE_URL, TEAM_URL, read
from fetch_results import parse_league_page, parse_page, parse_score, to_result

D = dt.date


@pytest.mark.parametrize("raw, expected", [
    ("L, 102-78", ("L", 78, 102)),          # Presto lists the winner's score first...
    ("W, 81-74", ("W", 81, 74)),
    ("W, 62-78", ("W", 78, 62)),            # ...but never trust the order: W always gets the high score
    ("L 55-57", ("L", 55, 57)),
    ("W 70-62", ("W", 70, 62)),             # manual `result:` style in schedule.yaml
    ("W, 81-74 (OT)", ("W", 81, 74)),
    ("  T, 70 - 70", ("T", 70, 70)),
])
def test_parse_score_winner_first(raw, expected):
    assert parse_score(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "TBA", "Final", "Postponed", "70-62", "X, 1-0"])
def test_parse_score_rejects_non_scores(raw):
    assert parse_score(raw) is None


@pytest.mark.parametrize("row, raw, ot", [
    ({"status": "Final - OT"}, "L, 70-61", "OT"),     # team site: OT only in the status column
    ({"status": "Final - 2OT"}, "W, 90-88", "2OT"),
    ({"status": "Final"}, "W, 81-74 (OT)", "OT"),
    ({"status": "Final"}, "W, 81-74 (2OT)", "2OT"),   # used to be missed: "(2OT" isn't "(OT"
    ({"status": "Final"}, "W, 81-74", None),
])
def test_to_result_overtime(row, raw, ot):
    assert to_result(row, raw).get("ot") == ot


def test_to_result_forfeit_is_two_nil_without_box_score():
    assert to_result({"status": "FinalForfeit Home", "raw": "W, 2-0"})["forfeit"] is True
    assert "forfeit" not in to_result({"status": "Final", "raw": "W, 2-0", "boxscore": "https://x/box"})
    assert to_result({"raw": "L, 79-61", "forfeit": True})["forfeit"] is True   # feed flags it explicitly


def test_to_result_shape_and_links():
    r = to_result({"status": "Final", "raw": "L, 102-78", "boxscore": "https://b", "recap": "https://r"})
    assert r == {"outcome": "L", "us": 78, "them": 102, "score": "78-102", "raw": "L, 102-78",
                 "status": "Final", "boxscore": "https://b", "recap": "https://r"}
    assert to_result({"raw": "TBA"}) is None


# ---------------------------------------------------------------- team site (PrestoSports)
@pytest.fixture(scope="module")
def team_rows():
    return parse_page(read("team-schedule.html"), TEAM_URL)


def test_team_site_lists_every_game(team_rows):
    assert len(team_rows) == 32
    assert sum(bool(parse_score(r["raw"])) for r in team_rows) == 28
    assert [r["opponent"] for r in team_rows if r["exhibition"]] == [
        "NorCal Fall JUCO Jamboree", "NorCal Fall JUCO Jamboree", "Bakersfield", "Hartnell"]


def test_team_site_scores_attach_to_the_right_game(team_rows):
    by = {(r["date"], r["opponent"]): r for r in team_rows}
    de_anza = to_result(by[(D(2025, 11, 4), "De Anza")])
    assert (de_anza["outcome"], de_anza["us"], de_anza["them"]) == ("L", 78, 102)
    oxnard = to_result(by[(D(2026, 1, 17), "Oxnard")])
    assert (oxnard["outcome"], oxnard["us"], oxnard["them"]) == ("W", 78, 62)
    assert by[(D(2026, 1, 17), "Oxnard")]["site"] == "home"
    assert by[(D(2026, 2, 11), "Oxnard")]["site"] == "away"
    assert by[(D(2025, 12, 13), "Oxnard")]["site"] == "neutral"


def test_team_site_overtime_games(team_rows):
    ot = {(r["date"], r["opponent"]) for r in team_rows if (res := to_result(r)) and res.get("ot")}
    assert ot == {(D(2025, 11, 13), "San Mateo"), (D(2026, 1, 24), "LA Pierce")}


def test_team_site_forfeit(team_rows):
    shasta = next(r for r in team_rows if r["opponent"] == "Shasta")
    res = to_result(shasta)
    assert (res["outcome"], res["us"], res["them"], res.get("forfeit")) == ("W", 2, 0, True)
    assert "boxscore" not in shasta
    assert [r["opponent"] for r in team_rows if (x := to_result(r)) and x.get("forfeit")] == ["Shasta"]


def test_team_site_links_are_absolute(team_rows):
    scored = [r for r in team_rows if parse_score(r["raw"])]
    assert all(r["boxscore"].startswith("https://www.cuestaathletics.com/") for r in scored if r.get("boxscore"))
    assert sum("boxscore" in r for r in scored) == 27            # everything but the forfeit
    recaps = [r for r in scored if r.get("recap")]
    assert recaps and all(r["recap"].startswith("https://www.cuestaathletics.com/") for r in recaps)


# ---------------------------------------------------------------- 3C2A game log
@pytest.fixture(scope="module")
def league_rows():
    return parse_league_page(read("league-gamelog.html"), LEAGUE_URL, "2025-26")


def test_league_page_dedupes_repeated_stat_tables(league_rows):
    page = read("league-gamelog.html")
    assert page.count("November 13 06:00 PM: at San Mateo") > 1      # the page really repeats each game
    assert len(league_rows) == 32
    assert len({(r["date"], r["opponent"]) for r in league_rows}) == 32
    assert sum(bool(parse_score(r["raw"])) for r in league_rows) == 28


def test_league_page_season_year_rollover(league_rows):
    assert league_rows[0]["date"] == D(2025, 9, 27)
    assert league_rows[-1]["date"] == D(2026, 2, 20)
    assert [r["date"] for r in league_rows] == sorted(r["date"] for r in league_rows)


def test_league_page_sites_and_names(league_rows):
    by = {(r["date"], r["opponent"]): r for r in league_rows}
    assert by[(D(2025, 11, 13), "San Mateo")]["site"] == "away"        # "at San Mateo"
    assert by[(D(2025, 11, 14), "San Joaquin Delta")]["site"] == "neutral"   # "vs. San Joaquin Delta"
    assert by[(D(2026, 1, 17), "Oxnard")]["site"] == "home"
    assert not any(r["opponent"].startswith(("at ", "vs")) or r["opponent"].endswith(("*", "#")) for r in league_rows)
    assert by[(D(2025, 10, 24), "Hartnell")]["exhibition"] is True


def test_league_page_box_scores_and_forfeit(league_rows):
    box = next(r for r in league_rows if r["opponent"] == "San Mateo")["boxscore"]
    assert box == "https://www.cccaasports.org/sports/mbkb/2025-26/boxscores/20251113_lutz.xml"
    shasta = next(r for r in league_rows if r["opponent"] == "Shasta")
    assert to_result(shasta)["forfeit"] is True


def test_team_site_and_league_log_agree(team_rows, league_rows):
    def scores(rows):
        return {(r["date"], r["opponent"], parse_score(r["raw"])) for r in rows if parse_score(r["raw"])}
    assert scores(team_rows) == scores(league_rows)
