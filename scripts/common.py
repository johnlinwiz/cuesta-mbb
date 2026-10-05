"""Shared loading/formatting for the Cuesta MBB schedule generators."""
import datetime as dt
import json
import pathlib
import re
from urllib.parse import quote_plus, urlencode
from zoneinfo import ZoneInfo

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "johnlinwiz/cuesta-mbb-2026-27"
PAGES_URL = "https://johnlinwiz.github.io/cuesta-mbb-2026-27/"
ICS_NAME = "cuesta-mbb-2026-27.ics"
TZ = ZoneInfo("America/Los_Angeles")

ORIGIN_QUERY = {"pasadena": "Pasadena, CA", "slo": "San Luis Obispo, CA"}
TYPE_LABEL = {
    "scrimmage": "Scrimmage",
    "non-conference": "Non-conference",
    "conference": "WSC conference",
    "tournament": "Tournament",
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fmt_dur(minutes):
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def fmt_time(t):
    return t.strftime("%-I:%M %p")


def maps_place(v):
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{v['name']}, {v['address']}")


def maps_dir(origin_key, v):
    return "https://www.google.com/maps/dir/?api=1&" + urlencode(
        {"origin": ORIGIN_QUERY[origin_key], "destination": v["address"], "travelmode": "driving"})


class Event:
    def __init__(self, raw, venues, drive, defaults):
        self.raw = raw
        self.date = raw["date"] if isinstance(raw["date"], dt.date) else dt.date.fromisoformat(raw["date"])
        end = raw.get("end_date")
        self.end_date = (end if isinstance(end, dt.date) else dt.date.fromisoformat(end)) if end else self.date
        self.opponent = raw["opponent"]
        self.site = raw["site"]
        self.site_confirmed = raw.get("site_confirmed", True)
        self.type = raw["type"]
        self.live_stats = raw.get("live_stats", False)
        self.notes = raw.get("notes", "")
        self.venue_key = raw["venue"]
        self.venue = venues[self.venue_key]
        self.drive = drive.get(self.venue_key, {})
        self.all_day = "time" not in raw
        if self.all_day:
            self.start = self.end = None
        else:
            h, m = map(int, raw["time"].split(":"))
            self.start = dt.datetime.combine(self.date, dt.time(h, m), TZ)
            self.end = self.start + dt.timedelta(minutes=raw.get("duration_min", defaults["default_duration_min"]))
        self.id = f"{self.date.isoformat()}-{slug(self.opponent)}"

    # --- display helpers -------------------------------------------------
    @property
    def is_tournament(self):
        return self.type == "tournament"

    @property
    def matchup(self):
        if self.is_tournament and self.all_day:
            return self.opponent
        return f"{'@' if self.site == 'away' else 'vs'} {self.opponent}"

    @property
    def site_label(self):
        base = {"home": "Home", "away": "Away", "neutral": "Neutral"}[self.site]
        return base if self.site_confirmed else f"{base}?"

    @property
    def date_label(self):
        if self.end_date != self.date:
            return f"{self.date.strftime('%a %b %-d')}–{self.end_date.strftime('%a %-d')}"
        return self.date.strftime("%a %b %-d")

    @property
    def time_label(self):
        return "TBA" if self.all_day else fmt_time(self.start)

    @property
    def conf_star(self):
        return "*" if self.type == "conference" else ""

    def title(self):
        bits = [f"{self.date_label}", self.time_label, f"{self.matchup}{self.conf_star}"]
        if self.type == "scrimmage":
            bits.append("(scrimmage)")
        return " · ".join(bits)

    def summary(self):
        """Calendar event title."""
        s = f"Cuesta MBB {self.matchup}"
        if self.type == "scrimmage":
            s += " (scrimmage)"
        return s

    def drive_label(self, origin):
        d = self.drive.get(origin)
        return f"{fmt_dur(d['minutes'])} · {d['miles']} mi" if d else "—"

    def gcal_link(self):
        if self.all_day:
            dates = f"{self.date:%Y%m%d}/{self.end_date + dt.timedelta(days=1):%Y%m%d}"
        else:
            dates = f"{self.start:%Y%m%dT%H%M%S}/{self.end:%Y%m%dT%H%M%S}"
        return "https://calendar.google.com/calendar/render?" + urlencode({
            "action": "TEMPLATE", "text": self.summary(), "dates": dates, "ctz": "America/Los_Angeles",
            "location": f"{self.venue['name']}, {self.venue['address']}",
            "details": self.description(plain=True)})

    def description(self, plain=False):
        lines = [
            f"{TYPE_LABEL[self.type]} — {self.site_label}",
            f"Venue: {self.venue['name']}, {self.venue['address']}",
            f"Map: {maps_place(self.venue)}",
            f"Drive from Pasadena: {self.drive_label('pasadena')}",
            f"Drive from SLO: {self.drive_label('slo')}",
        ]
        if self.live_stats:
            lines.append("Live stats available")
        if self.notes:
            lines.append(f"Note: {self.notes}")
        if not self.site_confirmed:
            lines.append("Home/away inferred (no @/Vs on poster) — confirm before traveling")
        if not plain:
            lines.append(f"Season calendar: {PAGES_URL}")
        return "\n".join(lines)


def load():
    sched = yaml.safe_load((ROOT / "data/schedule.yaml").read_text())
    venues_cfg = yaml.safe_load((ROOT / "data/venues.yaml").read_text())
    drive_path = ROOT / "data/drive_times.json"
    drive = json.loads(drive_path.read_text()) if drive_path.exists() else {}
    events = [Event(g, venues_cfg["venues"], drive, sched) for g in sched["games"]]
    events.sort(key=lambda e: (e.date, e.start or dt.datetime.min.replace(tzinfo=TZ)))
    return sched, venues_cfg, drive, events


def load_issue_map():
    p = ROOT / "data/issues.json"
    return json.loads(p.read_text()) if p.exists() else {}


def today_pt():
    return dt.datetime.now(TZ).date()
