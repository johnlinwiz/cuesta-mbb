# Uses the johnlinwiz gh account regardless of which account is active globally.
GH_TOKEN ?= $(shell gh auth token --user johnlinwiz 2>/dev/null)
export GH_TOKEN

.PHONY: build drive issues feed results daily serve all
build:            ## regenerate README, CALENDAR.md, venues.geojson, docs/
	python3 scripts/build.py
drive:            ## recompute drive times (OSRM) after editing venues
	python3 scripts/drive_times.py
issues:           ## create/update one reminder issue per game, then rebuild links
	python3 scripts/sync_issues.py && python3 scripts/build.py
feed:             ## compare the official 3C2A feed with schedule.yaml (prints diffs)
	python3 scripts/check_feed.py
results:          ## scrape final scores into data/results.json, then rebuild
	python3 scripts/fetch_results.py && python3 scripts/build.py
daily:            ## run the reminder/close job locally
	python3 scripts/daily.py
serve:            ## preview the Pages calendar at http://localhost:8000
	cd docs && python3 -m http.server 8000
all: drive issues
