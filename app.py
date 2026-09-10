"""
Trailhead Tracker -- FastAPI backend.

Serves:
  GET  /api/calendar               -> the raw assigned training calendar
  GET  /api/progress?profile=...   -> calendar cross-checked against a
                                       trainee's public Trailhead badges
  /                                 -> the static frontend (static/)

Run with:  uvicorn app:app --reload
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from matcher import match_calendar_to_awards
from trailhead_client import TrailheadError, get_progress_data

BASE_DIR = Path(__file__).resolve().parent
CALENDAR_PATH = BASE_DIR / "data" / "calendar.json"

app = FastAPI(title="Trailhead Tracker")


def _load_calendar():
    if not CALENDAR_PATH.exists():
        raise RuntimeError(
            f"{CALENDAR_PATH} not found. Run `python parse_calendar.py "
            "<your_calendar.xlsx>` first to generate it."
        )
    return json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))


CALENDAR = _load_calendar()


@app.get("/api/calendar")
def get_calendar():
    return CALENDAR


@app.get("/api/progress")
def get_progress(
    profile: str = Query(..., description="Trailhead public profile URL or handle"),
    mock: bool = Query(False, description="Use bundled demo data instead of a live lookup"),
):
    if mock:
        from mock_data import MOCK_AWARDS, MOCK_PROFILE, MOCK_RANK
        awards, profile_info, rank_info = MOCK_AWARDS, MOCK_PROFILE, MOCK_RANK
    else:
        try:
            awards, profile_info, rank_info = get_progress_data(profile)
        except TrailheadError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    result = match_calendar_to_awards(CALENDAR, awards)
    result["profile"] = profile_info
    result["rank"] = rank_info
    return result


@app.get("/api/health")
def health():
    return {"status": "ok", "phases_loaded": len(CALENDAR.get("phases", []))}


# Static frontend -- keep this mounted last so it doesn't shadow /api/*.
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")
