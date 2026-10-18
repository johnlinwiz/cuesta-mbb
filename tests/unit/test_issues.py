"""Issue sync: one issue per game, superseded issues closed and linked to their replacements.

gh.api (the thin `gh api` wrapper) is replaced by an in-memory fake GitHub, so nothing leaves the machine.
"""
import json
import re

import pytest
import yaml

import common
import gh
import sync_issues


class FakeGitHub:
    def __init__(self):
        self.issues, self.comments, self.labels, self.milestones, self.calls = {}, {}, [], [], []
        self.next_number = 100

    def add_issue(self, number, body, state="open", title="old", pull_request=False):
        iss = {"number": number, "title": title, "body": body, "state": state}
        if pull_request:
            iss["pull_request"] = {"url": "x"}
        self.issues[number] = iss
        return iss

    def api(self, path, method="GET", fields=None, paginate=False):
        self.calls.append((method, path, fields))
        path = path.split("?")[0]
        if path == "labels":
            if method == "POST":
                self.labels.append(fields); return fields
            return list(self.labels)
        if path == "milestones":
            if method == "POST":
                ms = {**fields, "number": len(self.milestones) + 1}; self.milestones.append(ms); return ms
            return list(self.milestones)
        if path == "issues":
            if method == "POST":
                self.next_number += 1
                return self.add_issue(self.next_number, fields["body"], title=fields["title"]) | fields
            return list(self.issues.values())
        m = re.fullmatch(r"issues/(\d+)(/comments)?", path)
        n = int(m.group(1))
        if m.group(2):
            if method == "POST":
                self.comments.setdefault(n, []).append(fields["body"]); return {}
            return [{"body": b} for b in self.comments.get(n, [])]
        if method == "PATCH":
            self.issues[n].update(fields); return self.issues[n]
        return self.issues[n]


