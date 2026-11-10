/*
    ROW COUNT BEFORE / AFTER JOIN: silver_place_temporal_coverage.
    Với mỗi nguồn, tổng count trong bảng coverage (sau khi LEFT JOIN vào spine silver_places)
    phải bằng số dòng của bảng fact Silver tương ứng chỉ tính các place có trong dimension.
    Lệch => có fan-out hoặc mất dữ liệu khi aggregate / join.
    Trả về các nguồn bị lệch.
*/

WITH coverage_totals AS (
    SELECT
        SUM(review_count)           AS review_rows,
        SUM(video_count)            AS video_rows,
        SUM(video_snapshot_count)   AS video_snapshot_rows,
        SUM(comment_count)          AS comment_rows,
        SUM(rating_snapshot_count)  AS rating_rows
    FROM {{ ref('silver_place_temporal_coverage') }}
),

fact_totals AS (
    SELECT
        (SELECT COUNT(*) FROM {{ ref('silver_travel_reviews') }} WHERE is_place_in_dim)                AS review_rows,
        (SELECT COUNT(DISTINCT place_id || '##' || video_id) FROM {{ ref('silver_youtube_videos') }}
            WHERE is_place_in_dim)                                                                     AS video_rows,
        (SELECT COUNT(*) FROM {{ ref('silver_youtube_video_snapshots') }} WHERE is_place_in_dim)       AS video_snapshot_rows,
        (SELECT COUNT(*) FROM {{ ref('silver_youtube_comments') }} WHERE is_place_in_dim)              AS comment_rows,
        (SELECT COUNT(*) FROM {{ ref('silver_google_maps_rating_snapshots') }} WHERE is_place_in_dim)  AS rating_rows
),

compared AS (
    SELECT 'reviews' AS source_name, c.review_rows AS coverage_rows, f.review_rows AS fact_rows
    FROM coverage_totals AS c CROSS JOIN fact_totals AS f
    UNION ALL
    SELECT 'videos', c.video_rows, f.video_rows
    FROM coverage_totals AS c CROSS JOIN fact_totals AS f
    UNION ALL
    SELECT 'video_snapshots', c.video_snapshot_rows, f.video_snapshot_rows
    FROM coverage_totals AS c CROSS JOIN fact_totals AS f
    UNION ALL
    SELECT 'comments', c.comment_rows, f.comment_rows
    FROM coverage_totals AS c CROSS JOIN fact_totals AS f
    UNION ALL
    SELECT 'rating_snapshots', c.rating_rows, f.rating_rows
    FROM coverage_totals AS c CROSS JOIN fact_totals AS f
)

SELECT *
FROM compared
WHERE COALESCE(coverage_rows, 0) <> COALESCE(fact_rows, 0)
