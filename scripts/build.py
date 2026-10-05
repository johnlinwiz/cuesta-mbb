#!/usr/bin/env python3
"""Generate README.md, CALENDAR.md, venues.geojson, docs/events.json and the .ics feed
from data/schedule.yaml + data/venues.yaml + data/drive_times.json."""
import calendar
import datetime as dt
import json

from common import (ICS_NAME, PAGES_URL, REPO, ROOT, TYPE_LABEL, fmt_dur, load, load_issue_map,
                    maps_dir, maps_place, today_pt)

ICON = {"home": "🏠", "away": "🚌", "neutral": "📍"}


def icon(e):
    return "🏆" if e.is_tournament else ICON[e.site]


def issue_link(e, issues):
    n = issues.get(e.id)
    return f"[#{n}](https://github.com/{REPO}/issues/{n})" if n else ""


def drive_cell(e, origin):
    d = e.drive.get(origin)
    if not d:
        return "—"
    return f"[{fmt_dur(d['minutes'])}]({maps_dir(origin, e.venue)}) · {d['miles']} mi"


# ---------------------------------------------------------------- README.md
def build_readme(sched, venues_cfg, drive, events, issues, today):
    upcoming = [e for e in events if e.end_date >= today]
    out = [
        f"# 🏀 {sched['team']} — {sched['season']}",
        "",
        f"**[📅 Calendar view]({PAGES_URL})** · "
        f"**[➕ Subscribe (.ics)]({PAGES_URL}{ICS_NAME})** · "
        "**[🗓️ Month grids](CALENDAR.md)** · "
        "**[🗺️ Venue map](venues.geojson)** · "
        f"**[🔔 Reminders](https://github.com/{REPO}/issues)**",
        "",
    ]
    if upcoming:
        n = upcoming[0]
        days = (n.date - today).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        out += [
            f"> **Next up ({when}):** {n.title()} — [{n.venue['name']}]({maps_place(n.venue)}), "
            f"{n.venue['city']}  ",
            f"> 🚗 Pasadena {drive_cell(n, 'pasadena')} · SLO {drive_cell(n, 'slo')}",
            "",
        ]
    out += [
        "🏠 home · 🚌 away · 🏆 tournament · `*` Western State Conference · "
        "`?` home/away inferred (poster had no `@`/`Vs`) · ✅ played  ",
        "Drive times are OSRM free-flow estimates (no traffic; run a bit long vs Google) — "
        "click one for live Google Maps directions. All times Pacific.",
        "",
    ]

    month = None
    for e in events:
        if e.date.month != month:
            month = e.date.month
            out += ["", f"## {e.date:%B %Y}", "",
                    "| Date | Time | Game | H/A | Venue | 🚗 From Pasadena | 🚗 From SLO | 🔔 |",
                    "|---|---|---|---|---|---|---|---|"]
        done = "✅ " if e.end_date < today else ""
        game = f"{icon(e)} **{e.matchup}**{e.conf_star}"
        extras = []
        if e.type == "scrimmage":
            extras.append("scrimmage")
        if e.live_stats:
            extras.append("live stats")
        if e.notes:
            extras.append(e.notes)
        if extras:
            game += f"<br><sub>{' · '.join(extras)}</sub>"
        venue = f"[{e.venue['name']}]({maps_place(e.venue)})<br><sub>{e.venue['city']}</sub>"
        out.append(f"| {done}{e.date_label} | {e.time_label} | {game} | {e.site_label} | {venue} | "
                   f"{drive_cell(e, 'pasadena')} | {drive_cell(e, 'slo')} | {issue_link(e, issues)} |")

    # Timeline (Mermaid renders natively on GitHub)
    out += ["", "## Season timeline", "", "```mermaid", "gantt", "    dateFormat YYYY-MM-DD",
            "    axisFormat %b %d", "    todayMarker on"]
    month = None
    for e in events:
        if e.date.month != month:
            month = e.date.month
            out.append(f"    section {e.date:%b}")
        tag = "crit, " if e.site == "home" and not e.is_tournament else "active, " if e.is_tournament else ""
        length = (e.end_date - e.date).days + 1
        label = e.matchup.replace(":", " ").replace("#", "")
        out.append(f"    {label} :{tag}g{e.id.replace('-', '')}, {e.date}, {length}d")
    out += ["```", "<sub>Red = home game · blue = tournament · grey = away</sub>", ""]

    # Venues
    out += ["## Venues", "", "| Venue | City | Games | 🚗 From Pasadena | 🚗 From SLO |",
            "|---|---|---|---|---|"]
    for key, v in venues_cfg["venues"].items():
        games = [e for e in events if e.venue_key == key]
        if not games:
            continue
        d = drive.get(key, {})
        p = d.get("pasadena"); s = d.get("slo")
        out.append(
            f"| [{v['name']}]({maps_place(v)}) | {v['city']} | {len(games)} | "
            + (f"[{fmt_dur(p['minutes'])}]({maps_dir('pasadena', v)}) · {p['miles']} mi" if p else "—") + " | "
            + (f"[{fmt_dur(s['minutes'])}]({maps_dir('slo', v)}) · {s['miles']} mi" if s else "—") + " |")

    out += [
        "", "## How this repo works", "",
        "- `data/schedule.yaml` is the single source of truth (transcribed from the "
        "[@cuesta_mbb](https://www.instagram.com/cuesta_mbb/) poster). `data/venues.yaml` holds addresses.",
        "- `make build` regenerates this README, `CALENDAR.md`, `venues.geojson`, and the GitHub Pages "
        "calendar + `.ics` feed in `docs/`.",
        "- `make issues` creates/updates one GitHub issue per game (the reminders), grouped into monthly milestones.",
        "- A daily GitHub Action (`.github/workflows/daily.yml`) comments on a game's issue "
        f"{', '.join(f'{d}d' for d in sched['reminder_days_before'] if d)} and day-of "
        "(@-mention → GitHub notification/email), closes issues after the game, and refreshes “Next up”.",
        "", f"<sub>Generated by scripts/build.py · status as of {today:%a %b %-d, %Y}</sub>", "",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- CALENDAR.md
def build_calendar_md(sched, events, issues, today):
    by_day = {}
    for e in events:
        d = e.date
        while d <= e.end_date:
            by_day.setdefault(d, []).append(e)
            d += dt.timedelta(days=1)
    months = sorted({(d.year, d.month) for d in by_day})
    out = [f"# 🗓️ {sched['team']} — {sched['season']} month view", "",
           f"[⬅ README](README.md) · [📅 Interactive calendar]({PAGES_URL})", "",
           "🏠 home · 🚌 away · 🏆 tournament · `*` conference · ✅ played", ""]
    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    for y, m in months:
        out += [f"## {calendar.month_name[m]} {y}", "",
                "| Sun | Mon | Tue | Wed | Thu | Fri | Sat |", "|---|---|---|---|---|---|---|"]
        for week in cal.monthdatescalendar(y, m):
            cells = []
            for d in week:
                if d.month != m:
                    cells.append(" ")
                    continue
                txt = f"**{d.day}**" if d == today else str(d.day)
                for e in by_day.get(d, []):
                    t = "" if e.all_day else e.start.strftime("%-I:%M%p").lower().replace(":00", "")
                    n = issues.get(e.id)
                    name = f"{e.matchup}{e.conf_star}"
                    if n:
                        name = f"[{name}](https://github.com/{REPO}/issues/{n})"
                    done = "✅" if e.end_date < today else ""
                    txt += f"<br>{done}{icon(e)} {t} {name}"
                cells.append(txt)
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- venues.geojson
def build_geojson(venues_cfg, drive, events):
    feats = []
    for key, v in venues_cfg["venues"].items():
        games = [e for e in events if e.venue_key == key]
        if not games:
            continue
        home = key == "cuesta"
        d = drive.get(key, {})
        props = {
            "name": v["name"],
            "address": v["address"],
            "games": "; ".join(f"{e.date_label} {e.time_label} {e.matchup}" for e in games),
            "from Pasadena": f"{fmt_dur(d['pasadena']['minutes'])}, {d['pasadena']['miles']} mi" if d else "",
            "from SLO": f"{fmt_dur(d['slo']['minutes'])}, {d['slo']['miles']} mi" if d else "",
            "marker-color": "#0b6e3a" if home else "#555555",
            "marker-symbol": "basketball",
            "marker-size": "large" if home else "medium",
        }
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]}})
    return json.dumps({"type": "FeatureCollection", "features": feats}, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- docs/events.json
def build_events_json(events, issues):
    rows = []
    for e in events:
        r = {
            "id": e.id, "title": f"{e.matchup}{e.conf_star}", "allDay": e.all_day,
            "classNames": ["tourney" if e.is_tournament else e.site, e.type],
            "extendedProps": {
                "matchup": e.matchup, "type": TYPE_LABEL[e.type], "site": e.site_label,
                "time": e.time_label, "dateLabel": e.date_label,
                "venue": e.venue["name"], "city": e.venue["city"], "address": e.venue["address"],
                "map": maps_place(e.venue),
                "dirPasadena": maps_dir("pasadena", e.venue), "dirSlo": maps_dir("slo", e.venue),
                "drivePasadena": e.drive_label("pasadena"), "driveSlo": e.drive_label("slo"),
                "liveStats": e.live_stats, "notes": e.notes, "confirmed": e.site_confirmed,
                "gcal": e.gcal_link(),
                "issue": f"https://github.com/{REPO}/issues/{issues[e.id]}" if e.id in issues else None,
            },
        }
        if e.all_day:
            r["start"] = e.date.isoformat()
            r["end"] = (e.end_date + dt.timedelta(days=1)).isoformat()  # exclusive end
        else:
            r["start"] = e.start.isoformat()
            r["end"] = e.end.isoformat()
        rows.append(r)
    return json.dumps(rows, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- .ics
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/Los_Angeles
BEGIN:DAYLIGHT
TZOFFSETFROM:-0800
TZOFFSETTO:-0700
TZNAME:PDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0700
TZOFFSETTO:-0800
TZNAME:PST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    # RFC 5545: lines > 75 octets are folded with CRLF + space
    b = line.encode()
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        c = ch.encode()
        if len(cur) + len(c) > (75 if not parts else 74):
            parts.append(cur.decode()); cur = b""
        cur += c
    parts.append(cur.decode())
    return "\r\n ".join(parts)


def build_ics(sched, events):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{REPO}//schedule//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:Cuesta MBB {sched['season']}",
             "X-WR-TIMEZONE:America/Los_Angeles", "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
             "X-PUBLISHED-TTL:PT12H", *VTIMEZONE.split("\n")]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e.id}@{REPO.replace('/', '.')}", f"DTSTAMP:{stamp}"]
        if e.all_day:
            lines += [f"DTSTART;VALUE=DATE:{e.date:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{e.end_date + dt.timedelta(days=1):%Y%m%d}"]
        else:
            lines += [f"DTSTART;TZID=America/Los_Angeles:{e.start:%Y%m%dT%H%M%S}",
                      f"DTEND;TZID=America/Los_Angeles:{e.end:%Y%m%dT%H%M%S}"]
        lines += [f"SUMMARY:{ics_escape(e.summary())}",
                  f"LOCATION:{ics_escape(e.venue['name'] + ', ' + e.venue['address'])}",
                  f"GEO:{e.venue['lat']};{e.venue['lon']}",
                  f"DESCRIPTION:{ics_escape(e.description())}",
                  f"URL:{PAGES_URL}",
                  f"CATEGORIES:{ics_escape(TYPE_LABEL[e.type])},{'Home' if e.site == 'home' else 'Away'}"]
        for trig, label in (("-P1D", "tomorrow"), ("-PT3H", "in 3 hours")):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trig}",
                      f"DESCRIPTION:{ics_escape(e.summary())} {label}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    sched, venues_cfg, drive, events = load()
    issues = load_issue_map()
    today = today_pt()
    (ROOT / "README.md").write_text(build_readme(sched, venues_cfg, drive, events, issues, today))
    (ROOT / "CALENDAR.md").write_text(build_calendar_md(sched, events, issues, today))
    (ROOT / "venues.geojson").write_text(build_geojson(venues_cfg, drive, events) + "\n")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/events.json").write_text(build_events_json(events, issues) + "\n")
    (ROOT / "docs" / ICS_NAME).write_bytes(build_ics(sched, events).encode())
    print(f"built {len(events)} events")


if __name__ == "__main__":
    main()
