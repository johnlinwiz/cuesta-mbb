"""Shared test plumbing.

The scripts import each other as top-level modules (`from common import ...`), exactly as
they do when run as `python3 scripts/x.py`, so scripts/ goes on sys.path here.
"""
import pathlib
import shutil
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

from helpers import SEASON, read  # noqa: E402


@pytest.fixture
def season_root(tmp_path, monkeypatch):
    """A throwaway repo root holding last season's data/ files; common.load() reads from it.

    Never touches the real data/ directory.
    """
    import common
    import fetch_results
    data = tmp_path / "data"
    data.mkdir()
    for name in ("schedule.yaml", "venues.yaml", "drive_times.json"):
        shutil.copy(SEASON / name, data / name)
    for mod in (common, fetch_results):
        monkeypatch.setattr(mod, "ROOT", tmp_path)
    try:
        import build
        import sync_issues
        monkeypatch.setattr(build, "ROOT", tmp_path)
        monkeypatch.setattr(sync_issues, "ROOT", tmp_path)
    except ImportError:
        pass
    return tmp_path


@pytest.fixture
def season(season_root):
    """(sched, venues_cfg, drive, events) for 2025-26, with no results attached."""
    import common
    return common.load()


@pytest.fixture
def offline_sources(monkeypatch):
    """Point every network fetch at the saved 2025-26 copies (fetch, fetch_feed)."""
    import fetch_results
    pages = {"cuestaathletics.com": "team-schedule.html", "teams/cuesta": "league-gamelog.html"}

    def fake_fetch(url, must_contain="event-row"):
        for needle, name in pages.items():
            if needle in url:
                body = read(name)
                assert must_contain in body
                return body
        raise RuntimeError(f"unexpected fetch {url}")

    monkeypatch.setattr(fetch_results, "fetch", fake_fetch)
    monkeypatch.setattr(fetch_results, "fetch_feed", lambda url: read("league.ics"))
    return fake_fetch
