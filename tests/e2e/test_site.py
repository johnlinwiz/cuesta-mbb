"""docs/index.html in a real (headless Chromium) browser, against faked network services."""
import hashlib
import base64
import json
import re

import pytest
from playwright.sync_api import expect

from conftest import CDN, REPO, VENDOR
from pagetools import fmt_dur, horizontal_overflow, pinch, text_size

VIEWS = {"table": "#view-tbl", "cal": "#view-cal", "map": "#view-map"}
BUTTONS = {"table": "#m-tbl", "cal": "#m-cal", "map": "#m-map"}


def shown_views(page):
    return [m for m, sel in VIEWS.items()
            if page.eval_on_selector(sel, "el => getComputedStyle(el).display !== 'none' && el.getClientRects().length > 0")]


# ---------------------------------------------------------------- views
@pytest.mark.parametrize("mobile", [True, False], ids=["phone", "desktop"])
def test_each_view_shows_alone(make_page, mobile):
    page, _ = make_page(mobile=mobile)
    assert shown_views(page) == ["table"]
    for mode in ("map", "cal", "table", "map"):
        page.click(BUTTONS[mode])
        assert shown_views(page) == [mode], f"after clicking {mode}"
        assert page.eval_on_selector(BUTTONS[mode], "b => b.classList.contains('on')")
    # the old bug: #view-map's display:grid beat [hidden], so the map sat under the other views
    page.click(BUTTONS["table"])
    assert page.eval_on_selector("#view-map", "el => el.hidden && getComputedStyle(el).display") == "none"


@pytest.mark.parametrize("hash, mode", [("#map", "map"), ("#calendar", "cal"), ("#cal", "cal"), ("", "table")])
def test_url_hash_picks_the_view(make_page, hash, mode):
    page, _ = make_page(mobile=False, hash=hash)
    assert shown_views(page) == [mode]
    if mode == "map":
        expect(page.locator("#map .leaflet-interactive").first).to_be_attached()
    if mode == "cal":
        expect(page.locator("#cal .fc-event").first).to_be_visible()


# ---------------------------------------------------------------- phone layout
@pytest.mark.parametrize("size", [None, "130"], ids=["text-100", "text-130"])
@pytest.mark.parametrize("mode", ["table", "cal", "map"])
def test_nothing_scrolls_sideways_at_390px(make_page, mode, size):
    page, _ = make_page(mobile=True, text_size=size)
    assert text_size(page)[0] == ("130%" if size else "")
    page.click(BUTTONS[mode])
    page.wait_for_timeout(100)
    assert horizontal_overflow(page) == []
    page.click("#presets button[data-key=pasadena]")          # drive columns get longer once an origin is set
    expect(page.locator("#from-status")).to_have_text("From Pasadena")
    page.wait_for_timeout(100)
    assert horizontal_overflow(page) == []


def test_details_dialog_fits_on_a_phone(make_page):
    page, _ = make_page(mobile=True, text_size="130")
    page.click("#tbl-b button.link >> nth=2")
    expect(page.locator("#dlg")).to_be_visible()
    box = page.locator("#dlg").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390


# ---------------------------------------------------------------- text size
def test_text_size_buttons(make_page):
    page, _ = make_page(mobile=True)
    assert text_size(page) == ["", None]
    page.click("#ts-up")
    assert text_size(page) == ["115%", "115"]
    expect(page.locator("#ts-badge")).to_have_text("Text 115%")
    page.click("#ts-up")
    assert text_size(page) == ["130%", "130"]
    expect(page.locator("#ts-up")).to_be_disabled()
    for _ in range(3):                                      # 130 -> 115 -> 100 -> 90
        page.click("#ts-down")
    assert text_size(page) == ["90%", "90"]
    expect(page.locator("#ts-down")).to_be_disabled()
    page.click("#ts-up")
    assert text_size(page) == ["", "100"]                   # 100% clears the inline style


