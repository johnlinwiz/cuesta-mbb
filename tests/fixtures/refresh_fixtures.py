#!/usr/bin/env python3
"""Re-download and trim the saved source pages the unit tests run against.

    python3 tests/fixtures/refresh_fixtures.py            # 2025-26 (default)
    python3 tests/fixtures/refresh_fixtures.py 2026-27    # another season, into tests/fixtures/2026-27/

Uses curl (the macOS system Python can't do TLS to these hosts) with a browser-ish
User-Agent. Trimming keeps every byte the parsers look at and drops the rest so the
repo stays small:
  * HTML: <script>, <style>, <svg> blocks, comments and indentation removed.
  * iCal: header + every VEVENT that mentions Cuesta + the first 12 other events
    (so the "not our game" filter still has something to filter).
Tests assert on the parsed result, so after refreshing a *past* season they should still pass.
"""
import pathlib
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SOURCES = {
    "team-schedule.html": "https://www.cuestaathletics.com/sports/mbkb/{s}/schedule",
    "league-gamelog.html": "https://www.cccaasports.org/sports/mbkb/{s}/teams/cuesta?view=schedule",
    "league.ics": "https://www.cccaasports.org/sports/mbkb/{s}/schedule?print=ical",
}
OTHER_EVENTS = 12


def fetch(url):
    r = subprocess.run(["curl", "-sfL", "--max-time", "90", "-A", UA, url], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"curl {url} failed (exit {r.returncode})")
    return r.stdout.decode("utf-8")


def trim_html(page):
    for tag in ("script", "style", "svg"):
        page = re.sub(rf"<{tag}\b.*?</{tag}>", "", page, flags=re.S | re.I)
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    page = re.sub(r"^[ \t]+", "", page, flags=re.M)        # indentation only
    return re.sub(r"\n\s*\n+", "\n", page)


def trim_ics(text):
    head, *events = text.split("BEGIN:VEVENT")
    tail = "END:VCALENDAR\r\n"
    keep, others = [], 0
    for ev in events:
        ev = ev.replace("END:VCALENDAR\r\n", "").replace("END:VCALENDAR", "")
        if "Cuesta" in ev:
            keep.append(ev)
        elif others < OTHER_EVENTS:
            keep.append(ev); others += 1
    return head + "".join("BEGIN:VEVENT" + ev for ev in keep) + tail


def main():
    season = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
    out = pathlib.Path(__file__).resolve().parent / season
    out.mkdir(exist_ok=True)
    for name, url in SOURCES.items():
        body = fetch(url.format(s=season))
        body = trim_ics(body) if name.endswith(".ics") else trim_html(body)
        # newline="" keeps the iCal CRLFs exactly as served
        with open(out / name, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        print(f"{out / name}: {len(body.encode()):,} bytes")


if __name__ == "__main__":
    main()