@pytest.fixture
def fake_gh(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(gh, "api", fake.api)
    return fake


GAMES = [
    {"date": "2026-10-17", "time": "14:00", "opponent": "Reedley", "site": "away", "venue": "away", "type": "scrimmage",
     "replaces": ["2026-10-16-porterville"]},
    {"date": "2026-11-13", "time": "18:00", "opponent": "Feather River", "site": "neutral", "venue": "neutral",
     "type": "tournament", "replaces": ["2026-11-13-american-river-college-tournament-arc"]},
    {"date": "2026-11-14", "time": "13:00", "opponent": "Shasta", "site": "neutral", "venue": "neutral",
     "type": "tournament", "replaces": ["2026-11-13-american-river-college-tournament-arc"]},
    {"date": "2027-01-09", "time": "15:00", "opponent": "Santa Barbara", "site": "home", "venue": "cuesta",
     "type": "conference", "site_confirmed": False},
]


@pytest.fixture
def schedule(season_root):
    p = season_root / "data/schedule.yaml"
    sched = yaml.safe_load(p.read_text())
    sched["games"] = GAMES
    p.write_text(yaml.safe_dump(sched, sort_keys=False))
    return common.load()


def marker(eid):
    return f"body\n<!-- event-id: {eid} -->"


def test_superseded_issue_is_linked_to_its_replacement_and_closed(fake_gh, schedule):
    sched, _, _, events = schedule
    fake_gh.add_issue(1, marker("2026-10-16-porterville"))
    sync_issues.close_superseded(sched, events, {"2026-10-16-porterville": 1}, {"2026-10-17-reedley": 28})
    (comment,) = fake_gh.comments[1]
    assert "@johnlinwiz" in comment and "**Schedule change**" in comment
    assert "#28 (Sat Oct 17 · 2:00 PM · @ Reedley · (scrimmage))" in comment
    assert fake_gh.issues[1]["state"] == "closed" and fake_gh.issues[1]["state_reason"] == "not_planned"


def test_one_issue_replaced_by_two_games_links_both(fake_gh, schedule):
    sched, _, _, events = schedule
    old = "2026-11-13-american-river-college-tournament-arc"
    fake_gh.add_issue(8, marker(old))
    sync_issues.close_superseded(sched, events, {old: 8},
                                 {"2026-11-13-feather-river": 29, "2026-11-14-shasta": 30})
    (comment,) = fake_gh.comments[8]
    assert "#29 (Fri Nov 13 · 6:00 PM · vs Feather River)" in comment
    assert "#30 (Sat Nov 14 · 1:00 PM · vs Shasta)" in comment


def test_removed_game_without_replacement_is_closed_as_cancelled(fake_gh, schedule):
    sched, _, _, events = schedule
    fake_gh.add_issue(5, marker("2026-11-03-monterey-peninsula"))
    sync_issues.close_superseded(sched, events, {"2026-11-03-monterey-peninsula": 5}, {})
    (comment,) = fake_gh.comments[5]
    assert "Removed from the official schedule" in comment and "@johnlinwiz" in comment
    assert fake_gh.issues[5]["state"] == "closed"


def test_already_closed_and_current_issues_are_left_alone(fake_gh, schedule):
    sched, _, _, events = schedule
    fake_gh.add_issue(1, marker("2026-10-16-porterville"), state="closed")
    fake_gh.add_issue(28, marker("2026-10-17-reedley"))
    sync_issues.close_superseded(sched, events, {"2026-10-16-porterville": 1, "2026-10-17-reedley": 28},
                                 {"2026-10-17-reedley": 28})
    assert fake_gh.comments == {}
    assert fake_gh.issues[28]["state"] == "open"
    assert not [c for c in fake_gh.calls if c[0] in ("POST", "PATCH")]


def test_full_sync_creates_updates_and_closes(fake_gh, schedule, season_root):
    fake_gh.add_issue(1, marker("2026-10-16-porterville"))             # superseded by Reedley
    fake_gh.add_issue(4, marker("2027-01-09-santa-barbara"), title="stale title")
    fake_gh.add_issue(50, marker("2026-11-14-shasta"), pull_request=True)   # PRs are never treated as issues
    sync_issues.main()

    issue_map = json.loads((season_root / "data/issues.json").read_text())
    assert set(issue_map) == {e["date"] + "-" + common.slug(e["opponent"]) for e in GAMES}
    assert issue_map["2027-01-09-santa-barbara"] == 4                     # updated in place, not duplicated
    assert fake_gh.issues[4]["title"] == "Sat Jan 9 · 3:00 PM · vs Santa Barbara*"
    assert issue_map["2026-11-14-shasta"] != 50
    created = [c for c in fake_gh.calls if c[:2] == ("POST", "issues")]
    assert len(created) == 3
    assert fake_gh.issues[1]["state"] == "closed"
    assert f"#{issue_map['2026-10-17-reedley']} (" in fake_gh.comments[1][0]
    assert {l["name"] for l in fake_gh.labels} == set(sync_issues.LABELS)
    assert [m["title"] for m in fake_gh.milestones] == ["October 2026", "November 2026", "January 2027"]
    sb = fake_gh.issues[4]
    assert set(sb["labels"]) == {"home", "conference", "site-unconfirmed"}
    assert sb["milestone"] == 3


def test_sync_is_idempotent(fake_gh, schedule):
    sync_issues.main()
    before = dict(fake_gh.issues)
    fake_gh.calls.clear()
    sync_issues.main()
    assert fake_gh.issues.keys() == before.keys()
    assert not [c for c in fake_gh.calls if c[0] == "POST"]               # nothing new created


def test_issue_body(schedule):
    sched, _, _, events = schedule
    sb = next(e for e in events if e.opponent == "Santa Barbara")
    body = sync_issues.body_for(sb, sched)
    assert body.rstrip().endswith("<!-- event-id: 2027-01-09-santa-barbara -->")
    assert "Home/away is inferred" in body
    assert "| **When** | Sat Jan 9, 2027 · **3:00 PM PT** |" in body
    assert "7 days, 2 days before and on game day" in body
    assert sync_issues.labels_for(next(e for e in events if e.opponent == "Shasta")) == ["tournament"]
