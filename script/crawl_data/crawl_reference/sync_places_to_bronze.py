from __future__ import annotations

import shutil
import uuid
import pandas as pd

from ..config import BRONZE_ROOT, REFERENCE_ROOT
from ..utils.ingestion_storage import BronzeWriter
from .classify_places import (
    CATEGORIES_OUTPUT,
    PLACES_OUTPUT,
    TAXONOMY_OUTPUT,
    classify_row,
    create_taxonomy_df,
)


def sync_reference_places_to_bronze() -> None:
    run_id = uuid.uuid4().hex[:12]

    places_df = pd.read_csv(PLACES_OUTPUT, dtype=str, encoding="utf-8-sig").fillna("")
    taxonomy_df = create_taxonomy_df()

    taxonomy_lookup = {
        (row["group"], row["category"], row["subcategory"]): row["category_id"]
        for _, row in taxonomy_df.iterrows()
    }

    place_categories: list[dict[str, object]] = []
    for _, row in places_df.iterrows():
        place_id = str(row.get("place_id", "")).strip()
        if not place_id:
            continue
        categories = classify_row(row)
        for idx, cat_tuple in enumerate(categories):
            group, cat, subcat = cat_tuple
            category_id = taxonomy_lookup.get(cat_tuple)
            if not category_id:
                continue
            place_categories.append(
                {
                    "place_id": place_id,
                    "category_id": category_id,
                    "group": group,
                    "category": cat,
                    "subcategory": subcat,
                    "is_primary": idx == 0,
                    "classification_method": "osm_rule",
                    "classification_confidence": "high",
                }
            )

    categories_df = pd.DataFrame(place_categories)
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    categories_df.to_csv(CATEGORIES_OUTPUT, index=False, encoding="utf-8-sig")
    taxonomy_df.to_csv(TAXONOMY_OUTPUT, index=False, encoding="utf-8-sig")

    writer_places = BronzeWriter(
        "places",
        "openstreetmap",
        run_id=run_id,
        crawler_version="reference-places-sync-1",
    )

    # Clear old local and S3 partitions for places & place_categories so Bronze matches reference/places.csv
    for dataset in ("places", "reference/place_categories"):
        local_dir = BRONZE_ROOT / dataset
        if local_dir.exists():
            shutil.rmtree(local_dir)
        s3_prefix = f"{writer_places.s3_root}/{dataset}".removeprefix("s3://")
        if writer_places.s3.exists(s3_prefix):
            writer_places.s3.rm(s3_prefix, recursive=True)

    places_stats = writer_places.write(places_df.to_dict("records"))
    cat_stats = BronzeWriter(
        "reference/place_categories",
        "openstreetmap",
        run_id=run_id,
        crawler_version="reference-places-sync-1",
    ).write(categories_df.to_dict("records"))

    print("========================================")
    print("SYNC REFERENCE PLACES & CATEGORIES -> BRONZE")
    print("========================================")
    print(f"  places.csv rows           : {len(places_df):,}")
    print(f"  Bronze places written     : {places_stats}")
    print(f"  place_categories.csv rows : {len(categories_df):,}")
    print(f"  Bronze categories written : {cat_stats}")
    print("========================================")


if __name__ == "__main__":
    sync_reference_places_to_bronze()
