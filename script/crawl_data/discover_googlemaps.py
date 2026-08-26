import os
import time
import requests
import pandas as pd

# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "./data/places.csv"
OUTPUT_FILE = "./data/google_places.csv"

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

TEST_PROVINCE = "Đà Nẵng"
TEST_LIMIT = 5

URL = "https://places.googleapis.com/v1/places:searchText"

# ============================================================
# GOOGLE SEARCH
# ============================================================

def search_google(place_name, province):

    query = f"{place_name}, {province}, Vietnam"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName,"
            "places.formattedAddress,"
            "places.location,"
            "places.types,"
            "places.googleMapsUri"
        )
    }

    body = {
        "textQuery": query,
        "pageSize": 5
    }

    response = requests.post(
        URL,
        json=body,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.json().get("places", [])


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GOOGLE MAPS PLACE DISCOVERY")
    print("=" * 70)

    if not API_KEY:
        raise RuntimeError(
            "Missing GOOGLE_MAPS_API_KEY environment variable."
        )

    df = pd.read_csv(INPUT_FILE)

    print(f"Total places loaded: {len(df)}")

    df = df[
        df["province_name"] == TEST_PROVINCE
    ].head(TEST_LIMIT)

    print(f"TEST MODE: {TEST_PROVINCE}")
    print(f"Places to search: {len(df)}")

    results = []

    for i, row in enumerate(df.itertuples(), 1):

        print(f"\n[{i}/{len(df)}] {row.place_name}")

        try:

            places = search_google(
                row.place_name,
                row.province_name
            )

            print(f"Google results: {len(places)}")

            for rank, place in enumerate(places, 1):

                display_name = place.get(
                    "displayName", {}
                ).get("text")

                location = place.get(
                    "location", {}
                )

                results.append({
                    "place_id": row.place_id,
                    "osm_id": row.osm_id,
                    "place_name": row.place_name,
                    "province_name": row.province_name,

                    "google_rank": rank,
                    "google_place_id": place.get("id"),
                    "google_name": display_name,
                    "google_address": place.get(
                        "formattedAddress"
                    ),

                    "google_latitude": location.get(
                        "latitude"
                    ),
                    "google_longitude": location.get(
                        "longitude"
                    ),

                    "google_types": "|".join(
                        place.get("types", [])
                    ),

                    "google_maps_uri": place.get(
                        "googleMapsUri"
                    ),

                    "query": (
                        f"{row.place_name}, "
                        f"{row.province_name}, Vietnam"
                    )
                })

            time.sleep(1)

        except Exception as e:

            print(f"  ERROR: {e}")

    result_df = pd.DataFrame(results)

    result_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n" + "=" * 70)
    print("GOOGLE MAPS DISCOVERY COMPLETED")
    print("=" * 70)

    print(f"Results: {len(result_df)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()