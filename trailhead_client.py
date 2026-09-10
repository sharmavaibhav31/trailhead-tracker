"""
Talks to Trailhead's own internal Aura endpoints (the same ones the
trailblazer.me profile page itself calls in the browser) to pull public
profile info, rank/points, and earned badges for a given Trailhead handle.

This used to just call the third-party `trailhead-scraper` PyPI package.
It's vendored and rewritten in-house now because that package's calls were
failing against real profiles (see CHANGELOG note below) and, as a small
unmaintained dependency, it gave us no visibility into *why* -- every
failure came back as the same generic exception. This version keeps every
HTTP response's status code and a text snippet attached to errors, so if it
breaks again the error message itself tells us what changed, instead of us
guessing. `diagnose.py` in this same folder runs all of this step by step
and prints the raw responses if you need to debug further.

IMPORTANT / HONESTY NOTE: Trailhead has no official public API. This code
calls internal, undocumented endpoints, which Salesforce can change without
notice. This sandbox has no network access to salesforce.com, so none of
this can be tested end-to-end from here -- it has to be debugged against
real responses on your machine using diagnose.py.
"""

import json
import re

import requests

BASE_URL = "https://trailblazer.me"
AURA_SERVICE_URL = f"{BASE_URL}/aura"
AURA_CONFIG_URL = f"{BASE_URL}/c/ProfileApp.app?aura.format=JSON&aura.formatAdapter=LIGHTNING_OUT"

# A plain `requests` default User-Agent (python-requests/x.x) gets treated as
# a bot by a lot of front-ends and served a different (often JS-only or
# consent-wall) page than a browser would get. Sending browser-like headers
# is the single highest-value fix for scrapers like this breaking silently.
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


class TrailheadError(Exception):
    """Raised for anything that should be shown back to the user as-is."""


def _snippet(text, length=300):
    text = (text or "").strip().replace("\n", " ")
    return text[:length] + ("..." if len(text) > length else "")


def _build_profile_url(handle):
    return f"{BASE_URL}/id/{handle}"


_HANDLE_PATTERNS = [
    r"trailblazer\.me/id/([a-zA-Z0-9\-]+)",
    r"trailblazer\.me/([a-zA-Z0-9\-]+)",
    r"salesforce\.com/trailblazer/([a-zA-Z0-9\-]+)",
    r"trailhead\.salesforce\.com/[a-zA-Z-]+/me/([a-zA-Z0-9\-]+)",
]


def extract_handle(raw_input):
    """Pulls a bare Trailhead handle out of whatever the user pasted in --
    a full profile URL in one of a few known formats, or just the handle."""
    raw = (raw_input or "").strip()
    if not raw:
        raise TrailheadError("Please enter a Trailhead profile URL or handle.")

    for pattern in _HANDLE_PATTERNS:
        match = re.search(pattern, raw, re.I)
        if match:
            return match.group(1)

    # No URL pattern matched -- if it's a bare word/handle, use it directly.
    bare = raw.rstrip("/").split("/")[-1]
    if re.match(r"^[a-zA-Z0-9\-]+$", bare):
        return bare

    raise TrailheadError(
        "Couldn't recognize that as a Trailhead profile link. Expected something like "
        "https://www.salesforce.com/trailblazer/<handle> or just the handle itself."
    )


def _extract_field(data, paths, default=None):
    """Tries several possible key-paths against a dict and returns the first
    that resolves, so a Trailhead schema change in one field doesn't break
    everything else."""
    for path in paths:
        node = data
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and node is not None:
            return node
    return default


def _normalize_award(award):
    return {
        "title": _extract_field(award, [
            ["Award", "Label"], ["Award", "Title"], ["Title"], ["Label"], ["Name"],
        ]),
        "completed_date": _extract_field(award, [
            ["CompletedDate"], ["EarnedDate"], ["DateEarned"], ["DateCompleted"],
            ["Award", "CompletedDate"], ["Award", "EarnedDate"],
        ]),
        "type": _extract_field(award, [["AwardType"], ["Type"]]),
    }


# ---------------------------------------------------------------------------
# Low-level Aura calls (vendored + hardened; see module docstring for why)
# ---------------------------------------------------------------------------

def _get_fwuid():
    resp = _SESSION.get(AURA_CONFIG_URL, timeout=15)
    if not resp.ok:
        raise TrailheadError(
            f"Trailhead's config endpoint returned HTTP {resp.status_code} "
            f"instead of the expected JSON. Response started with: {_snippet(resp.text)}"
        )
    try:
        return resp.json()["delegateVersion"]
    except Exception as exc:
        raise TrailheadError(
            "Trailhead's config endpoint didn't return the JSON shape we expected "
            f"(this usually means their frontend changed). Raw response: {_snippet(resp.text)}"
        ) from exc


