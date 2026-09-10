"""
Fuzzy-matches the module names pulled from the training calendar against the
badge titles earned on a trainee's public Trailhead profile.

We match on name similarity rather than exact string equality because the
calendar's module names and Trailhead's own badge titles don't always agree
character-for-character (e.g. calendar says "Apex Basics & Database", a
badge might be titled slightly differently, extra whitespace, etc). Uses
only the standard library (difflib) to avoid an extra dependency.
"""

import difflib
import re

MATCH_THRESHOLD = 0.82


def _normalize(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a, b):
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _best_match(module_name, awards):
    best_score = 0.0
    best_award = None
    for award in awards:
        title = award.get("title")
        if not title:
            continue
        score = _similarity(module_name, title)
        if score > best_score:
            best_score = score
            best_award = award
    return best_score, best_award


def match_calendar_to_awards(calendar, awards, threshold=MATCH_THRESHOLD):
    phases_out = []
    overall_done = 0
    overall_total = 0

    for phase in calendar["phases"]:
        rows_out = []
        phase_done = 0
        phase_total = 0

        for row in phase["rows"]:
            modules_out = []
            for module in row["modules"]:
                phase_total += 1
                overall_total += 1

                score, award = _best_match(module["name"], awards)
                completed = score >= threshold

                if completed:
                    phase_done += 1
                    overall_done += 1

                modules_out.append({
                    "name": module["name"],
                    "url": module["url"],
                    "completed": completed,
                    "matched_award_title": award["title"] if (completed and award) else None,
                    "completed_date": award.get("completed_date") if (completed and award) else None,
                    "match_score": round(score, 2),
                })

            rows_out.append({
                "date": row["date"],
                "day": row["day"],
                "topic": row["topic"],
                "subtopics": row["subtopics"],
                "hours": row["hours"],
                "reference_link": row["reference_link"],
                "modules": modules_out,
            })

        phases_out.append({
            "id": phase["id"],
            "title": phase["title"],
            "covers": phase["covers"],
            "rows": rows_out,
            "progress": {
                "done": phase_done,
                "total": phase_total,
                "pct": round(100 * phase_done / phase_total, 1) if phase_total else 0,
            },
        })

    return {
        "phases": phases_out,
        "overall": {
            "done": overall_done,
            "total": overall_total,
            "pct": round(100 * overall_done / overall_total, 1) if overall_total else 0,
        },
    }
