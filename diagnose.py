"""
Standalone debugging tool -- run this directly (no server needed) when a
real profile fails in the app.

Usage:
    python diagnose.py <handle-or-profile-url>
"""

import sys

import trailhead_client as tc


def main():
    if len(sys.argv) not in (2, 3):
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

    print(f"\n2. Testing get_progress_data pipeline (Cache Miss)...")
    try:
        awards, profile_info, rank_info = tc.get_progress_data(handle, force_refresh=True)
        print(f"   Profile Info: {profile_info}")
        print(f"   Rank Info: {rank_info}")
        print(f"   Awards fetched: {len(awards)}")
    except Exception as e:
        print(f"   Progress data lookup failed: {e}")

    print(f"\n3. Testing get_progress_data pipeline (Cache Hit)...")
    cached_data = tc.GLOBAL_PROFILE_CACHE.get(handle)
    if cached_data:
        print("   -> Cache hit verified!")
    else:
        print("   -> Cache miss.")

    print("\nDiagnostic checks completed.")


if __name__ == "__main__":
    main()
