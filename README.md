# Trailhead Tracker

A small local web app for Wipro's 6-week Salesforce training program. It takes
the training calendar (Excel, with modules assigned per day) and a trainee's
**public** Trailhead profile link, and shows which assigned modules they've
actually completed by cross-checking against their earned badges.

```
your-calendar.xlsx  --parse_calendar.py-->  data/calendar.json  --served by-->  FastAPI  --renders in-->  browser UI
                                                                                     ^
                                                              trainee's Trailhead profile link (typed in the UI)
```

## How it actually gets the completion data

Trailhead has no official public API. This app calls the same internal
Aura endpoints that trailblazer.me's own profile page calls in the browser
— the same technique several other community tools (leaderboard bots,
badge widgets) use. `trailhead_client.py` implements this directly (it
originally wrapped the third-party `trailhead-scraper` PyPI package, but
that was vendored in-house — see the changelog note below). It only works
for profiles the trainee has set to **Public** (Trailhead Settings →
Privacy → Public Profile); a private profile will show name/photo only,
and the app will report it can't read badges.

**Read this before you rely on it:** this is not an official, stable API.
Salesforce can change these internal endpoints at any time without notice.
I built and tested the Excel parsing, matching logic, and full UI against
your real spreadsheet, but this was built in a sandbox with no network
access to salesforce.com, so **the live Trailhead lookup can't be tested
from where I build this — only from your machine.**

### If a real profile fails (400 error / "couldn't find profile")

1. Run the bundled diagnostic script, which calls each step individually
   and prints the real HTTP status codes and response bodies:
   ```bash
   python diagnose.py https://www.salesforce.com/trailblazer/<handle>
   ```
2. Whichever step fails will print the actual server response. Common causes:
   - **Response is a login page / redirect** → the profile isn't actually
     set to Public yet (Trailhead's privacy toggle can take a minute to
     apply, or the person toggled the wrong section).
   - **HTTP 403 / a captcha-looking response** → Trailhead is blocking the
     request as automated traffic. Try again after a short wait; if it's
     consistent, this needs a different approach (e.g. a headless-browser
     based scraper instead of raw HTTP) — let me know and I'll build that.
   - **JSON shape errors ("didn't return the expected structure")** →
     Salesforce changed their internal API response format. Paste the
     printed snippet back to me and I'll update the field lookups in
     `trailhead_client.py` to match.
3. The app's own error messages (shown in the UI and in the `uvicorn` log)
   now include the same status-code/snippet detail as `diagnose.py`, so you
   don't strictly need to run it separately — but it's cleaner output for
   sharing.

### Changelog

- **v1** used the `trailhead-scraper` PyPI package directly. It returned
  generic errors on every real profile tested, with no way to see why.
- **v2** (current) vendors that same Aura-call approach directly into
  `trailhead_client.py`, adds browser-like request headers (a plain
  `requests` User-Agent gets treated as a bot by a lot of sites), and wraps
  every HTTP call with status-code + response-snippet reporting so failures
  are diagnosable instead of opaque.

## What's in the box

```
trailhead-tracker/
├── app.py                # FastAPI app: /api/calendar, /api/progress, serves static/
├── parse_calendar.py      # Excel -> data/calendar.json (run once, or whenever the sheet changes)
├── trailhead_client.py    # Talks to Trailhead, normalizes the response
├── matcher.py             # Fuzzy-matches calendar modules against earned badges
├── mock_data.py           # Fixture data for the "demo" button — no network needed
├── data/calendar.json     # Already generated from your uploaded spreadsheet
├── static/                # Plain HTML/CSS/JS frontend, no build step
└── requirements.txt
```

## Setup

Requires Python 3.9+.

```bash
cd trailhead-tracker
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`data/calendar.json` is already generated from the spreadsheet you gave me,
so you can run the app right away. If the training team edits the Excel file
later, regenerate it:

```bash
python parse_calendar.py path/to/updated_calendar.xlsx
```

## Run it

```bash
uvicorn app:app --reload
```

Open **http://127.0.0.1:8000** in your browser. You'll see the full 6-week
calendar (ungraded — just the plan). Click **"Try it with a demo profile
instead"** to see what a checked result looks like without any network
calls. To check a real trainee, paste their public profile link (either
`https://www.salesforce.com/trailblazer/<handle>` or just the handle) and
click **Check progress**.

## Known limitations, on purpose

- **Multi-module cells only carry one link.** A few rows in your spreadsheet
  list several Trailhead module names in one cell but Excel only lets one
  hyperlink attach to the whole cell. `parse_calendar.py` keeps every module
  name (so nothing is silently dropped) and attaches the one available link
  to the first module in that cell; the rest show without a clickable link.
  You can hand-fix `data/calendar.json` for any specific row if you want
  every module individually linked.
- **Matching is name-similarity based, not an exact ID match** (Trailhead
  doesn't expose one via this method), using a similarity threshold. It's
  tuned to catch minor wording differences, but treat anything you're
  unsure about as worth a manual glance — the module's own link is right
  there in the row for that.
- **No database, no auth, no bulk roster upload.** This checks one profile
  at a time by design, matching what you described. If you later want to
  check a whole cohort at once, the natural extension is a small CSV of
  `name,trailhead_handle` fed through the same `/api/progress` logic in a
  loop — say the word if you want that built out.
