import os
import uuid
import pandas as pd

from script.crawl_data.pipeline_scope import log_event, utc_now_iso

# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "./data/candidate_places_validated.csv"

PLACES_OUTPUT = "./data/places.csv"
CATEGORIES_OUTPUT = "./data/place_categories.csv"
TAXONOMY_OUTPUT = "./data/taxonomy.csv"
LEGACY_MAPPING_FILE = "./data/legacy_province_mapping.csv"

TEST_MODE = False
TEST_PROVINCE = "Đà Nẵng"

# ============================================================
# TAXONOMY V1
# ============================================================

TAXONOMY = [
    # natural
    ("natural", "landscape", "mountain", "Núi", "Mountain"),
    ("natural", "landscape", "waterfall", "Thác", "Waterfall"),
    ("natural", "landscape", "cave", "Hang động", "Cave"),
    ("natural", "coastal", "beach", "Biển", "Beach"),
    ("natural", "coastal", "cape", "Mũi đất", "Cape"),

    # heritage
    ("heritage", "historical", "monument", "Di tích", "Monument"),
    ("heritage", "historical", "ruins", "Di tích đổ nát", "Ruins"),
    ("heritage", "historical", "archaeological_site",
     "Di chỉ khảo cổ", "Archaeological Site"),
    ("heritage", "historical", "historic_building",
     "Công trình lịch sử", "Historic Building"),
    ("heritage", "religious", "temple",
     "Chùa/đền", "Temple"),

    # culture
    ("culture", "museum", "museum", "Bảo tàng", "Museum"),
    ("culture", "arts", "gallery", "Phòng trưng bày", "Gallery"),

    # recreation
    ("recreation", "park", "public_park", "Công viên", "Public Park"),
    ("recreation", "amusement", "theme_park", "Công viên chủ đề", "Theme Park"),
    ("recreation", "amusement", "water_park", "Công viên nước", "Water Park"),
    ("recreation", "amusement", "zoo", "Vườn thú", "Zoo"),

    # scenic
    ("scenic", "viewpoint", "viewpoint", "Điểm ngắm cảnh", "Viewpoint"),

    # fallback
    ("other", "attraction", "general_attraction",
     "Điểm tham quan", "General Attraction"),
]

# ============================================================
# OSM -> PROJECT TAXONOMY
# ============================================================

OSM_RULES = {
    ("natural", "peak"): [
        ("natural", "landscape", "mountain")
    ],

    ("natural", "waterfall"): [
        ("natural", "landscape", "waterfall")
    ],

    ("natural", "cave_entrance"): [
        ("natural", "landscape", "cave")
    ],

    ("natural", "beach"): [
        ("natural", "coastal", "beach")
    ],

    ("natural", "cape"): [
        ("natural", "coastal", "cape")
    ],

    ("historic", "monument"): [
        ("heritage", "historical", "monument")
    ],

    ("historic", "memorial"): [
        ("heritage", "historical", "monument")
    ],

    ("historic", "ruins"): [
        ("heritage", "historical", "ruins")
    ],

    ("historic", "archaeological_site"): [
        ("heritage", "historical", "archaeological_site")
    ],

    ("historic", "building"): [
        ("heritage", "historical", "historic_building")
    ],

    ("historic", "castle"): [
        ("heritage", "historical", "monument")
    ],

    ("historic", "fort"): [
        ("heritage", "historical", "monument")
    ],

    ("tourism", "museum"): [
        ("culture", "museum", "museum")
    ],

    ("tourism", "gallery"): [
        ("culture", "arts", "gallery")
    ],

    ("tourism", "viewpoint"): [
        ("scenic", "viewpoint", "viewpoint")
    ],

    ("tourism", "theme_park"): [
        ("recreation", "amusement", "theme_park")
    ],

    ("tourism", "zoo"): [
        ("recreation", "amusement", "zoo")
    ],

    ("leisure", "park"): [
        ("recreation", "park", "public_park")
    ],

    ("leisure", "water_park"): [
        ("recreation", "amusement", "water_park")
    ],
}

# ============================================================
# HELPERS
# ============================================================

