#!/usr/bin/env python3
"""Compare the official 3C2A iCal feed with data/schedule.yaml and flag drift.

Detects: games added to the feed, games that disappeared (cancelled/moved),
tip-off time changes, and feed events marked CANCELLED/POSTPONED.

On drift it keeps ONE open issue labelled `schedule-drift` up to date and
@-mentions the notify users only when the set of differences changes. When
the feed and schedule agree again, that issue is closed.

  python3 scripts/check_feed.py            # print diff only
  python3 scripts/check_feed.py --issue    # also open/update/close the drift issue
"""
import datetime as dt
import hashlib
import re
import subprocess
import sys

from common import REPO, TZ, load, today_pt

UA = "Mozilla/5.0 (compatible; cuesta-mbb-schedule; +https://github.com/johnlinwiz/cuesta-mbb)"
LABEL = "schedule-drift"


def norm(name, aliases):
    n = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    n = aliases.get(n, n)
    for w in (" college", " tournament", " cc"):
        n = n.replace(w, "")
    return re.sub(r"\s+", " ", n).strip()


def fetch_feed(url):
    # curl: works with the CCCAA host where Python's default UA/SSL is sometimes refused.
    r = subprocess.run(["curl", "-sfL", "--max-time", "60", "-A", UA, url], capture_output=True, text=True)
    if r.returncode != 0 or "BEGIN:VCALENDAR" not in r.stdout:
        raise RuntimeError(f"feed fetch failed (curl exit {r.returncode})")
    return r.stdout


def parse_feed(text, team="Cuesta"):
    text = text.replace("\r\n", "\n").replace("\n ", "")  # unfold RFC 5545 lines
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        def field(k):
            m = re.search(rf"^{k}(?:;[^:\n]*)?:(.*)$", block, re.M)
            return m.group(1).strip() if m else ""
        summary = field("SUMMARY").replace("\\,", ",")
        if "Men's Basketball" not in summary or team not in summary:
            continue
        title = re.sub(r"^\(Men's Basketball\)\s*", "", summary)
        m = re.match(rf"^{team} at (.+)$", title) or re.match(rf"^(.+) at {team}$", title) \
            or re.match(rf"^(.+) vs\.? {team}$", title) or re.match(rf"^{team} vs\.? (.+)$", title)
        if not m:
            continue
        opp = m.group(1).strip()
        site = "away" if title.startswith(f"{team} at") else "home" if title.endswith(f"at {team}") else "neutral"
        raw = field("DTSTART")
        if re.fullmatch(r"\d{8}", raw):
            d, t = dt.datetime.strptime(raw, "%Y%m%d").date(), None
        else:
            u = dt.datetime.strptime(raw.rstrip("Z"), "%Y%m%dT%H%M%S")
            local = u.replace(tzinfo=dt.timezone.utc).astimezone(TZ) if raw.endswith("Z") else u.replace(tzinfo=TZ)
            d, t = local.date(), local.strftime("%H:%M")
        status = field("STATUS").upper()
        desc = field("DESCRIPTION").replace("\\,", ",").replace("\\n", " ")
        if re.search(r"\b(postponed|cancel+ed)\b", desc, re.I):
            status = status or "CANCELLED"
        out.append({"date": d, "time": t, "opponent": opp, "site": site, "status": status, "title": title})
    return out


