# US Academic Competitions Finder

A simple, fast, static web app that lets a US parent or student filter
academic competitions (math, science, history, geography, spelling, writing,
debate, language, CS) by **subject, grade, format, cost, and upcoming deadline**,
with a direct link to each competition's official registration page.

## The core design rule

This is **not** a mass-scrape of the internet. It is:

1. **A curated seed dataset — `competitions.yaml`** — the stable facts about each
   competition, maintained as version-controlled data. This is the source of truth.
2. **A scoped refresh script — `refresh.py`** — re-checks only the volatile fields
   (liveness, registration open/closed, next deadline) and stamps `last_verified`.

Why: a finder is only useful if its deadlines are current, and bespoke scrapers
across 30+ different sites break constantly and silently. A curated seed + a
targeted, honest refresh is robust, debuggable, and clear about what's verified
vs. stale. **Dead competitions are never listed as active** — e.g. the National
Geographic GeoBee (discontinued 2021) is kept as `active: false` with a
`discontinued_note`, and the live IAC National Geography Bee is listed instead.

## Files

| File | Role |
|------|------|
| `competitions.yaml` | **Source of truth.** Hand-curated seed. Edit this. |
| `build.py`          | Offline: validates the seed → `competitions.json` (+ `.js` fallback). No network. |
| `refresh.py`        | Scoped refresh of volatile fields; respects robots.txt, rate-limits, caches; writes a report. |
| `index.html`        | The finder UI (plain HTML + JS). Reads `competitions.json`. |
| `competitions.json` | Generated data the UI consumes. |
| `competitions.js`   | Generated `window.__DATA__` fallback so the page also opens from `file://`. |
| `smoke.mjs`         | jsdom test of rendering + every filter. |

## Run it

```bash
pip install pyyaml
python3 build.py                 # seed -> competitions.json
open index.html                  # works directly (uses competitions.js fallback)
# or serve:  python3 -m http.server  then visit http://localhost:8000
```

### Refresh the volatile fields

```bash
python3 refresh.py               # check all active records (network)
python3 refresh.py --offline     # no network; just rebuild JSON from the seed
python3 refresh.py --only mathcounts,usaco
python3 refresh.py --limit 5
```

`refresh.py` is conservative by design:

- **Liveness:** if a competition's official page returns HTTP 200, it's treated as
  still running and `last_verified` is bumped. If it can't be confirmed (robots.txt
  disallow, 404, error), `last_verified` is **not** bumped and the record is flagged
  in `refresh_report.md` for manual review.
- **`registration_open`** is set only on an unambiguous on-page phrase.
- **`next_deadline`** is extracted **only** from an explicit "deadline … Month DD,
  YYYY" phrase. If absent or ambiguous, it stays `null`. **It never guesses a date.**

It does not rewrite `competitions.yaml` (so the curated comments survive). The YAML's
`last_verified` means "a human confirmed the stable facts"; the refreshed JSON also
carries today's automated liveness/volatile check.

## Run the smoke test

```bash
npm install      # jsdom
node smoke.mjs
```

## Data model

Each competition is one record:

```yaml
- id: mathcounts
  name: MATHCOUNTS Competition Series
  subjects: [math]
  grades: [6, 7, 8]            # explicit list -> exact grade filtering
  format: in-person            # in-person | online | hybrid
  level: national              # national | regional | state | local
  access:
    has_local_chapter: true    # is there a local/regional pathway to enter?
    online_option: false
    notes: "local chapter & state rounds (varies by chapter)"
  team_or_individual: both
  cost: "varies; usually school-paid registration"
  typical_window: "school round fall; chapter Feb; state Mar; national May"
  next_deadline: null          # refreshed; null if unknown (never invented)
  registration_open: null      # true | false | null (unknown)
  official_url: https://www.mathcounts.org/
  registration_url: https://www.mathcounts.org/programs/mathcounts-competition-series
  source_notes: "Register through school; verify each year."
  last_verified: 2026-06-17
  active: true                 # set false + discontinued_note instead of deleting
```

## Hard guardrails (non-negotiable)

- **No minors' personal data, ever.** This app lists competitions — never individual
  students, names, schools-of-record, or results tied to a child. There is no
  "winners"/"achievers" feature, by design.
- **No login, no user-data collection** in v1.
- Any future "recognize individual achievers" idea is a **separate** system whose
  data must come from district/school opt-in nomination — never from scraping.

## Data provenance

Seed verified against official organization sites during a 2026-06-17 pass. Entries
whose stable facts were confirmed carry a `last_verified` date; entries still showing
"unverified" in the UI should be confirmed before being relied on. Each card links to
the competition's official site — always the authority over any date or rule here.

Spot a wrong or expired listing? Use the "Report a listing" link in the app footer.
