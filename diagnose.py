"""
Standalone debugging tool -- run this directly (no server needed) when a
real profile fails in the app, to see exactly which HTTP call is failing and
why.

Usage:
    python diagnose.py <handle-or-profile-url>

Example:
    python diagnose.py https://www.salesforce.com/trailblazer/shrinidhi-d-bhat

It prints each step (config fetch, user-ID lookup, rank fetch, badge fetch)
with the actual HTTP status code and a snippet of the raw response, so if
Trailhead has changed something on their end, the output tells you (and me,
if you paste it back) exactly what changed instead of a generic error.
"""

import sys

import trailhead_client as tc


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    raw_input_ = sys.argv[1]

    print(f"1. Extracting handle from: {raw_input_}")
    try:
        handle = tc.extract_handle(raw_input_)
        print(f"   -> handle: {handle}")
    except tc.TrailheadError as e:
        print(f"   FAILED: {e}")
        return

    print(f"\n2. Fetching Aura config (fwuid) from {tc.AURA_CONFIG_URL}")
    try:
        fwuid = tc._get_fwuid()
        print(f"   -> fwuid: {fwuid}")
    except tc.TrailheadError as e:
        print(f"   FAILED: {e}")
        return

    profile_url = tc._build_profile_url(handle)
    print(f"\n3. Fetching profile page: {profile_url}")
    try:
        user_id = tc.fetch_user_id(handle)
        print(f"   -> user_id: {user_id}")
    except tc.TrailheadError as e:
        print(f"   FAILED: {e}")
        print("\n   Since this is the step that broke, here's the raw page fetch for inspection:")
        try:
            resp = tc._SESSION.get(profile_url, timeout=15)
            print(f"   HTTP {resp.status_code}, {len(resp.text)} chars")
            print(f"   First 1000 chars:\n{resp.text[:1000]}")
        except Exception as e2:
            print(f"   Couldn't even fetch the page: {e2}")
        return

    print("\n4. Fetching rank data")
    try:
        rank_data = tc.fetch_rank_data(handle, user_id)
        print(f"   -> {rank_data}")
    except tc.TrailheadError as e:
        print(f"   FAILED: {e}")
        rank_data = {}

    print("\n5. Fetching badges")
    try:
        awards = tc.fetch_awards(handle, user_id)
        print(f"   -> got {len(awards)} awards")
        for a in awards[:5]:
            print(f"      {a}")
        if len(awards) > 5:
            print(f"      ... and {len(awards) - 5} more")
    except tc.TrailheadError as e:
        print(f"   FAILED: {e}")
        return

    print("\nAll steps succeeded.")


if __name__ == "__main__":
    main()
