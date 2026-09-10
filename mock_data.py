"""
Fixture data so you can click around the UI and see what a real result looks
like without needing a live Trailhead profile or an internet connection.
Hit the app with ?mock=1 (the "Try a demo profile" button in the UI does
this) to use this instead of a real network call.

The titles below intentionally match some, not all, of the real module
names in the training calendar, so the demo shows a realistic mix of done /
not-done rows rather than either extreme.
"""

MOCK_AWARDS = [
    {"title": "Company-Wide Org Settings", "completed_date": "2026-05-11", "type": "Module"},
    {"title": "User Management", "completed_date": "2026-05-12", "type": "Module"},
    {"title": "Data Security", "completed_date": "2026-05-13", "type": "Module"},
    {"title": "Data Modeling", "completed_date": "2026-05-14", "type": "Module"},
    {"title": "Apex Basics & Database", "completed_date": "2026-05-25", "type": "Module"},
    {"title": "JavaScript Skills for Salesforce Developers", "completed_date": "2026-06-08", "type": "Module"},
    {"title": "Coding for Web Accessibility", "completed_date": "2026-06-12", "type": "Module"},
]

MOCK_PROFILE = {
    "handle": "demo-trailblazer",
    "first_name": "Demo",
    "last_name": "Trainee",
    "company": "Wipro",
    "photo": None,
}

MOCK_RANK = {
    "rank_label": "Ranger",
    "points": 45500,
    "badges": len(MOCK_AWARDS),
    "trails": 3,
}