def create_taxonomy_df():

    rows = []

    for i, item in enumerate(TAXONOMY, start=1):

        group, category, subcategory, name_vi, name_en = item

        rows.append({
            "category_id": f"CAT{i:03d}",
            "group": group,
            "category": category,
            "subcategory": subcategory,
            "name_vi": name_vi,
            "name_en": name_en
        })

    return pd.DataFrame(rows)


def get_osm_tags(row):

    tags = []

    for column in [
        "tourism",
        "natural",
        "historic",
        "leisure"
    ]:

        value = row.get(column)

        if pd.notna(value) and str(value).strip():

            tags.append(
                (column, str(value).strip())
            )

    return tags


def classify_row(row):

    categories = []

    # --------------------------------------------------------
    # Apply OSM rules
    # --------------------------------------------------------

    for tag in get_osm_tags(row):

        if tag in OSM_RULES:

            categories.extend(
                OSM_RULES[tag]
            )

    # --------------------------------------------------------
    # tourism=attraction fallback
    # --------------------------------------------------------

    tourism = row.get("tourism")

    if (
        pd.notna(tourism)
        and tourism == "attraction"
        and not categories
    ):
        categories.append(
            ("other", "attraction", "general_attraction")
        )

    # --------------------------------------------------------
    # Deduplicate
    # --------------------------------------------------------

    categories = list(dict.fromkeys(categories))

    return categories


def make_place_id(osm_type, osm_id):

    # Stable ID based on OSM identity
    return f"OSM_{osm_type}_{osm_id}"


def enrich_admin_columns(df):

    df = df.copy()

    if "current_province_id" not in df.columns:
        df["current_province_id"] = df.get("province_id")

    if "current_province_name" not in df.columns:
        df["current_province_name"] = df.get("province_name")

    if "legacy_province_id" not in df.columns:
        df["legacy_province_id"] = None

    if "legacy_province_name" not in df.columns:
        df["legacy_province_name"] = None

    if (
        os.path.exists(LEGACY_MAPPING_FILE)
        and (
            df["legacy_province_id"].isna().any()
            or df["legacy_province_name"].isna().any()
        )
    ):

        map_df = pd.read_csv(
            LEGACY_MAPPING_FILE,
            dtype={
                "current_province_id": str,
                "legacy_province_id": str,
            }
        )

        expected_cols = {
            "current_province_id",
            "legacy_province_id",
            "legacy_province_name",
        }

        if expected_cols.issubset(set(map_df.columns)):
            df = df.merge(
                map_df[
                    [
                        "current_province_id",
                        "legacy_province_id",
                        "legacy_province_name",
                    ]
                ],
                on="current_province_id",
                how="left",
                suffixes=("", "_mapped"),
            )

            df["legacy_province_id"] = df["legacy_province_id"].fillna(
                df.get("legacy_province_id_mapped")
            )
            df["legacy_province_name"] = df["legacy_province_name"].fillna(
                df.get("legacy_province_name_mapped")
            )

            drop_cols = [
                c
                for c in [
                    "legacy_province_id_mapped",
                    "legacy_province_name_mapped",
                ]
                if c in df.columns
            ]
            if drop_cols:
                df = df.drop(columns=drop_cols)

    return df


# ============================================================
# MAIN
# ============================================================