def test_text_size_survives_reload(make_page):
    page, _ = make_page(mobile=True)
    page.click("#ts-up")
    page.reload()
    page.wait_for_selector("#tbl-b tr")
    assert text_size(page) == ["115%", "115"]
    expect(page.locator("#ts-up")).to_be_enabled()
    page.evaluate("localStorage.setItem('cuesta-mbb-textsize', 'xl')")    # value saved by an older version
    page.reload()
    page.wait_for_selector("#tbl-b tr")
    assert text_size(page)[0] == "130%"
    page.evaluate("localStorage.setItem('cuesta-mbb-textsize', 'garbage')")
    page.reload()
    page.wait_for_selector("#tbl-b tr")
    assert text_size(page)[0] == ""


def test_pinch_resizes_text_and_saves_where_fingers_stop(make_page):
    page, _ = make_page(mobile=True)
    # 200px -> 230px (115%), let it paint, then 260px (130%) and lift before the next frame.
    pinch(page, "#tbl-b", [200, 230, 260], frame_gaps=[0, 2, 0])
    assert text_size(page) == ["130%", "130"]             # not 115: the end of the pinch wins
    expect(page.locator("#ts-badge")).to_have_text("Text 130%")
    page.reload()
    page.wait_for_selector("#tbl-b tr")
    assert text_size(page) == ["130%", "130"]


def test_pinch_in_and_clamping(make_page):
    page, _ = make_page(mobile=True)
    pinch(page, "#next", [300, 240])                      # fingers together -> smaller
    assert text_size(page) == ["80%", "80"]
    pinch(page, "#next", [100, 400])                      # way out -> clamped at 160%
    assert text_size(page) == ["160%", "160"]
    page.click("#ts-down")                                # buttons step from wherever the pinch left it
    assert text_size(page) == ["130%", "130"]


def test_pinch_on_map_leaves_text_alone(make_page):
    page, _ = make_page(mobile=True, hash="#map")
    expect(page.locator("#map .leaflet-interactive").first).to_be_attached()
    pinch(page, "#map", [100, 250])
    assert text_size(page) == ["", None]
    pinch(page, "#map-side", [100, 130])                 # the venue list beside it is fair game
    assert text_size(page) == ["130%", "130"]


# ---------------------------------------------------------------- drive from
def test_drive_from_typed_address(make_page, events_json):
    page, net = make_page(mobile=False)
    page.fill("#i-addr", "Fresno, CA")
    page.press("#i-addr", "Enter")
    label = "Fresno, Fresno County"
    expect(page.locator("#from-status")).to_have_text(f"From {label}")
    assert any("nominatim.openstreetmap.org/search" in u and "Fresno" in u for u in net.requests)

    nxt = next(e for e in events_json["events"] if e["start"] >= "2026-11-05T12")
    assert nxt["id"] == "2026-11-07-diablo-valley"
    mins, miles = net.drive(nxt["extendedProps"]["venueKey"])

    # table: header + the next game's row
    expect(page.locator("#tbl-th-drive")).to_have_text(f"🚗 From {label}")
    row = page.locator("#tbl-b tr", has=page.locator(f"button[data-id='{nxt['id']}']"))
    expect(row.locator("td[data-label=Drive]")).to_have_text(f"{fmt_dur(mins)} · {miles} mi")
    # next-up line
    expect(page.locator("#next")).to_contain_text(f"From {label}: {fmt_dur(mins)} · {miles} mi")
    expect(page.locator("#next")).to_contain_text("leave by")
    saved = json.loads(page.evaluate("localStorage.getItem('cuesta-mbb-origin')"))
    assert (saved["label"], saved["lat"], saved["lon"]) == (label, 36.7378, -119.7871)

    # map: side list, origin marker, and a drawn route
    page.click("#m-map")
    venue = page.locator(f"#map-list .v[data-key={nxt['extendedProps']['venueKey']}]")
    expect(venue).to_contain_text(f"{fmt_dur(mins)} · {miles} mi")
    n_markers = len(events_json["venues"]) + 1
    expect(page.locator("#map path.leaflet-interactive")).to_have_count(n_markers)
    venue.click()
    page.click(".leaflet-popup button[data-route=me]")
    expect(page.locator("#route-info")).to_contain_text(f"{label} →")
    expect(page.locator("#route-info")).to_contain_text("1h 30m · 100 mi")

    # calendar view gets the upcoming-trips table
    page.click("#m-cal")
    expect(page.locator("#trips-h")).to_have_text(f"Upcoming games — drive from {label}")

    # remembered on reload, then cleared
    page.click("#m-tbl")
    page.reload()
    expect(page.locator("#from-status")).to_have_text(f"From {label}")
    page.click("#b-clear")
    expect(page.locator("#tbl-th-drive")).to_have_text("🚗 Pasadena · SLO")
    assert page.evaluate("localStorage.getItem('cuesta-mbb-origin')") is None


