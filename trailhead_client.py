"""
trailhead_client.py

Pulls public Trailhead profile info, rank/points, and earned badges for a given
Trailhead handle using Salesforce's official modern Trailhead GraphQL API
(https://profile.api.trailhead.com/graphql).

Unlike legacy scrapers that relied on internal Aura endpoints or headless browsers
(which trigger WAF/Akamai 403 blocks and Windows asyncio event loop conflicts in
Uvicorn), this communicates directly over HTTPS using standard library urllib,
making it fast, lightweight, and robust.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request

GRAPHQL_URL = "https://profile.api.trailhead.com/graphql"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ProfileCache:
    """Thread-safe TTL in-memory cache for profile progress data."""

    def __init__(self, ttl_seconds=3600):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def get(self, handle):
        with self._lock:
            if handle in self._store:
                data, timestamp = self._store[handle]
                if time.time() - timestamp < self.ttl:
                    return data
                del self._store[handle]
        return None

    def set(self, handle, data):
        with self._lock:
            self._store[handle] = (data, time.time())

    def clear(self):
        with self._lock:
            self._store.clear()


GLOBAL_PROFILE_CACHE = ProfileCache()


class TrailheadError(Exception):
    """Raised for errors that should be shown back to the user as-is."""


def _snippet(text, length=200):
    text = (text or "").strip().replace("\n", " ")
    return text[:length] + ("..." if len(text) > length else "")


_HANDLE_PATTERNS = [
    r"trailblazer\.me/id/([a-zA-Z0-9\-_]+)",
    r"trailblazer\.me/([a-zA-Z0-9\-_]+)",
    r"salesforce\.com/trailblazer/([a-zA-Z0-9\-_]+)",
    r"trailhead\.salesforce\.com/[a-zA-Z-]+/me/([a-zA-Z0-9\-_]+)",
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
    if re.match(r"^[a-zA-Z0-9\-_]+$", bare):
        return bare

    raise TrailheadError(
        "Couldn't recognize that as a Trailhead profile link. Expected something like "
        "https://www.salesforce.com/trailblazer/<handle> or just the handle itself."
    )


def _query_graphql(query, op_name, variables):
    payload = json.dumps({
        "operationName": op_name,
        "variables": variables,
        "query": query,
    }).encode("utf-8")

    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise TrailheadError(
            f"Trailhead API returned HTTP {exc.code}: {_snippet(body)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise TrailheadError(
            f"Could not connect to Trailhead ({exc.reason}). Please check your internet connection."
        ) from exc
    except json.JSONDecodeError as exc:
        raise TrailheadError(f"Invalid JSON received from Trailhead API: {exc}") from exc


PROFILE_QUERY = """query GetProfileSummary($slug: String, $hasSlug: Boolean!) {
  profile(slug: $slug) @include(if: $hasSlug) {
    __typename
    ... on PublicProfile {
      id
      name
      avatarUrl
      companyName
      trailheadStats {
        __typename
        earnedPointsSum
        earnedBadgesCount
        completedTrailCount
        rank {
          title
        }
      }
    }
    ... on PrivateProfile {
      __typename
    }
  }
}"""

BADGES_QUERY = """fragment EarnedAward on EarnedAwardBase {
  __typename
  id
  award {
    __typename
    id
    title
    type
    icon
  }
}

fragment EarnedAwardSelf on EarnedAwardSelf {
  __typename
  id
  award {
    __typename
    id
    title
    type
    icon
  }
  earnedAt
  earnedPointsSum
}

query GetTrailheadBadges($slug: String, $hasSlug: Boolean!, $count: Int = 100, $after: String = null) {
  profile(slug: $slug) @include(if: $hasSlug) {
    __typename
    ... on PublicProfile {
      earnedAwards(first: $count, after: $after) {
        edges {
          node {
            ... on EarnedAwardBase {
              ...EarnedAward
            }
            ... on EarnedAwardSelf {
              ...EarnedAwardSelf
            }
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}"""


def get_progress_data(raw_profile_input, force_refresh=False):
    """Returns (awards, profile_info, rank_info) for the given profile URL/handle.
    Serves from cache if available unless force_refresh is True."""
    handle = extract_handle(raw_profile_input)

    if not force_refresh:
        cached = GLOBAL_PROFILE_CACHE.get(handle)
        if cached is not None:
            return cached

    # 1. Fetch Profile & Rank
    data = _query_graphql(PROFILE_QUERY, "GetProfileSummary", {"slug": handle, "hasSlug": True})

    errors = data.get("errors")
    if errors:
        msg = errors[0].get("message", "Unknown GraphQL error")
        raise TrailheadError(f"Trailhead error for '{handle}': {msg}")

    prof = data.get("data", {}).get("profile")
    if not prof:
        raise TrailheadError(
            f"Couldn't find a Trailhead profile for '{handle}'. "
            "Please check that the handle/link is correct."
        )

    if prof.get("__typename") == "PrivateProfile":
        raise TrailheadError(
            f"The Trailhead profile for '{handle}' is set to Private. "
            "The trainee must set their profile to Public in Trailhead (Settings → Privacy → Public Profile)."
        )

    stats = prof.get("trailheadStats") or {}
    rank = stats.get("rank") or {}

    raw_name = (prof.get("name") or "").strip()
    name_parts = raw_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    profile_info = {
        "name": raw_name or f"{first_name} {last_name}".strip() or handle,
        "handle": handle,
        "first_name": first_name,
        "last_name": last_name,
        "company": prof.get("companyName") or "",
        "photo": prof.get("avatarUrl") or None,
    }

    rank_info = {
        "rank_label": rank.get("title") or "Learner",
        "points": stats.get("earnedPointsSum") or 0,
        "badges": stats.get("earnedBadgesCount") or 0,
        "trails": stats.get("completedTrailCount") or 0,
    }

    # 2. Fetch Badges with pagination
    awards = []
    has_next = True
    after = None
    pages = 0
    max_pages = 50  # Safety limit: up to 5000 badges

    while has_next and pages < max_pages:
        pages += 1
        b_data = _query_graphql(
            BADGES_QUERY,
            "GetTrailheadBadges",
            {"slug": handle, "hasSlug": True, "count": 100, "after": after},
        )
        b_errors = b_data.get("errors")
        if b_errors:
            msg = b_errors[0].get("message", "Unknown GraphQL error while fetching badges")
            raise TrailheadError(f"Error fetching badges for '{handle}': {msg}")

        awards_conn = b_data.get("data", {}).get("profile", {}).get("earnedAwards") or {}
        edges = awards_conn.get("edges") or []
        for edge in edges:
            node = edge.get("node") or {}
            award = node.get("award") or {}
            earned_at = node.get("earnedAt")
            if earned_at and "T" in earned_at:
                earned_at = earned_at.split("T")[0]
            awards.append({
                "title": award.get("title"),
                "completed_date": earned_at,
                "type": award.get("type"),
            })

        page_info = awards_conn.get("pageInfo") or {}
        has_next = page_info.get("hasNextPage", False)
        after = page_info.get("endCursor")

    result = (awards, profile_info, rank_info)
    GLOBAL_PROFILE_CACHE.set(handle, result)
    return result
