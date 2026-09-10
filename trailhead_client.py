"""
Talks to Trailhead's own internal Aura endpoints (the same ones the
trailblazer.me profile page itself calls in the browser) to pull public
profile info, rank/points, and earned badges for a given Trailhead handle.

This now drives a real headless browser (Playwright) instead of plain
`requests`, because trailblazer.me returns HTTP 403 to plain HTTP calls
regardless of headers -- that's WAF/bot-detection (Cloudflare/Akamai-style)
keying off TLS and JS fingerprints a plain HTTP client can't produce, not
just a missing User-Agent. Running everything (page load AND the Aura POST
calls) inside one real browser context is what gets past that.

IMPORTANT / HONESTY NOTE: Trailhead has no official public API. This code
calls internal, undocumented endpoints, which Salesforce can change or
block further at any time. This sandbox has no network access to
salesforce.com, so none of this can be tested end-to-end from here -- it
has to be verified against real responses on your machine using
diagnose.py. If Trailhead's bot protection blocks even a real headless
browser (some WAFs fingerprint headless Chrome specifically), the next
escalation is running Playwright with `headless=False` or with a stealth
plugin -- let me know what diagnose.py prints and I'll take it from there.
"""

import json
import re

from playwright.sync_api import sync_playwright

BASE_URL = "https://trailblazer.me"
AURA_SERVICE_URL = f"{BASE_URL}/aura"
AURA_CONFIG_URL = f"{BASE_URL}/c/ProfileApp.app?aura.format=JSON&aura.formatAdapter=LIGHTNING_OUT"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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

    bare = raw.rstrip("/").split("/")[-1]
    if re.match(r"^[a-zA-Z0-9\-]+$", bare):
        return bare

    raise TrailheadError(
        "Couldn't recognize that as a Trailhead profile link. Expected something like "
        "https://www.salesforce.com/trailblazer/<handle> or just the handle itself."
    )


def _extract_field(data, paths, default=None):
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
# Browser-driven session
# ---------------------------------------------------------------------------

class BrowserSession:
    """One real (headless) browser page, reused for the page load and every
    Aura call for a single lookup, so everything shares the same cookies /
    TLS+JS fingerprint that got past the bot check on the first request."""

    def __init__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page(user_agent=_UA)

    def get_profile_html(self, handle):
        resp = self._page.goto(_build_profile_url(handle), wait_until="networkidle", timeout=30000)
        status = resp.status if resp else None
        return status, self._page.content()

    def fetch_json(self, url, method="GET", form_data=None):
        """Runs fetch() inside the page's own browser context (so it reuses
        the session/cookies that already passed the bot check)."""
        result = self._page.evaluate(
            """
            async ({url, method, formData}) => {
                const opts = { method };
                if (formData) {
                    opts.body = new URLSearchParams(formData).toString();
                    opts.headers = {'Content-Type': 'application/x-www-form-urlencoded'};
                }
                const res = await fetch(url, opts);
                const text = await res.text();
                return { status: res.status, text };
            }
            """,
            {"url": url, "method": method, "formData": form_data},
        )
        return result["status"], result["text"]

    def close(self):
        self._browser.close()
        self._pw.stop()


def _get_fwuid(session):
    status, text = session.fetch_json(AURA_CONFIG_URL)
    if status != 200:
        raise TrailheadError(
            f"Trailhead's config endpoint returned HTTP {status} even from inside a "
            f"real browser session. Response started with: {_snippet(text)}"
        )
    try:
        return json.loads(text)["delegateVersion"]
    except Exception as exc:
        raise TrailheadError(
            f"Trailhead's config endpoint didn't return the expected JSON. Raw: {_snippet(text)}"
        ) from exc


class _AuraPayload:
    def __init__(self, session):
        self.message = {"actions": []}
        self.aura_context = {"fwuid": _get_fwuid(session), "app": "c:ProfileApp"}
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
    def form_data(self):
        return {
            "message": json.dumps(self.message),
            "aura.context": json.dumps(self.aura_context),
            "aura.token": self.aura_token,
        }


def _aura_call(session, payload):
    status, text = session.fetch_json(AURA_SERVICE_URL, method="POST", form_data=payload.form_data)
    if status != 200:
        raise TrailheadError(f"Trailhead's Aura endpoint returned HTTP {status}. Response started with: {_snippet(text)}")
    try:
        body = json.loads(text)
    except Exception as exc:
        raise TrailheadError(
            f"Trailhead's Aura endpoint didn't return JSON. Raw response: {_snippet(text)}"
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
            f"Trailhead's Aura response didn't have the expected structure. Raw action: {_snippet(json.dumps(action))}"
        ) from exc


def fetch_user_id(session, handle):
    status, html = session.get_profile_html(handle)
    if status == 403:
        raise TrailheadError(
            f"Trailhead blocked the profile page for '{handle}' with HTTP 403 even from a "
            "real browser session. Either the profile is private, or Trailhead's bot "
            "protection is fingerprinting headless Chrome specifically -- if this persists, "
            "tell me and we'll try headless=False or a stealth plugin next."
        )
    if status and status >= 400:
        raise TrailheadError(f"The profile page for '{handle}' returned HTTP {status}.")
    match = re.search(r"User\/(.*?)\\", html)
    if not match:
        raise TrailheadError(
            f"Couldn't find a user ID in the profile page for '{handle}'. Either it's "
            f"private, the handle is wrong, or Trailhead changed its markup. Page start: {_snippet(html[:500])}"
        )
    return match.group(1)


def fetch_profile_data(session, handle):
    _, html = session.get_profile_html(handle)
    match = re.search(r'profileData = JSON.parse\("(.*?)"\)', html)
    if not match:
        raise TrailheadError("Couldn't find embedded profile data on the page.")
    return json.loads(match.group(1).replace("\\", ""))


def fetch_rank_data(session, handle, user_id):
    payload = _AuraPayload(session)
    payload.add_action("TrailheadProfileService", "fetchTrailheadData", {"userId": user_id})
    body = _aura_call(session, payload)
    return body["value"][0]["ProfileCounts"][0]


def fetch_awards(session, handle, user_id, limit=None):
    if limit is None:
        limit = fetch_rank_data(session, handle, user_id).get("EarnedBadgeTotal", 0)

    awards = []
    skip = 0
    while skip < limit:
        payload = _AuraPayload(session)
        payload.add_action("TrailheadProfileService", "fetchTrailheadBadges", {
            "userId": user_id,
            "skip": skip,
            "perPage": min(limit - skip, 30),
            "filter": "All",
        })
        body = _aura_call(session, payload)
        page_awards = body["value"][0]["EarnedAwards"]
        if not page_awards:
            break
        awards.extend(page_awards)
        skip += 30
    return awards


def get_progress_data(raw_profile_input):
    """Returns (awards, profile_info, rank_info) for the given profile
    URL/handle. Raises TrailheadError with a detailed, user-facing message
    on failure."""
    handle = extract_handle(raw_profile_input)

    session = BrowserSession()
    try:
        user_id = fetch_user_id(session, handle)

        try:
            profile_data = fetch_profile_data(session, handle)
        except Exception:
            profile_data = {}

        try:
            rank_data = fetch_rank_data(session, handle, user_id) or {}
        except Exception:
            rank_data = {}

        raw_awards = fetch_awards(session, handle, user_id)
        awards = [_normalize_award(a) for a in raw_awards]
    finally:
        session.close()

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