def test_drive_from_unknown_address(make_page):
    page, _ = make_page(mobile=True)
    page.fill("#i-addr", "Atlantis")
    page.press("#i-addr", "Enter")
    expect(page.locator("#from-status")).to_have_text("Couldn't find “Atlantis”.")
    expect(page.locator("#b-clear")).to_be_hidden()


# ---------------------------------------------------------------- results
def test_results_badges_and_record(make_page):
    page, _ = make_page(mobile=False)
    expect(page.locator("#next")).to_contain_text("Record: 2-1")      # the scrimmage isn't scored
    expect(page.locator("#next")).to_contain_text("Next up: Sat Nov 7 · 3:00 PM · vs Diablo Valley")
    badges = page.locator("#tbl-b .res")
    expect(badges).to_have_text(["L 68-75", "W 81-74 (OT)", "W (forfeit)"])
    expect(page.locator("#tbl-b .res.W")).to_have_count(2)
    expect(page.locator("#tbl-b .res.L")).to_have_count(1)
    gavilan = page.locator("#tbl-b tr", has=page.locator("button[data-id='2026-10-29-gavilan']"))
    expect(gavilan).to_have_class("past")
    expect(gavilan.locator("td[data-label=Watch] a")).to_have_text(["box"])


def test_details_dialog_shows_result(make_page):
    page, _ = make_page(mobile=False)
    page.click("button[data-id='2026-10-31-sequoias']")
    dlg = page.locator("#dlg")
    expect(dlg).to_be_visible()
    expect(page.locator("#d-title")).to_have_text("Cuesta vs Sequoias")
    expect(page.locator("#d-body .res.W")).to_have_text("W 81-74 (OT)")
    expect(page.locator("#d-body .res-links a")).to_have_text(["box", "recap"])
    expect(page.locator("#d-body a", has_text="recap")).to_have_attribute("href", "https://example.test/recap/sequoias")
    expect(page.locator("#d-foot a", has_text="Reminder issue")).to_have_attribute(
        "href", re.compile(r"github\.com/johnlinwiz/cuesta-mbb/issues/\d+"))
    page.click("#d-foot button")
    expect(dlg).to_be_hidden()


def test_calendar_titles_carry_results(make_page):
    page, _ = make_page(mobile=False, hash="#calendar")
    page.click("#cal .fc-prev-button")                                      # opens on November; go to October
    expect(page.locator("#cal .fc-event", has_text="W 81-74 (OT)")).to_be_visible()


# ---------------------------------------------------------------- the vendored copies stay honest
@pytest.mark.parametrize("url", list(CDN))
def test_vendored_cdn_files_match_page_integrity(url):
    html = (REPO / "docs/index.html").read_text()
    m = re.search(rf'(?:src|href)="{re.escape(url)}" integrity="(sha384-[^"]+)"', html)
    assert m, f"{url} no longer referenced by docs/index.html; update tests/e2e/conftest.py CDN + vendor/"
    digest = "sha384-" + base64.b64encode(hashlib.sha384((VENDOR / CDN[url][0]).read_bytes()).digest()).decode()
    assert digest == m.group(1), f"re-download {url} into tests/e2e/vendor/"
