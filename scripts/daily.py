#!/usr/bin/env python3
"""Daily job: post reminder comments on upcoming games' issues and close finished ones.

Run by .github/workflows/daily.yml. Safe to run repeatedly — each reminder comment
carries a hidden marker so it is posted at most once per issue.
"""
import datetime as dt
import sys

import gh
from common import (fmt_dur, load, load_issue_map, maps_dir, maps_place, record_label, result_games,
                    result_label, today_pt)

BUFFER_MIN = 30  # arrive this long before tip-off


def leave_by(e, origin):
    d = e.drive.get(origin)
    if not d or e.all_day:
        return None
    return e.start - dt.timedelta(minutes=d["minutes"] + BUFFER_MIN)


def reminder_body(e, days, mentions):
    when = {0: "**Today!**", 1: "**Tomorrow**"}.get(days, f"**In {days} days**")
    lines = [f"🔔 {' '.join('@' + m for m in mentions)} {when} — Cuesta {e.matchup}{e.conf_star}", "",
             f"- 🕑 {e.date_label} · {e.time_label} PT",
             f"- 📍 [{e.venue['name']}]({maps_place(e.venue)}) — {e.venue['address']}"]
    for origin, label in (("pasadena", "Pasadena"), ("slo", "SLO")):
        d = e.drive.get(origin)
        if not d:
            continue
        lb = leave_by(e, origin)
        extra = f" → leave by **{lb.strftime('%-I:%M %p')}**" if lb and d["minutes"] > 20 else ""
        lines.append(f"- 🚗 From {label}: [{fmt_dur(d['minutes'])}]({maps_dir(origin, e.venue)}) "
                     f"· {d['miles']} mi{extra}")
    if e.video:
        lines.append(f"- 📺 **Watch live:** [{e.video_label}]({e.video})")
    if e.audio:
        lines.append(f"- 🎙️ Audio: {e.audio}")
    if e.stats:
        lines.append(f"- 📊 [Live stats / box score]({e.stats})")
    elif e.live_stats:
        lines.append("- 📊 Live stats available")
    if not e.site_confirmed:
        lines.append("- ⚠️ Home/away inferred from poster — confirm before you go")
    if any(e.drive.get(o) for o in ("pasadena", "slo")) and not e.all_day:
        lines.append(f"\n<sub>Leave-by = OSRM drive estimate + {BUFFER_MIN} min buffer; check live traffic.</sub>")
    lines.append(f"\n<!-- reminder:{days}d -->")
    return "\n".join(lines)


def result_body(e, games, mentions, record):
    lines = []
    for g in games:
        icon = {"W": "🟢", "L": "🔴"}.get(g["outcome"], "⚪")
        who = f" vs {g['opponent']}" if g.get("opponent") else ""
        links = " · ".join(f"[{lbl}]({g[k]})" for k, lbl in (("boxscore", "Box score"), ("recap", "Recap")) if g.get(k))
        lines.append(f"{icon} **Final{who}: Cuesta {result_label(g)}**" + (f" — {links}" if links else ""))
    head = f"🏁 {' '.join('@' + m for m in mentions)} Cuesta {e.matchup}{e.conf_star}"
    tail = [f"", f"Season record: **{record}**"] if record and e.type != "scrimmage" else []
    return "\n".join([head, "", *lines, *tail, "", "<!-- result -->"])


def main():
    sched, _, _, events = load()
    issues = load_issue_map()
    mentions = sched.get("notify", [])
    today = today_pt()
    for e in events:
        n = issues.get(e.id)
        if not n:
            continue
        days = (e.date - today).days
        if days in sched["reminder_days_before"]:
            marker = f"<!-- reminder:{days}d -->"
            comments = gh.api(f"issues/{n}/comments?per_page=100", paginate=True)
            if not any(marker in (c.get("body") or "") for c in comments):
                gh.api(f"issues/{n}/comments", "POST", {"body": reminder_body(e, days, mentions)})
                print(f"#{n}: posted {days}d reminder")
        if e.end_date < today:
            games = result_games(e)
            iss = gh.api(f"issues/{n}")
            comments = None
            if games:   # post the final score once (scores often land after the issue already closed)
                comments = gh.api(f"issues/{n}/comments?per_page=100")
                if not any("<!-- result -->" in (c.get("body") or "") for c in comments):
                    gh.api(f"issues/{n}/comments", "POST", {"body": result_body(e, games, mentions, record_label(events))})
                    print(f"#{n}: posted result")
            if iss["state"] == "open":
                if not games:
                    gh.api(f"issues/{n}/comments", "POST", {"body":
                           "🏁 Game day has passed — closing. The final score will be added here once it's posted "
                           "(scrimmages usually aren't scored; add `result: \"W 70-62\"` in schedule.yaml if you know it)."})
                gh.api(f"issues/{n}", "PATCH", {"state": "closed", "state_reason": "completed"})
                print(f"#{n}: closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
