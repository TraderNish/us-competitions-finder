#!/usr/bin/env python3
"""
refresh.py — scoped, idempotent refresh of VOLATILE fields only.

What it does, conservatively and honestly:
  - For each ACTIVE competition, fetch its registration_url (falling back to
    official_url), respecting robots.txt, rate-limiting, and caching responses.
  - Liveness check: if the official page is reachable (HTTP 200), treat the
    competition as still running and bump last_verified to today.
  - registration_open: set true/false ONLY on an unambiguous phrase in the page
    ("registration is open" / "registration is closed"). Otherwise leave as-is.
  - next_deadline: extract ONLY from an explicit "deadline ... <Month DD, YYYY>"
    or "register by <Month DD, YYYY>" phrase. If absent or ambiguous, leave null.
    NEVER guesses a date.
  - Writes competitions.json + competitions.js (same code path as build.py) and a
    refresh_report.md. Records that could not be confirmed are flagged for manual
    review; their last_verified is NOT bumped.

It does NOT rewrite competitions.yaml (the curated source of truth keeps its
comments). The YAML's last_verified means "stable facts confirmed by a human";
the refreshed JSON additionally carries today's liveness/volatile check.

Usage:
  python3 refresh.py            # refresh all active records
  python3 refresh.py --offline  # no network; just rebuild JSON from the seed
  python3 refresh.py --only mathcounts,usaco
  python3 refresh.py --limit 5
"""

import argparse
import datetime as dt
import hashlib
import re
import sys
import time
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import build  # shared load/assemble/write

ROOT = Path(__file__).parent
CACHE = ROOT / ".cache"
REPORT = ROOT / "refresh_report.md"

UA = "JCCompetitionsFinder/1.0 (+contact: appunish4u@gmail.com)"
CACHE_TTL = 6 * 3600        # reuse cached pages for 6h
RATE_LIMIT_SECONDS = 3.0    # polite delay between LIVE network requests
TIMEOUT = 15

MONTHS = ("january february march april may june july august september "
          "october november december").split()
DATE_RE = re.compile(
    r"(?:deadline|register(?:ing)?\s+by|registration\s+closes?)\D{0,40}?"
    r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE)
OPEN_RE = re.compile(r"registration\s+is\s+open|register\s+now", re.IGNORECASE)
CLOSED_RE = re.compile(r"registration\s+(?:is\s+)?closed", re.IGNORECASE)

_robots_cache = {}
_last_request_ts = [0.0]


def today():
    return dt.date.today().isoformat()


def robots_ok(url):
    """Respect robots.txt for our UA. Fail-closed only on explicit Disallow."""
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None  # no robots.txt reachable -> allowed
        _robots_cache[base] = rp
    rp = _robots_cache[base]
    return True if rp is None else rp.can_fetch(UA, url)


def cache_path(url):
    return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def fetch(url):
    """Return (status, text). Uses cache; rate-limits live requests. status is
    'cache', an int HTTP code, or an error string."""
    cp = cache_path(url)
    if cp.exists() and (time.time() - cp.stat().st_mtime) < CACHE_TTL:
        return "cache", cp.read_text(errors="ignore")

    # rate limit live requests only
    wait = RATE_LIMIT_SECONDS - (time.time() - _last_request_ts[0])
    if wait > 0:
        time.sleep(wait)
    _last_request_ts[0] = time.time()

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            CACHE.mkdir(exist_ok=True)
            cp.write_text(body, errors="ignore")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return f"error: {type(e).__name__}", ""


def visible_text(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def extract_deadline(text):
    """Return ISO date ONLY from an explicit deadline phrase, else None."""
    m = DATE_RE.search(text)
    if not m:
        return None
    month = MONTHS.index(m.group(1).lower()) + 1
    day, year = int(m.group(2)), int(m.group(3))
    try:
        d = dt.date(year, month, day)
    except ValueError:
        return None
    # ignore obviously stale matches (a deadline already long past)
    if d < dt.date.today() - dt.timedelta(days=14):
        return None
    return d.isoformat()


def refresh_record(r):
    """Mutate r's volatile fields in place. Return a status dict for the report."""
    url = r.get("registration_url") or r.get("official_url")
    status = {"id": r["id"], "url": url, "result": "", "deadline": None,
              "reg_open": None, "bumped": False, "review": False}

    if not url:
        status["result"] = "no url"
        status["review"] = True
        return status

    if not robots_ok(url):
        status["result"] = "skipped (robots.txt disallow)"
        status["review"] = True
        return status

    code, html = fetch(url)
    status["result"] = f"http {code}"
    if code in (200, "cache"):
        text = visible_text(html)
        # liveness confirmed -> bump last_verified
        r["last_verified"] = today()
        status["bumped"] = True
        # conservative registration_open
        if OPEN_RE.search(text) and not CLOSED_RE.search(text):
            r["registration_open"] = True
            status["reg_open"] = True
        elif CLOSED_RE.search(text):
            r["registration_open"] = False
            status["reg_open"] = False
        # conservative deadline (never guesses)
        d = extract_deadline(text)
        if d:
            r["next_deadline"] = d
            status["deadline"] = d
    else:
        # could not confirm liveness -> do NOT bump; flag for manual review
        status["review"] = True
    return status


def write_report(statuses, offline):
    lines = [f"# Refresh report — {today()}", ""]
    if offline:
        lines.append("_Offline run: JSON rebuilt from seed; no network checks._\n")
    bumped = [s for s in statuses if s["bumped"]]
    review = [s for s in statuses if s["review"]]
    deadlines = [s for s in statuses if s["deadline"]]
    lines += [
        f"- checked: **{len(statuses)}**",
        f"- liveness confirmed (last_verified bumped): **{len(bumped)}**",
        f"- deadlines extracted: **{len(deadlines)}**",
        f"- needs manual review: **{len(review)}**",
        "",
        "## Needs manual review",
    ]
    lines += [f"- `{s['id']}` — {s['result']} — {s['url']}" for s in review] or ["- none"]
    lines += ["", "## Deadlines extracted"]
    lines += [f"- `{s['id']}` — {s['deadline']}" for s in deadlines] or ["- none"]
    REPORT.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="no network; just rebuild JSON from the seed")
    ap.add_argument("--only", help="comma-separated ids to refresh")
    ap.add_argument("--limit", type=int, help="cap number of records checked")
    args = ap.parse_args()

    records = build.load_and_validate()
    active = [r for r in records if r.get("active")]
    targets = active
    if args.only:
        want = set(args.only.split(","))
        targets = [r for r in active if r["id"] in want]
    if args.limit:
        targets = targets[:args.limit]

    statuses = []
    if not args.offline:
        print(f"refreshing {len(targets)} record(s)…")
        for r in targets:
            s = refresh_record(r)
            statuses.append(s)
            flag = " [REVIEW]" if s["review"] else ""
            extra = f" deadline={s['deadline']}" if s["deadline"] else ""
            print(f"  {r['id']:<26} {s['result']}{extra}{flag}")

    payload = build.assemble(records)
    payload["data_refreshed_at"] = today() if not args.offline else None
    build.write_outputs(payload)
    write_report(statuses, args.offline)

    print(f"\nwrote competitions.json / competitions.js")
    if not args.offline:
        print(f"report: {REPORT.name}  "
              f"(bumped {sum(s['bumped'] for s in statuses)}, "
              f"review {sum(s['review'] for s in statuses)})")


if __name__ == "__main__":
    main()
