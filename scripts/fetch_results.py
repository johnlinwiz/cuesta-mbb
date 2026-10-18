#!/usr/bin/env python3
"""Scrape final scores from the team's official (PrestoSports) schedule page.

Writes data/results.json: {event_id: {outcome, us, them, score, status, boxscore, recap, raw}}.
Results are matched to schedule.yaml events by date + opponent name. Games inside a
multi-day tournament whose opponent we don't list individually (e.g. Delta bracket)
are attached to that tournament event under "games".

A manual `result: "W 70-62"` on a game in schedule.yaml wins over anything scraped
(useful for scrimmages, which the official page never scores).

  python3 scripts/fetch_results.py              # update data/results.json
  python3 scripts/fetch_results.py --url URL    # parse another season's page (dry run, prints)
"""
import datetime as dt
import html
import json
import re
import subprocess
import sys
from urllib.parse import urljoin

from check_feed import fetch_feed, norm, parse_feed
from common import ROOT, load

UA = "Mozilla/5.0 (compatible; cuesta-mbb-schedule; +https://github.com/johnlinwiz/cuesta-mbb)"


def fetch(url, must_contain="event-row"):
    r = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", UA, "-w", "\n%{http_code}", url],
                       capture_output=True, text=True)
    body, _, code = r.stdout.rpartition("\n")
    if r.returncode != 0 or code != "200" or must_contain not in body:
        raise RuntimeError(f"{url} -> HTTP {code or '?'} (curl exit {r.returncode})")
    return body


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_score(raw):
    """'L, 102-78' / 'W, 81-74 (OT)' / 'W 70-62' -> (outcome, us, them). Presto lists the higher score first."""
    m = re.match(r"^\s*([WLT])\s*,?\s*(\d+)\s*-\s*(\d+)", raw or "")
    if not m:
        return None
    o, a, b = m.group(1), int(m.group(2)), int(m.group(3))
    hi, lo = max(a, b), min(a, b)
    us, them = (hi, lo) if o == "W" else (lo, hi) if o == "L" else (a, b)
    return o, us, them


def parse_page(page, base_url):
    rows = []
    for m in re.finditer(r'<div class="event-row([^"]*)"([^>]*)>(.*?)<a href="#" class="venue" title="([^"]*)"', page, re.S):
        classes, attrs, body, venue = m.groups()
        d = re.search(r'<div class="date" title="[A-Za-z]+\.? ([A-Za-z]+) (\d{1,2}), (\d{4})"', body)
        name = re.search(r'<span class="team-name">(.*?)</span>', body, re.S)
        if not (d and name):
            continue
        date = dt.datetime.strptime(f"{d.group(1)} {d.group(2)} {d.group(3)}", "%B %d %Y").date()
        status = text((re.search(r'<div class="status">(.*?)</div>', body, re.S) or [None, ""])[1])
        result = text((re.search(r'<div class="result">(.*?)</div>', body, re.S) or [None, ""])[1])
        links = {}
        for a in re.finditer(r'<a [^>]*href="([^"]+)"[^>]*>.*?<span class="text">(.*?)</span>', body, re.S):
            label = text(a.group(2)).lower()
            key = "boxscore" if "box" in label else "recap" if "recap" in label else None
            if key and key not in links:
                links[key] = urljoin(base_url, a.group(1))
        bs = re.search(r'data-boxscore="([^"]+)"', attrs)
        if bs and "boxscore" not in links:
            links["boxscore"] = urljoin(base_url, bs.group(1))
        rows.append({"date": date, "opponent": text(name.group(1)), "site": venue.lower(),
                     "status": status, "raw": result, "exhibition": "exhibition" in classes, **links})
    return rows


def parse_league_page(page, base_url, season):
    """3C2A team game-log page (…/teams/<team>?view=schedule). Reachable from GitHub runners,
    unlike some college athletics hosts. Columns: date, opponent, result-with-boxscore-link, stats…"""
    y1 = int(season[:4]); rows = []
    for tr in re.finditer(r"<tr>\s*<td class=\"text-nowrap text-start\">(.*?)</td>\s*<td class=\"text-nowrap\">(.*?)</td>\s*"
                          r"<td class=\"text-nowrap text-center\">(.*?)</td>", page, re.S):
        dtxt, opp, res = (text(x) for x in tr.groups())
        m = re.match(r"([A-Za-z]{3}) (\d{1,2})", dtxt)
        if not m:
            continue
        mon = dt.datetime.strptime(m.group(1), "%b").month
        date = dt.date(y1 if mon >= 7 else y1 + 1, mon, int(m.group(2)))
        site = "away" if opp.startswith("at ") else "neutral" if opp.startswith("vs") else "home"
        opp = re.sub(r"^(at|vs\.?)\s+", "", opp).rstrip("*# ").strip()
        link = re.search(r'href="([^"]+boxscores/[^"]+)"', tr.group(3))
        row = {"date": date, "opponent": opp, "site": site, "status": "Final" if parse_score(res) else "",
               "raw": res, "exhibition": "#" in dtxt}
        if link:
            row["boxscore"] = urljoin(base_url, link.group(1))
        rows.append(row)
    # The page repeats the game log in several stat tables; keep the first copy of each game.
    seen, out = set(), []
    for r in rows:
        k = (r["date"], r["opponent"])
        if k not in seen:
            seen.add(k); out.append(r)
    return out


