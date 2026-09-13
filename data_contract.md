# Data Contract - Ingestion and Bronze

Version: 1.0
Timezone: UTC
Encoding: UTF-8
Format: CSV for current files; Parquet or JSONL is preferred for Bronze

## 1. Common rules

- Every dataset has one record per row and a stable business key where one exists.
- `*_id` fields are strings. Do not let CSV readers infer identifiers as integers.
- `province_id` is a string. Preserve the source representation in Bronze; normalize the canonical representation in Silver.
- Coordinates are decimal degrees as `float64`: latitude is in `[-90, 90]`, longitude is in `[-180, 180]`.
- Counts are nullable non-negative `int64`; ratings are nullable `float64` in `[0, 5]`.
- Boolean fields are nullable `boolean`, represented as `true` or `false` after normalization.
- Timestamps ending in `_utc` are timezone-aware ISO 8601 timestamps with offset `+00:00` or suffix `Z`.
- Empty CSV values represent null. Empty strings are not valid substitutes for null in Silver.
- Bronze preserves source values and source field names. Type coercion, trimming, and deduplication belong in Silver.
- Each Bronze object also carries ingestion metadata: `run_id`, `source`, `source_url` or `source_id` when available, `ingested_at_utc`, `pipeline_version`, `crawler_version`, `attempt`, and `record_status`.

## 2. Current datasets

### 2.1 `places`

Role: curated place dimension used by downstream crawlers.

Business key: `place_id`

| Field | Type | Nullable |
|---|---|---|
| place_id | string | no |
| place_name | string | no |
| name_vi | string | yes |
| name_en | string | yes |
| province_id | string | no |
| province_name | string | no |
| current_province_id | string | yes |
| current_province_name | string | yes |
| legacy_province_id | string | yes |
| legacy_province_name | string | yes |
| latitude | float64 | no |
| longitude | float64 | no |
| osm_id | string | no |
| osm_type | string | no |
| tourism | string | yes |
| natural | string | yes |
| historic | string | yes |
| leisure | string | yes |
| website | string | yes |
| wikidata | string | yes |
| wikipedia | string | yes |
| source | string | no |
| validation_status | enum: valid, invalid, quarantine | no |
| classified_at_utc | timestamp UTC | yes |
| pipeline_run_id | string | yes |
| admin_scope | enum: current_34, legacy_63 | no |

### 2.2 `google_maps_ratings`

Role: place-level rating observation.

Business key: (`place_id`, `crawled_at`)

| Field | Type | Nullable |
|---|---|---|
| place_id | string | no |
| place_name | string | no |
| province_id | string | yes |
| province_name | string | yes |
| google_maps_url | string | yes |
| google_rating | float64, 0-5 | yes |
| google_review_count | int64, >=0 | yes |
| rating_5_count | int64, >=0 | no |
| rating_4_count | int64, >=0 | no |
| rating_3_count | int64, >=0 | no |
| rating_2_count | int64, >=0 | no |
| rating_1_count | int64, >=0 | no |
| crawl_status | enum: success, failed, skipped, quarantine | no |
| error_message | string | yes |
| crawled_at | timestamp UTC | no |

Note: rating distribution counts may be zero when the source does not expose the distribution. They are not equivalent to null.

### 2.3 `google_maps_reviews`

Role: review-level observation.

Business key: `review_id`; expected uniqueness within `source`.

| Field | Type | Nullable |
|---|---|---|
| review_id | string | no |
| place_id | string | no |
| rating | int64, 1-5 | yes |
| review_text | string | yes |
| review_date | string (source display value) | yes |
| likes_count | int64, >=0 | yes |
| source | string | no |
| crawled_at_utc | timestamp UTC | no |

`review_date` is intentionally retained as source text in Bronze because values such as "one month ago" are relative and cannot be interpreted reliably without crawl time. Silver may add a parsed date and retain the original.

### 2.4 `youtube_videos`

Role: video-level social trend observation.

Business key: (`place_id`, `video_id`)

| Field | Type | Nullable |
|---|---|---|
| place_id | string | no |
| place_name | string | no |
| province_id | string | yes |
| province_name | string | yes |
| query | string | yes |
| video_id | string | no |
| title | string | yes |
| channel_id | string | yes |
| channel_name | string | yes |
| views | int64, >=0 | yes |
| duration_seconds | int64, >=0 | yes |
| published_at | timestamp with source offset | yes |
| category | string | yes |
| thumbnail | string | yes |
| url | string | yes |
| crawled_at | timestamp UTC | no |

### 2.5 `youtube_comments`

Role: comment-level social observation.

Business key: (`video_id`, `author`, `text`, `crawled_at`); add a source comment ID when the crawler can provide one.

| Field | Type | Nullable |
|---|---|---|
| place_id | string | no |
| place_name | string | no |
| province_id | string | yes |
| province_name | string | yes |
| video_id | string | no |
| video_title | string | yes |
| author | string | yes |
| text | string | yes |
| likes | int64, >=0 | yes |
| is_reply | boolean | yes |
| crawled_at | timestamp UTC | no |