class _AuraPayload:
    def __init__(self):
        self.message = {"actions": []}
        self.aura_context = {"fwuid": _get_fwuid(), "app": "c:ProfileApp"}
        self.aura_token = "undefined"
        self.descriptor = "aura://ApexActionController/ACTION$execute"

    def add_action(self, class_name, method_name, inner_params):
        self.message["actions"].append({
            "descriptor": self.descriptor,
            "params": {
                "namespace": "",
                "classname": class_name,
                "method": method_name,
                "params": inner_params,
                "cacheable": False,
                "isContinuation": False,
            },
        })

    @property
    def data(self):
        return {
            "message": json.dumps(self.message),
            "aura.context": json.dumps(self.aura_context),
            "aura.token": self.aura_token,
        }


def _aura_call(payload):
    resp = _SESSION.post(AURA_SERVICE_URL, data=payload.data, timeout=15)
    if not resp.ok:
        raise TrailheadError(
            f"Trailhead's Aura endpoint returned HTTP {resp.status_code}. "
            f"Response started with: {_snippet(resp.text)}"
        )
    try:
        body = resp.json()
    except Exception as exc:
        raise TrailheadError(
            "Trailhead's Aura endpoint didn't return JSON (possibly a login/consent "
            f"page instead). Raw response started with: {_snippet(resp.text)}"
        ) from exc

    actions = body.get("actions", [])
    if not actions:
        raise TrailheadError(f"Trailhead's Aura endpoint returned no actions. Raw body: {_snippet(json.dumps(body))}")

    action = actions[0]
    if action.get("state") == "ERROR":
        error_detail = action.get("error", [{}])[0].get("message", "unknown error")
        raise TrailheadError(f"Trailhead's Aura endpoint reported an error: {error_detail}")

    try:
        return json.loads(action["returnValue"]["returnValue"]["body"])
    except Exception as exc:
        raise TrailheadError(
            "Trailhead's Aura response didn't have the expected structure. "
            f"Raw action: {_snippet(json.dumps(action))}"
        ) from exc


def fetch_user_id(handle):
    resp = _SESSION.get(_build_profile_url(handle), timeout=15)
    if not resp.ok:
        raise TrailheadError(
            f"The profile page for '{handle}' returned HTTP {resp.status_code} "
            f"(url: {_build_profile_url(handle)}). If this is a redirect to a login "
            "page, the profile is likely private."
        )
    match = re.search(r"User\/(.*?)\\", resp.text)
    if not match:
        raise TrailheadError(
            f"Couldn't find a user ID in the profile page for '{handle}'. Either the "
            "profile is private, the handle is wrong, or Trailhead changed how it "
            f"embeds this data. Page title/start: {_snippet(resp.text[:500])}"
        )
    return match.group(1)


def fetch_profile_data(handle):
    resp = _SESSION.get(_build_profile_url(handle), timeout=15)
    match = re.search(r'profileData = JSON.parse\("(.*?)"\)', resp.text)
    if not match:
        raise TrailheadError("Couldn't find embedded profile data on the page.")
    return json.loads(match.group(1).replace("\\", ""))


def fetch_rank_data(handle, user_id):
    payload = _AuraPayload()
    payload.add_action("TrailheadProfileService", "fetchTrailheadData", {"userId": user_id})
    body = _aura_call(payload)
    return body["value"][0]["ProfileCounts"][0]


def fetch_awards(handle, user_id, limit=None):
    if limit is None:
        limit = fetch_rank_data(handle, user_id).get("EarnedBadgeTotal", 0)

    awards = []
    skip = 0
    while skip < limit:
        payload = _AuraPayload()
        payload.add_action("TrailheadProfileService", "fetchTrailheadBadges", {
            "userId": user_id,
            "skip": skip,
            "perPage": min(limit - skip, 30),
            "filter": "All",
        })
        body = _aura_call(payload)
        page_awards = body["value"][0]["EarnedAwards"]
        if not page_awards:
            break
        awards.extend(page_awards)
        skip += 30
    return awards


def get_progress_data(raw_profile_input):
    """Returns (awards, profile_info, rank_info) for the given profile
    URL/handle. Raises TrailheadError with a detailed, user-facing message
    (including HTTP status/response snippets) on failure -- if this fails,
    the exception text itself should say why."""
    handle = extract_handle(raw_profile_input)

    user_id = fetch_user_id(handle)  # let TrailheadError propagate with full detail

    try:
        profile_data = fetch_profile_data(handle)
    except Exception:
        profile_data = {}

    try:
        rank_data = fetch_rank_data(handle, user_id) or {}
    except Exception:
        rank_data = {}

    raw_awards = fetch_awards(handle, user_id)  # let TrailheadError propagate with full detail
    awards = [_normalize_award(a) for a in raw_awards]

    profile_info = {
        "handle": handle,
        "first_name": _extract_field(profile_data, [["profileUser", "FirstName"]]),
        "last_name": _extract_field(profile_data, [["profileUser", "LastName"]]),
        "company": _extract_field(profile_data, [["profileUser", "CompanyName"]]),
        "photo": _extract_field(profile_data, [["profilePhotoUrl"]]),
    }
    rank_info = {
        "rank_label": rank_data.get("RankLabel"),
        "points": rank_data.get("EarnedPointTotal"),
        "badges": rank_data.get("EarnedBadgeTotal"),
        "trails": rank_data.get("CompletedTrailTotal"),
    }
    return awards, profile_info, rank_info
