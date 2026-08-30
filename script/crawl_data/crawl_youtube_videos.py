import os
import time
import pandas as pd
from datetime import datetime

from ytscrape import YouTube, SearchFilter


# ============================================================
# CONFIG
# ============================================================

PLACES_FILE = "data/reference/places.csv"

VIDEOS_FILE = "data/historical/youtube_videos.csv"

LOG_FILE = "data/historical/youtube_crawl_log.csv"

# ------------------------------------------------------------
# TEST CONFIG
# ------------------------------------------------------------

# None = crawl toàn bộ places.csv
# Ví dụ:
# 10   = test 10 places
# 100  = test 100 places
MAX_PLACES = 10

# Số video tối đa / place
MAX_VIDEOS = 5

# Delay giữa các place
DELAY_SECONDS = 1


# ============================================================
# COLUMNS
# ============================================================

VIDEO_COLUMNS = [
    "place_id",
    "place_name",
    "province_id",
    "province_name",
    "query",
    "video_id",
    "title",
    "channel_id",
    "channel_name",
    "views",
    "duration_seconds",
    "published_at",
    "category",
    "thumbnail",
    "url",
    "crawled_at",
]

LOG_COLUMNS = [
    "place_id",
    "place_name",
    "province_id",
    "province_name",
    "query",
    "status",
    "video_count",
    "error_message",
    "crawled_at",
]


# ============================================================
# HELPER: APPEND CSV
# ============================================================

