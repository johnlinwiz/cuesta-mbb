#!/usr/bin/env python3
"""Compute road distance + drive time from each origin to each venue via OSRM.

Writes data/drive_times.json. OSRM times are free-flow (no traffic) and run a bit
conservative versus Google; the generated docs also link Google Maps directions
for live traffic estimates.
"""
import json
import pathlib
import subprocess
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OSRM = "https://router.project-osrm.org/route/v1/driving/{a};{b}?overview=false"


def route(o, v):
    url = OSRM.format(a=f"{o['lon']},{o['lat']}", b=f"{v['lon']},{v['lat']}")
    # curl rather than urllib: macOS system Python's old SSL can't handshake with OSRM.
    raw = subprocess.run(["curl", "-sf", "--max-time", "30", "-A", "cuesta-mbb-schedule", url],
                         check=True, capture_output=True, text=True).stdout
    data = json.loads(raw)
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error for {url}: {data}")
    leg = data["routes"][0]
    return {"miles": round(leg["distance"] / 1609.344), "minutes": round(leg["duration"] / 60)}


def main():
    cfg = yaml.safe_load((ROOT / "data/venues.yaml").read_text())
    out = {}
    for key, v in cfg["venues"].items():
        out[key] = {}
        for okey, o in cfg["origins"].items():
            out[key][okey] = route(o, v)
            time.sleep(1)  # be polite to the public demo server
        print(key, out[key])
    (ROOT / "data/drive_times.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