def main():

    run_id = uuid.uuid4().hex[:12]
    classified_at = utc_now_iso()

    log_event(
        "CLASSIFY",
        "Start place classification",
        run_id=run_id,
        input=INPUT_FILE,
        output_places=PLACES_OUTPUT,
    )

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    df = pd.read_csv(INPUT_FILE)

    log_event(
        "CLASSIFY",
        "Validated records loaded",
        run_id=run_id,
        total_records=len(df),
    )

    # --------------------------------------------------------
    # Keep valid + review
    # --------------------------------------------------------

    df = df[
        df["validation_status"].isin(
            ["valid", "review"]
        )
    ].copy()

    log_event(
        "CLASSIFY",
        "Records kept after validation filter",
        run_id=run_id,
        kept_records=len(df),
    )

    # --------------------------------------------------------
    # TEST MODE
    # --------------------------------------------------------

    if TEST_MODE:

        df = df[
            df["province_name"] == TEST_PROVINCE
        ].copy()

        log_event(
            "CLASSIFY",
            "TEST MODE enabled",
            run_id=run_id,
            test_province=TEST_PROVINCE,
        )

    df = enrich_admin_columns(df)

    # --------------------------------------------------------
    # Create taxonomy
    # --------------------------------------------------------

    taxonomy_df = create_taxonomy_df()

    taxonomy_lookup = {}

    for _, row in taxonomy_df.iterrows():

        key = (
            row["group"],
            row["category"],
            row["subcategory"]
        )

        taxonomy_lookup[key] = row["category_id"]

    # --------------------------------------------------------
    # Create places
    # --------------------------------------------------------

    places = []
    place_categories = []

    for _, row in df.iterrows():

        osm_id = row["osm_id"]
        osm_type = row["osm_type"]

        place_id = make_place_id(
            osm_type,
            osm_id
        )

        categories = classify_row(row)

        # ----------------------------------------------------
        # Place master
        # ----------------------------------------------------

        places.append({

            "place_id": place_id,

            "place_name": row.get("place_name"),
            "name_vi": row.get("name_vi"),
            "name_en": row.get("name_en"),

            "province_id": row.get("province_id"),
            "province_name": row.get("province_name"),
            "current_province_id": row.get("current_province_id"),
            "current_province_name": row.get("current_province_name"),
            "legacy_province_id": row.get("legacy_province_id"),
            "legacy_province_name": row.get("legacy_province_name"),

            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),

            "osm_id": osm_id,
            "osm_type": osm_type,

            "tourism": row.get("tourism"),
            "natural": row.get("natural"),
            "historic": row.get("historic"),
            "leisure": row.get("leisure"),

            "website": row.get("website"),
            "wikidata": row.get("wikidata"),
            "wikipedia": row.get("wikipedia"),

            "source": row.get("source"),

            "validation_status": row.get(
                "validation_status"
            ),

            "classified_at_utc": classified_at,
            "pipeline_run_id": run_id,

            "admin_scope": row.get("province_scope")
            or row.get("admin_scope")
            or "current_34",

        })

        # ----------------------------------------------------
        # Categories
        # ----------------------------------------------------

        for category_index, category in enumerate(
            categories
        ):

            group, cat, subcat = category

            category_id = taxonomy_lookup.get(
                category
            )

            if not category_id:
                continue

            place_categories.append({

                "place_id": place_id,

                "category_id": category_id,

                "group": group,
                "category": cat,
                "subcategory": subcat,

                "is_primary": (
                    category_index == 0
                ),

                "classification_method":
                    "osm_rule",

                "classification_confidence":
                    "high"

            })

    # --------------------------------------------------------
    # DataFrames
    # --------------------------------------------------------

    places_df = pd.DataFrame(places)

    categories_df = pd.DataFrame(
        place_categories
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    os.makedirs(
        os.path.dirname(PLACES_OUTPUT),
        exist_ok=True
    )

    places_df.to_csv(
        PLACES_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    categories_df.to_csv(
        CATEGORIES_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    taxonomy_df.to_csv(
        TAXONOMY_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # REPORT
    # ========================================================

    log_event(
        "CLASSIFY",
        "CLASSIFICATION COMPLETED",
        run_id=run_id,
        places=len(places_df),
        place_category_relations=len(categories_df),
    )

    print()

    print("Classification coverage:")

    classified_ids = set(
        categories_df["place_id"]
    ) if not categories_df.empty else set()

    classified = len(
        set(places_df["place_id"])
        & classified_ids
    )

    unclassified = (
        len(places_df)
        - classified
    )

    print(
        f"  Classified:   {classified}"
    )

    print(
        f"  Unclassified: {unclassified}"
    )

    print()

    if not categories_df.empty:

        print("Places by category:")

        counts = (
            categories_df
            .groupby(
                ["group", "category", "subcategory"]
            )
            .size()
            .reset_index(name="count")
            .sort_values(
                "count",
                ascending=False
            )
        )

        print(
            counts.to_string(index=False)
        )

    print()

    print("Output files:")

    print(
        f"  {PLACES_OUTPUT}"
    )

    print(
        f"  {CATEGORIES_OUTPUT}"
    )

    print(
        f"  {TAXONOMY_OUTPUT}"
    )

    print()

    print("Done.")


if __name__ == "__main__":
    main()