## 3. Additional historical datasets

### 3.1 `candidate_places_raw`

Role: immutable OSM discovery output before spatial validation.

Business key: (`osm_type`, `osm_id`)

Fields: `osm_id` string not null; `osm_type` string not null; `place_name` string not null; `name_vi`, `name_en`, `tourism`, `natural`, `historic`, `leisure`, `website`, `wikidata`, `wikipedia`, `tags_json`, `source` strings nullable except `source`; `latitude`, `longitude` float64 not null; `province_id`, `province_name` strings nullable.

`tags_json` is a JSON object string in CSV and must remain parseable JSON in Bronze.

### 3.2 `candidate_places_validated`

Role: OSM candidates enriched by spatial validation.

Business key: (`osm_type`, `osm_id`)

Fields: all `candidate_places_raw` fields, plus `validation_status` enum (not null), `validation_reason` string nullable, `spatial_status` enum nullable, `boundary_distance_m` float64 nullable, `validated_at_utc` timestamp UTC nullable, and `pipeline_run_id` string nullable.

### 3.3 `google_maps_errors`

Role: crawl error/quarantine events, not a place fact table.

Business key: (`place_id`, `failed_at`, `error_type`)

Fields: `place_id` string not null; `place_name`, `province_id`, `province_name`, `error_type`, `error_message` strings nullable except `error_type`; `failed_at` timestamp UTC not null.

### 3.4 `youtube_crawl_log`

Role: one execution result per place and query.

Business key: (`place_id`, `query`, `crawled_at`)

Fields: `place_id` string not null; `place_name`, `province_id`, `province_name`, `query` strings nullable; `status` enum: success, failed, skipped, quarantine; `video_count` int64 nullable and >=0; `error_message` string nullable; `crawled_at` timestamp UTC not null.

## 4. Reference datasets

Reference datasets are versioned inputs to processing. They may be stored under `bronze/reference/` and should not be mixed with crawl observations.

### 4.1 `provinces`

Business key: `province_id`

Fields: `province_id` string not null; `province_name` string not null; `min_lon`, `min_lat`, `max_lon`, `max_lat` float64 not null; `geojson_url` string nullable. Bounding-box validity: `min_lon <= max_lon` and `min_lat <= max_lat`.

### 4.2 `taxonomy`

Business key: `category_id`

Fields: `category_id` string not null; `group`, `category`, `subcategory`, `name_vi`, `name_en` strings nullable except `group` and `category`.

### 4.3 `place_categories`

Business key: (`place_id`, `category_id`)

Fields: `place_id` string not null; `category_id`, `group`, `category`, `subcategory` strings nullable except `category_id`; `is_primary` boolean nullable; `classification_method` string nullable; `classification_confidence` enum nullable: low, medium, high.

## 5. Bronze layout

```text
bronze/
  osm/candidate_places_raw/crawl_date=YYYY-MM-DD/
  osm/candidate_places_validated/crawl_date=YYYY-MM-DD/
  places/crawl_date=YYYY-MM-DD/
  google_maps/ratings/crawl_date=YYYY-MM-DD/
  google_maps/reviews/crawl_date=YYYY-MM-DD/
  google_maps/errors/crawl_date=YYYY-MM-DD/
  youtube/videos/crawl_date=YYYY-MM-DD/
  youtube/comments/crawl_date=YYYY-MM-DD/
  youtube/crawl_log/crawl_date=YYYY-MM-DD/
  reference/provinces/version=.../
  reference/taxonomy/version=.../
  reference/place_categories/version=.../
```

A crawl date is derived from the crawler event timestamp in UTC. Historical snapshots are append-only; a writer must fail rather than overwrite an existing partition.

## 6. Known migration issues

- `province_id` appears as `01` in OSM/province files and as `1` in some downstream CSVs. Backfill must read it as string and apply an explicit mapping before Silver joins.
- `places.csv` uses `place_id`, while OSM discovery files use (`osm_type`, `osm_id`). The transformation must preserve both and must not fabricate an OSM ID from a display name.
- `google_maps_reviews.review_date` contains relative display text. Keep it as source text in Bronze.
- `google_maps_ratings` uses `crawled_at`, while reviews use `crawled_at_utc`; the canonical Silver name is `crawled_at_utc`.
- `youtube_videos.published_at` contains a source timezone offset; normalize to UTC in Silver while preserving the original Bronze value.
- `google_maps_errors` and `youtube_crawl_log` are operational datasets. They support observability and retry decisions and must not be joined as if they were observations.

## 7. Operational ingestion commands

Historical CSV snapshots can be imported into Bronze once with:

```bash
python -m script.crawl_data.backfill_historical
```

The command writes immutable JSONL partitions and a manifest under `data/bronze/_backfill/`; a second run skips files already imported. Live jobs keep the legacy CSV outputs for compatibility and additionally write the same records to Bronze with ingestion metadata. Per-item resume state is stored under `data/bronze/_state/`. Records that fail required-field or range checks are written under `data/bronze/quarantine/` and are not treated as successful crawl items.