def feed_rows(sched):
    """Final scores from the league iCal feed (same feed check_feed.py uses; reachable from runners)."""
    url = sched["feed_url"]
    host = re.match(r"https?://[^/]+", url).group(0)
    rows = []
    for f in parse_feed(fetch_feed(url)):
        if "us" not in f:
            continue
        us, them = f["us"], f["them"]
        o = "W" if us > them else "L" if us < them else "T"
        row = {"date": f["date"], "opponent": f["opponent"], "site": f["site"], "status": "Final",
               "raw": f"{o}, {max(us, them)}-{min(us, them)}" + (f" ({f['ot']})" if f.get("ot") else ""),
               "forfeit": f.get("forfeit", False)}
        if f.get("boxscore"):
            row["boxscore"] = urljoin(host + "/", f["boxscore"])
        rows.append(row)
    return rows


def get_rows(sched):
    """League iCal feed first; then team-site HTML (adds recap links) or league game log."""
    errors = []
    try:
        rows = feed_rows(sched)
        try:   # best-effort enrichment: recap links only exist on the team site (often blocked in CI)
            html_rows = parse_page(fetch(sched["source_url"]), sched["source_url"])
            extra = {(r["date"], r["opponent"]): r for r in html_rows}
            for r in rows:
                h = extra.get((r["date"], r["opponent"]))
                if h:
                    for k in ("recap", "boxscore"):
                        if h.get(k):
                            r[k] = h[k]
            return rows, "league iCal + team site"
        except Exception as err:
            return rows, f"league iCal (team site unavailable: {err})"
    except Exception as err:
        errors.append(str(err))
    try:
        return parse_page(fetch(sched["source_url"]), sched["source_url"]), "team site"
    except Exception as err:
        errors.append(str(err))
    if sched.get("results_fallback_url"):
        u = sched["results_fallback_url"]
        try:
            return parse_league_page(fetch(u, must_contain="text-nowrap text-start"), u, sched["season"]), "3C2A"
        except Exception as err:
            errors.append(str(err))
    raise RuntimeError("; ".join(errors))


def to_result(row, raw=None):
    raw = raw if raw is not None else row.get("raw", "")
    parsed = parse_score(raw)
    if not parsed:
        return None
    o, us, them = parsed
    out = {"outcome": o, "us": us, "them": them, "score": f"{us}-{them}", "raw": raw,
           "status": row.get("status") or "Final"}
    if row.get("forfeit") or (us + them <= 2 and not row.get("boxscore")):   # Presto records forfeits as 2-0
        out["forfeit"] = True
    # OT is in the score text ("W 81-74 (OT)", "(2OT)") or, on Presto pages, only the status ("Final - OT")
    ot = re.search(r"\b(\d?OT)\b", f"{raw} {row.get('status') or ''}".upper())
    if ot:
        out["ot"] = ot.group(1)
    for k in ("boxscore", "recap"):
        if row.get(k):
            out[k] = row[k]
    return out


def main():
    if "--feed" in sys.argv:   # validate the iCal path against another season's feed
        url = sys.argv[sys.argv.index("--feed") + 1]
        rows = feed_rows({"feed_url": url})
        print(f"{len(rows)} scored games in feed")
        for r in rows:
            o, us, them = parse_score(r["raw"])
            print(f"  {r['date']} {r['site']:7} {r['opponent']:<28} {o} {us}-{them}{'  FORFEIT' if r['forfeit'] else ''}{'  [box]' if r.get('boxscore') else ''}")
        return 0
    if "--url" in sys.argv:
        url = sys.argv[sys.argv.index("--url") + 1]
        if "cccaasports" in url:
            season = re.search(r"/(\d{4}-\d{2})/", url).group(1)
            rows = parse_league_page(fetch(url, "text-nowrap text-start"), url, season)
        else:
            rows = parse_page(fetch(url), url)
        scored = [r for r in rows if parse_score(r["raw"])]
        print(f"{len(rows)} rows, {len(scored)} with scores")
        for r in scored:
            o, us, them = parse_score(r["raw"])
            print(f"  {r['date']} {r['site']:7} {r['opponent']:<28} {o} {us}-{them}  raw='{r['raw']}'"
                  f"{'  [box]' if r.get('boxscore') else ''}{'  [recap]' if r.get('recap') else ''}")
        return 0

    sched, _, _, events = load()
    aliases = {k.lower(): v.lower() for k, v in (sched.get("feed_aliases") or {}).items()}
    out_path = ROOT / "data/results.json"
    prev = json.loads(out_path.read_text()) if out_path.exists() else {}
    try:
        rows, src = get_rows(sched)
        print(f"results source: {src} ({len(rows)} rows)")
    except Exception as err:   # keep yesterday's results rather than wiping them
        print(f"::warning::results fetch skipped: {err}")
        rows = None

    results = {}
    if rows is not None:
        by_key = {(r["date"], norm(r["opponent"], aliases)): r for r in rows}
        # Games tracked as their own single-day event never also count toward a tournament range.
        single = {(e.date, norm(e.opponent, aliases)) for e in events if e.end_date == e.date}
        for e in events:
            if e.end_date > e.date:   # multi-day tournament: collect every scored game in its range
                # (checked first: "Redwoods Tournament" must not grab just the day-1 game vs Redwoods)
                games = []
                for row in rows:
                    if (e.date <= row["date"] <= e.end_date and (row["date"], norm(row["opponent"], aliases)) not in single
                            and (res := to_result(row))):
                        games.append({"date": row["date"].isoformat(), "opponent": row["opponent"], **res})
                if games:
                    results[e.id] = {"games": games}
            elif (r := by_key.get((e.date, norm(e.opponent, aliases)))) and (res := to_result(r)):
                results[e.id] = res
    else:
        results = {k: v for k, v in prev.items() if not v.get("manual")}

    # Manual overrides from schedule.yaml (e.g. scrimmages)
    for e in events:
        if e.raw.get("result"):
            res = to_result({"status": "Final"}, str(e.raw["result"]))
            if res:
                res["manual"] = True
                results[e.id] = res

    out_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"{len(results)} result(s) recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