def diff(sched, events, feed, today):
    aliases = {k.lower(): v.lower() for k, v in (sched.get("feed_aliases") or {}).items()}
    ignore = set(sched.get("feed_ignore") or [])
    key = lambda d, opp: (d.isoformat(), norm(opp, aliases))
    ours = {}
    covered = set()   # every (date, opp) a multi-day event spans, so feed day-entries match it
    for e in events:
        if e.end_date < today:
            continue
        ours[key(e.date, e.opponent)] = e
        d = e.date
        while d <= e.end_date:
            covered.add(key(d, e.opponent)); d += dt.timedelta(days=1)
    theirs = {}
    for f in feed:
        if f["date"] < today:
            continue
        k = key(f["date"], f["opponent"])
        if f"{k[0]} {f['opponent']}" in ignore:
            continue
        theirs[k] = f

    rows = []
    for k, f in sorted(theirs.items()):
        e = ours.get(k)
        when = f"{f['date']:%a %b %-d}" + (f" {dt.datetime.strptime(f['time'], '%H:%M'):%-I:%M %p}" if f["time"] else "")
        if f["status"] in ("CANCELLED", "POSTPONED"):
            rows.append(f"❌ **{f['status'].title()} in feed:** {when} — {f['title']}")
        elif not e and k in covered:
            continue  # a later day of a tracked multi-day tournament
        elif not e:
            rows.append(f"➕ **New in feed:** {when} — {f['title']} *(not in schedule.yaml)*")
        elif f["time"] and not e.all_day and f["time"] != e.start.strftime("%H:%M"):
            rows.append(f"🕑 **Time changed:** {e.title()} → feed says {when}")
    for k, e in sorted(ours.items()):
        if k not in theirs:
            rows.append(f"➖ **Missing from feed** (cancelled or moved?): {e.title()}")
    return rows


def gh(*args, input=None):
    r = subprocess.run(["gh", *args], input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def sync_issue(rows, sched, feed_url):
    import json
    repo_flag = ["-R", REPO]
    existing = json.loads(gh("issue", "list", *repo_flag, "--label", LABEL, "--state", "open",
                             "--json", "number,body") or "[]")
    issue = existing[0] if existing else None
    if not rows:
        if issue:
            gh("issue", "comment", str(issue["number"]), *repo_flag,
               "--body", "✅ Feed and schedule.yaml agree again — closing.")
            gh("issue", "close", str(issue["number"]), *repo_flag, "--reason", "completed")
            print(f"closed drift issue #{issue['number']}")
        return
    fp = hashlib.sha1("\n".join(rows).encode()).hexdigest()[:12]
    body = "\n".join([
        "The official schedule feed no longer matches `data/schedule.yaml`.", "",
        *[f"- {r}" for r in rows], "",
        f"Feed: {feed_url}", "",
        "**To resolve:** edit `data/schedule.yaml` (use `replaces: [old-event-id]` when a game moves), "
        "or add a line to `feed_ignore:` for feed entries you deliberately don't track. "
        "This issue closes automatically once they agree.",
        "", f"<!-- drift-fp: {fp} -->"])
    mentions = " ".join("@" + m for m in sched.get("notify", []))
    if not issue:
        gh("label", "create", LABEL, *repo_flag, "--color", "d93f0b",
           "--description", "Official feed differs from schedule.yaml", "--force")
        url = gh("issue", "create", *repo_flag, "--title", "⚠️ Schedule drift: official feed differs",
                 "--label", LABEL, "--body", body)
        n = url.rstrip("/").split("/")[-1]
        gh("issue", "comment", n, *repo_flag, "--body", f"🔔 {mentions} the official schedule changed — see above.")
        print(f"opened drift issue #{n}")
    elif f"drift-fp: {fp}" not in (issue["body"] or ""):
        gh("issue", "edit", str(issue["number"]), *repo_flag, "--body", body)
        gh("issue", "comment", str(issue["number"]), *repo_flag,
           "--body", f"🔔 {mentions} the differences changed — issue body updated.")
        print(f"updated drift issue #{issue['number']}")
    else:
        print(f"drift issue #{issue['number']} already current")


def main():
    sched, _, _, events = load()
    url = sched["feed_url"]
    try:
        feed = parse_feed(fetch_feed(url))
    except Exception as err:  # never fail the daily job because the feed is down
        print(f"::warning::schedule feed check skipped: {err}")
        return 0
    rows = diff(sched, events, feed, today_pt())
    print(f"{len(feed)} feed games, {len(rows)} difference(s)")
    for r in rows:
        print(" ", r)
    if "--issue" in sys.argv:
        sync_issue(rows, sched, url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
