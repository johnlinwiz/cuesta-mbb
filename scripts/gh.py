"""Thin wrapper over the `gh` CLI (uses GH_TOKEN / GITHUB_TOKEN from the environment)."""
import json
import subprocess

from common import REPO


def api(path, method="GET", fields=None, paginate=False):
    # paginate kept for call-site readability; every list here fits in one per_page=100 page.
    cmd = ["gh", "api", "-X", method, "-H", "Accept: application/vnd.github+json"]
    cmd.append(path if path.startswith("/") else f"/repos/{REPO}/{path}")
    payload = None
    if fields is not None:
        cmd += ["--input", "-"]
        payload = json.dumps(fields)
    r = subprocess.run(cmd, input=payload, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {method} {path} failed: {r.stderr.strip() or r.stdout.strip()}")
    out = r.stdout.strip()
    if not out:
        return None
    return json.loads(out)
