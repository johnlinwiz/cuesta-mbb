"""Paths and readers for the saved 2025-26 source pages (tests/fixtures/2025-26/)."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
SEASON = FIXTURES / "2025-26"
TEAM_URL = "https://www.cuestaathletics.com/sports/mbkb/2025-26/schedule"
LEAGUE_URL = "https://www.cccaasports.org/sports/mbkb/2025-26/teams/cuesta?view=schedule"


def read(name):
    # newline="" keeps the iCal CRLFs exactly as the league serves them
    with open(SEASON / name, encoding="utf-8", newline="") as f:
        return f.read()
