#!/usr/bin/env python3
"""
build.py — deterministic, OFFLINE converter: competitions.yaml -> competitions.json

The frontend reads competitions.json (with competitions.js as a file:// fallback).
This script never touches the network; it validates the seed and serializes it.

refresh.py imports load_and_validate / assemble / write_outputs from here so the
two tools share exactly one code path.

Run:  python3 build.py
"""

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
SEED = ROOT / "competitions.yaml"
OUT_JSON = ROOT / "competitions.json"
OUT_JS = ROOT / "competitions.js"

REQUIRED = [
    "id", "name", "subjects", "grades", "format", "level", "access",
    "team_or_individual", "cost", "typical_window", "next_deadline",
    "registration_open", "official_url", "registration_url", "source_notes",
    "last_verified", "active",
]
VALID_FORMAT = {"in-person", "online", "hybrid"}
VALID_LEVEL = {"national", "regional", "state", "local"}


def norm_date(v):
    """YAML may parse dates as date objects; emit ISO strings (or None)."""
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    return str(v)


def validate(records):
    errors, ids = [], set()
    for i, r in enumerate(records):
        tag = r.get("id", f"<index {i}>")
        for f in REQUIRED:
            if f not in r:
                errors.append(f"{tag}: missing required field '{f}'")
        if r.get("id") in ids:
            errors.append(f"{tag}: duplicate id")
        ids.add(r.get("id"))
        if r.get("format") not in VALID_FORMAT:
            errors.append(f"{tag}: bad format '{r.get('format')}'")
        if r.get("level") not in VALID_LEVEL:
            errors.append(f"{tag}: bad level '{r.get('level')}'")
        if not isinstance(r.get("grades"), list) or not r.get("grades"):
            errors.append(f"{tag}: grades must be a non-empty list")
        if not isinstance(r.get("subjects"), list) or not r.get("subjects"):
            errors.append(f"{tag}: subjects must be a non-empty list")
        if r.get("active") is False and not r.get("discontinued_note"):
            errors.append(f"{tag}: active:false requires a discontinued_note")
    return errors


def load_and_validate():
    """Parse the seed, validate it, normalize dates. Exits on validation error."""
    data = yaml.safe_load(SEED.read_text())
    records = data.get("competitions", [])
    errors = validate(records)
    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        sys.exit(1)
    for r in records:
        r["last_verified"] = norm_date(r.get("last_verified"))
        r["next_deadline"] = norm_date(r.get("next_deadline"))
    return records


def assemble(records):
    """Build the JSON payload (facets + counts) the frontend consumes."""
    active = [r for r in records if r.get("active")]
    subjects = sorted({s for r in active for s in r["subjects"]})
    grades = sorted({g for r in active for g in r["grades"]})
    return {
        "generated_at": max(
            [r["last_verified"] for r in records if r["last_verified"]],
            default=None),
        "facets": {
            "subjects": subjects,
            "grades": grades,
            "formats": sorted({r["format"] for r in active}),
            "levels": sorted({r["level"] for r in active}),
        },
        "count_active": len(active),
        "count_total": len(records),
        "competitions": records,
    }


def write_outputs(payload):
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    # Fallback so index.html also opens directly from file:// (no server needed).
    OUT_JS.write_text(
        "window.__DATA__ = " + json.dumps(payload, separators=(",", ":")) + ";")


def main():
    records = load_and_validate()
    payload = assemble(records)
    write_outputs(payload)
    active = payload["count_active"]
    print(f"wrote {OUT_JSON.name}: {active} active / {payload['count_total']} total records")
    print(f"subjects: {', '.join(payload['facets']['subjects'])}")
    g = payload["facets"]["grades"]
    print(f"grades:   {min(g)}-{max(g)}")
    verified = sum(1 for r in records if r.get("active") and r["last_verified"])
    print(f"verified (last_verified set): {verified}/{active} active")


if __name__ == "__main__":
    main()