def append_to_csv(rows, file_path, columns):
    """
    Append rows vào CSV ngay lập tức.

    Nếu file chưa tồn tại:
        → tạo file + header

    Nếu file đã tồn tại:
        → append, không ghi lại header
    """

    if not rows:
        return

    df = pd.DataFrame(rows, columns=columns)

    file_exists = os.path.exists(file_path)

    df.to_csv(
        file_path,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# LOAD PLACES
# ============================================================

places = pd.read_csv(PLACES_FILE)

if MAX_PLACES is not None:
    places = places.head(MAX_PLACES)

print("=" * 70)
print("YOUTUBE VIDEO CRAWLER")
print("=" * 70)

print(f"Places file : {PLACES_FILE}")
print(f"Places      : {len(places)}")
print(f"Max videos  : {MAX_VIDEOS}")
print(f"Videos file : {VIDEOS_FILE}")
print(f"Log file    : {LOG_FILE}")

print("=" * 70)


# ============================================================
# LOAD EXISTING DATA
# ============================================================

# ------------------------------------------------------------
# Existing videos
# ------------------------------------------------------------

if os.path.exists(VIDEOS_FILE):

    existing_videos = pd.read_csv(VIDEOS_FILE)

    existing_video_keys = set(
        zip(
            existing_videos["place_id"].astype(str),
            existing_videos["video_id"].astype(str),
        )
    )

    print(
        f"Existing videos: {len(existing_videos)}"
    )

else:

    existing_videos = pd.DataFrame(
        columns=VIDEO_COLUMNS
    )

    existing_video_keys = set()

    print("Existing videos: 0")


# ------------------------------------------------------------
# Existing crawl log
# ------------------------------------------------------------

if os.path.exists(LOG_FILE):

    crawl_log = pd.read_csv(LOG_FILE)

else:

    crawl_log = pd.DataFrame(
        columns=LOG_COLUMNS
    )


# ============================================================
# BUILD SUCCESS PLACE SET
# ============================================================

successful_places = set()

if not crawl_log.empty:

    successful_places = set(
        crawl_log.loc[
            crawl_log["status"] == "success",
            "place_id"
        ].astype(str)
    )


print(
    f"Successful places already crawled: "
    f"{len(successful_places)}"
)

print("=" * 70)


# ============================================================
# CRAWL
# ============================================================

total_success = 0
total_failed = 0
total_skipped = 0
total_new_videos = 0


with YouTube(
    language="vi",
    region="VN"
) as yt:

    for index, row in places.iterrows():

        place_id = str(row["place_id"])

        place_name = row["place_name"]

        province_id = row["province_id"]

        province_name = row["province_name"]

        query = f"{place_name} {province_name}"


        # ====================================================
        # CHECK PLACE ALREADY CRAWLED
        # ====================================================

        if place_id in successful_places:

            print()
            print(
                f"[{index + 1}/{len(places)}] "
                f"[SKIP] {place_name}"
            )

            print(
                "       Reason: already crawled successfully"
            )

            total_skipped += 1

            continue


        # ====================================================
        # START PLACE
        # ====================================================

        print()
        print("=" * 70)

        print(
            f"[{index + 1}/{len(places)}] "
            f"{place_name}"
        )

        print(
            f"Province : {province_name}"
        )

        print(
            f"Place ID : {place_id}"
        )

        print(
            f"Query    : {query}"
        )

        print("=" * 70)


        place_videos = []


        try:

            # =================================================
            # SEARCH YOUTUBE
            # =================================================

            print("Searching YouTube...")

            results = yt.search(
                query,
                filter=SearchFilter.VIDEOS,
                max_results=MAX_VIDEOS,
            )


            search_count = 0


            for video_result in results:

                search_count += 1


                try:

                    # =========================================
                    # GET VIDEO DETAILS
                    # =========================================

                    video = yt.video(
                        video_result.url
                    )

                    video_id = str(
                        video.video_id
                    )


                    # =========================================
                    # CHECK DUPLICATE VIDEO
                    # =========================================

                    video_key = (
                        place_id,
                        video_id
                    )


                    if video_key in existing_video_keys:

                        print(
                            f"  [SKIP VIDEO] "
                            f"{video_id}"
                        )

                        continue


                    # =========================================
                    # CREATE RECORD
                    # =========================================

                    video_data = {

                        "place_id":
                            place_id,

                        "place_name":
                            place_name,

                        "province_id":
                            province_id,

                        "province_name":
                            province_name,

                        "query":
                            query,

                        "video_id":
                            video_id,

                        "title":
                            video.title,

                        "channel_id":
                            video.channel_id,

                        "channel_name":
                            video.channel,

                        "views":
                            video.views,

                        "duration_seconds":
                            video.length_seconds,

                        "published_at":
                            video.published,

                        "category":
                            video.category,

                        "thumbnail":
                            video.thumbnail,

                        "url":
                            video.url,

                        "crawled_at":
                            datetime.now().isoformat(),

                    }


                    place_videos.append(
                        video_data
                    )

                    existing_video_keys.add(
                        video_key
                    )


                    print(
                        f"  [OK] "
                        f"{video.title}"
                    )

                    print(
                        f"       ID    : {video_id}"
                    )

                    print(
                        f"       Views : {video.views}"
                    )


                except Exception as e:

                    print(
                        "  [ERROR VIDEO]"
                    )

                    print(
                        f"       URL: "
                        f"{video_result.url}"
                    )

                    print(
                        f"       {e}"
                    )


            # =================================================
            # SAVE VIDEOS IMMEDIATELY
            # =================================================

            append_to_csv(
                place_videos,
                VIDEOS_FILE,
                VIDEO_COLUMNS,
            )


            total_new_videos += len(
                place_videos
            )


            # =================================================
            # WRITE SUCCESS LOG
            # =================================================

            log_row = {

                "place_id":
                    place_id,

                "place_name":
                    place_name,

                "province_id":
                    province_id,

                "province_name":
                    province_name,

                "query":
                    query,

                "status":
                    "success",

                "video_count":
                    len(place_videos),

                "error_message":
                    "",

                "crawled_at":
                    datetime.now().isoformat(),
            }


            append_to_csv(
                [log_row],
                LOG_FILE,
                LOG_COLUMNS,
            )


            successful_places.add(
                place_id
            )

            total_success += 1


            print()
            print(
                f"✓ Place finished"
            )

            print(
                f"  Videos found : "
                f"{search_count}"
            )

            print(
                f"  New videos   : "
                f"{len(place_videos)}"
            )


        except Exception as e:

            # =================================================
            # SEARCH / PLACE ERROR
            # =================================================

            print()
            print(
                "❌ PLACE FAILED"
            )

            print(
                f"   Error: {e}"
            )


            log_row = {

                "place_id":
                    place_id,

                "place_name":
                    place_name,

                "province_id":
                    province_id,

                "province_name":
                    province_name,

                "query":
                    query,

                "status":
                    "failed",

                "video_count":
                    0,

                "error_message":
                    str(e),

                "crawled_at":
                    datetime.now().isoformat(),
            }


            append_to_csv(
                [log_row],
                LOG_FILE,
                LOG_COLUMNS,
            )


            total_failed += 1


        # ====================================================
        # DELAY
        # ====================================================

        time.sleep(
            DELAY_SECONDS
        )


# ============================================================
# SUMMARY
# ============================================================

print()
print()
print("=" * 70)
print("YOUTUBE VIDEO CRAWLER FINISHED")
print("=" * 70)

print(
    f"Successful places : {total_success}"
)

print(
    f"Failed places     : {total_failed}"
)

print(
    f"Skipped places    : {total_skipped}"
)

print(
    f"New videos        : {total_new_videos}"
)

print()
print(
    f"Videos CSV : {VIDEOS_FILE}"
)

print(
    f"Log CSV    : {LOG_FILE}"
)

print("=" * 70)
