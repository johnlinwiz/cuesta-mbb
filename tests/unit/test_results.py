"""Results: last season's games -> data/results.json -> record, end to end through fetch_results.main()."""
import json

import pytest
import yaml

import common
import fetch_results
from common import record_label, result_label, season_record


def results_json(root):
    return json.loads((root / "data/results.json").read_text())


def edit_games(root, fn):
    p = root / "data/schedule.yaml"
    sched = yaml.safe_load(p.read_text())
    sched["games"] = fn(sched["games"])
    p.write_text(yaml.safe_dump(sched, sort_keys=False))


def as_tournament(games, start, end, name):
    """Replace the individually listed games in [start, end] with one all-day multi-day event."""
    inside = [g for g in games if start <= str(g["date"]) <= end]
    keep = [g for g in games if g not in inside]
    keep.append({"date": start, "end_date": end, "opponent": name, "site": "neutral", "venue": "neutral",
                 "type": "tournament"})
    return keep


@pytest.fixture
def run_main(season_root, offline_sources, capsys):
    def go():
        assert fetch_results.main() == 0
        return results_json(season_root), common.load()[3], capsys.readouterr().out
    return go


def test_last_season_record(run_main):
    results, events, out = run_main()
    assert "league iCal + team site" in out
    assert season_record(events) == (10, 18, 5, 7)          # site: Overall 10-18, Conf. 5-7
    assert record_label(events) == "10-18 (WSC 5-7)"
    scored = [r for r in results.values() if not r.get("manual")]
    assert len(scored) == 28


def test_results_keep_overtime_forfeit_and_links(run_main):
    results, _, _ = run_main()
    assert results["2025-11-13-san-mateo"]["ot"] == "OT"
    assert result_label(results["2025-11-13-san-mateo"]) == "L 61-70 (OT)"
    assert result_label(results["2026-01-24-la-pierce"]) == "W 82-78 (OT)"
    assert results["2025-12-30-shasta"]["forfeit"] is True
    assert result_label(results["2025-12-30-shasta"]) == "W (forfeit)"
    assert result_label(results["2025-12-30-shasta"], short=True) == "W FF"
    mendocino = results["2025-11-07-mendocino"]
    assert mendocino["recap"].startswith("https://www.cuestaathletics.com/")   # recap only exists on the team site
    assert mendocino["boxscore"].startswith("https://www.cuestaathletics.com/")


def test_manual_result_override_and_scrimmages_not_in_record(run_main):
    results, events, _ = run_main()
    hartnell = results["2025-10-24-hartnell"]
    assert hartnell["manual"] is True and (hartnell["us"], hartnell["them"]) == (70, 62)
    assert season_record(events)[:2] == (10, 18)             # the scrimmage W doesn't count


def test_tournament_games_grouped_under_the_event(season_root, run_main):
    edit_games(season_root, lambda g: as_tournament(g, "2025-12-19", "2025-12-20", "Kris Kringle Tournament"))
    results, events, _ = run_main()
    games = results["2025-12-19-kris-kringle-tournament"]["games"]
    assert [(g["date"], g["opponent"], g["outcome"], g["us"], g["them"]) for g in games] == [
        ("2025-12-19", "Redwoods", "L", 64, 81), ("2025-12-20", "Foothill", "L", 69, 114)]
    assert season_record(events) == (10, 18, 5, 7)


def test_tournament_named_after_its_host_gets_every_game(season_root, run_main):
    # Day 1 is vs the host, so "Redwoods Tournament" normalises to the same key as that one game.
    edit_games(season_root, lambda g: as_tournament(g, "2025-12-19", "2025-12-20", "Redwoods Tournament"))
    results, events, _ = run_main()
    assert [g["opponent"] for g in results["2025-12-19-redwoods-tournament"]["games"]] == ["Redwoods", "Foothill"]
    assert season_record(events)[:2] == (10, 18)


def test_tournament_range_does_not_double_count_separately_listed_games(season_root, run_main):
    def fn(games):
        out = as_tournament(games, "2025-12-11", "2025-12-13", "SBCC/ECC Holiday Classic")
        out.append({"date": "2025-12-12", "time": "13:00", "opponent": "El Camino", "site": "away",
                    "venue": "away", "type": "non-conference"})
        return out
    edit_games(season_root, fn)
    results, events, _ = run_main()
    assert [g["opponent"] for g in results["2025-12-11-sbcc-ecc-holiday-classic"]["games"]] == ["LA Valley", "Oxnard"]
    assert results["2025-12-12-el-camino"]["outcome"] == "W"
    assert season_record(events)[:2] == (10, 18)


def test_fetch_failure_keeps_yesterdays_results(season_root, monkeypatch, capsys):
    (season_root / "data/results.json").write_text(json.dumps({
        "2025-11-04-de-anza": {"outcome": "L", "us": 78, "them": 102},
        "2025-10-04-bakersfield": {"outcome": "W", "us": 1, "them": 0, "manual": True}}))   # manual entry was removed
    monkeypatch.setattr(fetch_results, "get_rows", lambda sched: (_ for _ in ()).throw(RuntimeError("all down")))
    assert fetch_results.main() == 0
    assert "::warning::results fetch skipped: all down" in capsys.readouterr().out
    results = results_json(season_root)
    assert results["2025-11-04-de-anza"]["us"] == 78
    assert "2025-10-04-bakersfield" not in results
    assert results["2025-10-24-hartnell"]["manual"] is True


def boom(*a, **k):
    raise RuntimeError("HTTP 403")


def test_get_rows_falls_back_to_team_site(season, offline_sources, monkeypatch):
    monkeypatch.setattr(fetch_results, "fetch_feed", boom)
    rows, src = fetch_results.get_rows(season[0])
    assert src == "team site" and len(rows) == 32


def test_get_rows_falls_back_to_league_game_log(season, offline_sources, monkeypatch):
    monkeypatch.setattr(fetch_results, "fetch_feed", boom)
    real = offline_sources
    monkeypatch.setattr(fetch_results, "fetch",
                        lambda url, must_contain="event-row": boom() if "cuestaathletics" in url else real(url, must_contain))
    rows, src = fetch_results.get_rows(season[0])
    assert src == "3C2A" and sum(bool(fetch_results.parse_score(r["raw"])) for r in rows) == 28


def test_get_rows_feed_survives_team_site_block(season, offline_sources, monkeypatch):
    monkeypatch.setattr(fetch_results, "fetch", boom)
    rows, src = fetch_results.get_rows(season[0])
    assert src.startswith("league iCal (team site unavailable") and len(rows) == 28


def test_get_rows_all_sources_down(season, monkeypatch):
    monkeypatch.setattr(fetch_results, "fetch_feed", boom)
    monkeypatch.setattr(fetch_results, "fetch", boom)
    with pytest.raises(RuntimeError, match=r"HTTP 403; HTTP 403; HTTP 403"):
        fetch_results.get_rows(season[0])


def test_results_show_in_calendar_text(run_main):
    _, events, _ = run_main()
    oxnard = next(e for e in events if e.id == "2026-01-17-oxnard")
    assert oxnard.summary() == "Cuesta MBB vs Oxnard — W 78-62"
    assert "Final: W 78-62" in oxnard.description()
