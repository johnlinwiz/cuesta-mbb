"""The .ics calendar file: RFC 5545 structure, escaping and long-line folding."""
import json
import re

import pytest

import build
import common
import fetch_results
from build import build_ics, fold, ics_escape


@pytest.fixture
def ics(season_root, offline_sources):
    fetch_results.main()                      # attach last season's results so summaries are long
    sched, _, _, events = common.load()
    return build_ics(sched, events), events


def unfold(text):
    return text.replace("\r\n ", "")


def test_every_line_is_crlf_and_at_most_75_octets(ics):
    text, _ = ics
    assert text.endswith("\r\n")
    assert "\n" not in text.replace("\r\n", "")              # no bare LF anywhere
    lines = text.split("\r\n")[:-1]
    assert max(len(l.encode()) for l in lines) <= 75
    assert any(l.startswith(" ") for l in lines)             # the descriptions really did need folding


def test_structure_and_one_event_per_game(ics):
    text, events = ics
    lines = unfold(text).split("\r\n")[:-1]
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR" and "VERSION:2.0" in lines
    for block in ("VEVENT", "VALARM", "VTIMEZONE", "DAYLIGHT", "STANDARD"):
        assert lines.count(f"BEGIN:{block}") == lines.count(f"END:{block}") > 0
    assert lines.count("BEGIN:VEVENT") == len(events) == 31   # 32 feed rows, 2-day jamboree is one event
    uids = [l for l in lines if l.startswith("UID:")]
    assert len(set(uids)) == len(uids)
    assert all(re.fullmatch(r"[A-Z-]+(;[A-Z-]+=[^:;]+)*:.*", l) for l in lines)   # NAME[;PARAM=v]:value


def test_timed_and_all_day_events(ics):
    text, _ = ics
    events = unfold(text).split("BEGIN:VEVENT")[1:]
    oxnard = next(b for b in events if "UID:2026-01-17-oxnard@" in b)
    assert "DTSTART;TZID=America/Los_Angeles:20260117T130000\r\n" in oxnard
    assert "DTEND;TZID=America/Los_Angeles:20260117T150000\r\n" in oxnard
    jamboree = next(b for b in events if "UID:2025-09-27-norcal-fall-juco-jamboree@" in b)
    assert "DTSTART;VALUE=DATE:20250927\r\n" in jamboree
    assert "DTEND;VALUE=DATE:20250929\r\n" in jamboree        # exclusive end: day after Sep 28


def test_summary_carries_the_result_and_text_is_escaped(ics):
    text, _ = ics
    flat = unfold(text)
    assert "SUMMARY:Cuesta MBB vs Oxnard — W 78-62\r\n" in flat
    assert "SUMMARY:Cuesta MBB @ San Mateo — L 61-70 (OT)\r\n" in flat
    # venue fixture is "Opponent Gym; Main Court" / "1 College Way, Somewhere, CA 90000"
    assert "LOCATION:Opponent Gym\\; Main Court\\, 1 College Way\\, Somewhere\\, CA 90000\r\n" in flat
    desc = next(l for l in flat.split("\r\n") if l.startswith("DESCRIPTION:Non-conference — Away"))
    assert "\\n" in desc and "\n" not in desc


@pytest.mark.parametrize("raw, escaped", [
    ("a,b;c", "a\\,b\\;c"),
    ("line1\nline2", "line1\\nline2"),
    ("back\\slash", "back\\\\slash"),
    ("C:\\new", "C:\\\\new"),                                 # backslash escaped first, so no "\n" is invented
])
def test_ics_escape(raw, escaped):
    assert ics_escape(raw) == escaped


def test_fold_exact_boundaries():
    assert fold("X" * 75) == "X" * 75
    folded = fold("X" * 76)
    first, second = folded.split("\r\n")
    assert (len(first), second) == (75, " X")


def test_fold_never_splits_a_multibyte_character():
    line = "SUMMARY:" + "🏀é—" * 40
    folded = fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert unfold(folded) == line                             # each part decodes on its own -> no split chars


def test_ics_file_written_by_build_main(season_root):
    (season_root / "docs").mkdir()
    build.main()
    raw = (season_root / "docs" / common.ICS_NAME).read_bytes()
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.count(b"BEGIN:VEVENT") == 31
    data = json.loads((season_root / "docs/events.json").read_text())
    assert len(data["events"]) == 31 and data["season"] == "2025-26"
