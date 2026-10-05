#!/usr/bin/env python3
"""Create/update one GitHub issue per game (the "reminder" for that event).

Idempotent: each issue body carries a hidden `<!-- event-id: ... -->` marker, so
re-running updates titles/bodies/labels in place instead of duplicating.
Writes the event-id -> issue-number map to data/issues.json.
"""
import calendar
import json

import gh
from common import ICS_NAME, PAGES_URL, ROOT, TYPE_LABEL, fmt_dur, load, maps_dir, maps_place

LABELS = {
    "home": ("0b6e3a", "Home game at Cuesta"),
    "away": ("5b6670", "Away game"),
    "tournament": ("c9a227", "Multi-day tournament"),
    "conference": ("6f42c1", "Western State Conference game"),
    "non-conference": ("bfd4f2", "Non-conference game"),
    "scrimmage": ("e4e669", "Scrimmage"),
    "site-unconfirmed": ("d93f0b", "Home/away inferred from poster — confirm"),
}


def labels_for(e):
    ls = ["tournament" if e.is_tournament else e.site]
    ls.append(e.type if e.type != "tournament" else None)
    if not e.site_confirmed:
        ls.append("site-unconfirmed")
    return [l for l in ls if l]


def drive_row(e, origin, label):
    d = e.drive.get(origin)
    if not d:
        return f"| **🚗 From {label}** | — |"
    return f"| **🚗 From {label}** | [{fmt_dur(d['minutes'])}]({maps_dir(origin, e.venue)}) · {d['miles']} mi |"


def body_for(e, sched):
    when = e.date_label + (", " + str(e.date.year))
    when += "" if e.all_day else f" · **{e.time_label} PT**"
    rows = [
        f"## 🏀 Cuesta {e.matchup}{e.conf_star}", "",
        "| | |", "|---|---|",
        f"| **When** | {when} |",
        f"| **Game** | {TYPE_LABEL[e.type]} — {e.site_label} |",
        f"| **Venue** | [{e.venue['name']}]({maps_place(e.venue)}) |",
        f"| **Address** | {e.venue['address']} |",
        drive_row(e, "pasadena", "Pasadena"),
        drive_row(e, "slo", "SLO"),
    ]
    if e.live_stats:
        rows.append("| **Live stats** | 📊 Yes |")
    if e.notes:
        rows.append(f"| **Note** | {e.notes} |")
    rows.append("")
    if not e.site_confirmed:
        rows += ["> [!WARNING]", "> Home/away is inferred — the poster had no `@`/`Vs` for this game. "
                 "Confirm before traveling.", ""]
    if e.all_day:
        rows += ["> [!NOTE]", "> Tournament schedule/times TBA — update `data/schedule.yaml` when the bracket is out.", ""]
    days = ", ".join(f"{d} days" for d in sched["reminder_days_before"] if d)
    rows += [
        f"**Add to calendar:** [Google Calendar]({e.gcal_link()}) · "
        f"[Season .ics feed]({PAGES_URL}{ICS_NAME}) · [Calendar view]({PAGES_URL})", "",
        f"🔔 A reminder comment is posted {days} before and on game day; this issue closes after the game.",
        "", "<sub>Drive times: OSRM free-flow estimate (no traffic). Links open live Google Maps directions.</sub>",
        "", f"<!-- event-id: {e.id} -->",
    ]
    return "\n".join(rows)


def ensure_labels():
    have = {l["name"] for l in gh.api("labels?per_page=100", paginate=True)}
    for name, (color, desc) in LABELS.items():
        if name not in have:
            gh.api("labels", "POST", {"name": name, "color": color, "description": desc})


def ensure_milestones(events):
    have = {m["title"]: m["number"] for m in gh.api("milestones?state=all&per_page=100", paginate=True)}
    out = {}
    for y, m in sorted({(e.date.year, e.date.month) for e in events}):
        title = f"{calendar.month_name[m]} {y}"
        if title not in have:
            last = calendar.monthrange(y, m)[1]
            ms = gh.api("milestones", "POST", {"title": title, "due_on": f"{y}-{m:02d}-{last}T23:00:00Z",
                                                 "description": f"Cuesta MBB games in {title}"})
            have[title] = ms["number"]
        out[(y, m)] = have[title]
    return out


def main():
    sched, _, _, events = load()
    ensure_labels()
    milestones = ensure_milestones(events)
    existing = {}
    for iss in gh.api("issues?state=all&per_page=100", paginate=True):
        body = iss.get("body") or ""
        if "<!-- event-id: " in body and "pull_request" not in iss:
            eid = body.split("<!-- event-id: ", 1)[1].split(" -->", 1)[0]
            existing[eid] = iss["number"]

    issue_map = {}
    for e in events:
        payload = {"title": e.title(), "body": body_for(e, sched), "labels": labels_for(e),
                   "milestone": milestones[(e.date.year, e.date.month)]}
        if e.id in existing:
            n = existing[e.id]
            gh.api(f"issues/{n}", "PATCH", payload)
            print(f"updated #{n} {e.title()}")
        else:
            n = gh.api("issues", "POST", payload)["number"]
            print(f"created #{n} {e.title()}")
        issue_map[e.id] = n
    (ROOT / "data/issues.json").write_text(json.dumps(issue_map, indent=2) + "\n")


if __name__ == "__main__":
    main()
