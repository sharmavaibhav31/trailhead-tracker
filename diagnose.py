"""
Standalone debugging tool -- run this directly (no server needed) when a
real profile fails in the app.

Usage:
    python diagnose.py <handle-or-profile-url>
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

    session = tc.BrowserSession()
    try:
        print(f"\n2. Fetching Aura config (fwuid)")
        try:
            fwuid = tc._get_fwuid(session)
            print(f"   -> fwuid: {fwuid}")
        except tc.TrailheadError as e:
            print(f"   FAILED: {e}")
            return

        profile_url = tc._build_profile_url(handle)
        print(f"\n3. Fetching profile page: {profile_url}")
        try:
            user_id = tc.fetch_user_id(session, handle)
            print(f"   -> user_id: {user_id}")
        except tc.TrailheadError as e:
            print(f"   FAILED: {e}")
            status, html = session.get_profile_html(handle)
            print(f"\n   Raw page fetch for inspection -- HTTP {status}, {len(html)} chars")
            print(f"   First 1000 chars:\n{html[:1000]}")
            return

        print("\n4. Fetching rank data")
        try:
            rank_data = tc.fetch_rank_data(session, handle, user_id)
            print(f"   -> {rank_data}")
        except tc.TrailheadError as e:
            print(f"   FAILED: {e}")
            rank_data = {}

        print("\n5. Fetching badges")
        try:
            awards = tc.fetch_awards(session, handle, user_id)
            print(f"   -> got {len(awards)} awards")
            for a in awards[:5]:
                print(f"      {a}")
            if len(awards) > 5:
                print(f"      ... and {len(awards) - 5} more")
        except tc.TrailheadError as e:
            print(f"   FAILED: {e}")
            return

        print("\nAll steps succeeded.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
