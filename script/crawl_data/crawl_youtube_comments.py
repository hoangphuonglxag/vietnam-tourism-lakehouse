import os
import time
import pandas as pd
from datetime import datetime

from ytscrape import YouTube, CommentSort


# ============================================================
# CONFIG
# ============================================================

VIDEOS_FILE = "data/historical/youtube_videos.csv"

COMMENTS_FILE = "data/historical/youtube_comments.csv"

LOG_FILE = "data/historical/youtube_comments_crawl_log.csv"


# ============================================================
# TEST CONFIG
# ============================================================

# None = crawl toàn bộ videos
#
# Ví dụ:
# 20  -> test 20 videos
# 100 -> test 100 videos
MAX_VIDEOS = 20

# Số TOP comments lấy từ mỗi video
MAX_COMMENTS = 5

# Delay giữa các video
DELAY_SECONDS = 1


# ============================================================
# OUTPUT COLUMNS
# ============================================================

COMMENT_COLUMNS = [
    "place_id",
    "place_name",
    "province_id",
    "province_name",
    "video_id",
    "video_title",
    "author",
    "text",
    "likes",
    "is_reply",
    "crawled_at",
]

LOG_COLUMNS = [
    "place_id",
    "place_name",
    "province_id",
    "province_name",
    "video_id",
    "video_title",
    "status",
    "comment_count",
    "error_message",
    "crawled_at",
]


# ============================================================
# HELPER
# ============================================================

def append_to_csv(rows, file_path, columns):
    """
    Append dữ liệu vào CSV ngay lập tức.

    Nếu file chưa tồn tại:
        -> tạo file + header

    Nếu file đã tồn tại:
        -> append dữ liệu, không ghi lại header
    """

    if not rows:
        return

    df = pd.DataFrame(
        rows,
        columns=columns,
    )

    file_exists = os.path.exists(file_path)

    df.to_csv(
        file_path,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# CHECK INPUT FILE
# ============================================================

if not os.path.exists(VIDEOS_FILE):

    raise FileNotFoundError(
        f"Không tìm thấy file:\n"
        f"{VIDEOS_FILE}\n\n"
        f"Hãy chạy crawl_youtube_videos.py trước."
    )


# ============================================================
# LOAD VIDEOS
# ============================================================

videos = pd.read_csv(
    VIDEOS_FILE
)


# ============================================================
# REMOVE DUPLICATE VIDEOS
# ============================================================

videos = videos.drop_duplicates(
    subset=[
        "place_id",
        "video_id",
    ],
    keep="first",
)


# ============================================================
# LIMIT VIDEOS FOR TEST
# ============================================================

if MAX_VIDEOS is not None:

    videos = videos.head(
        MAX_VIDEOS
    )


# ============================================================
# PRINT CONFIG
# ============================================================

print("=" * 70)
print("YOUTUBE COMMENT CRAWLER")
print("=" * 70)

print(
    f"Input videos : {VIDEOS_FILE}"
)

print(
    f"Videos       : {len(videos)}"
)

print(
    f"Max comments : {MAX_COMMENTS}"
)

print(
    f"Comments CSV : {COMMENTS_FILE}"
)

print(
    f"Log CSV      : {LOG_FILE}"
)

print("=" * 70)


# ============================================================
# LOAD EXISTING COMMENTS
# ============================================================

if os.path.exists(COMMENTS_FILE):

    existing_comments = pd.read_csv(
        COMMENTS_FILE
    )

else:

    existing_comments = pd.DataFrame(
        columns=COMMENT_COLUMNS
    )


print(
    f"Existing comments: "
    f"{len(existing_comments)}"
)


# ============================================================
# BUILD COMMENT DUPLICATE SET
# ============================================================

existing_comment_keys = set()


if not existing_comments.empty:

    for _, row in existing_comments.iterrows():

        comment_key = (
            str(row["video_id"]),
            str(row["author"]),
            str(row["text"]),
        )

        existing_comment_keys.add(
            comment_key
        )


# ============================================================
# LOAD CRAWL LOG
# ============================================================

if os.path.exists(LOG_FILE):

    crawl_log = pd.read_csv(
        LOG_FILE
    )

else:

    crawl_log = pd.DataFrame(
        columns=LOG_COLUMNS
    )


# ============================================================
# BUILD SUCCESSFUL VIDEO SET
# ============================================================

successful_videos = set()


if not crawl_log.empty:

    successful_videos = set(

        crawl_log.loc[
            crawl_log["status"] == "success",
            "video_id",
        ]
        .astype(str)

    )


print(
    f"Already successful videos: "
    f"{len(successful_videos)}"
)

print("=" * 70)


# ============================================================
# STATISTICS
# ============================================================

total_success = 0
total_failed = 0
total_skipped = 0
total_new_comments = 0


# ============================================================
# START YOUTUBE
# ============================================================

with YouTube(
    language="vi",
    region="VN"
) as yt:

    # ========================================================
    # LOOP VIDEOS
    # ========================================================

    for index, row in videos.iterrows():

        place_id = str(
            row["place_id"]
        )

        place_name = row[
            "place_name"
        ]

        province_id = row[
            "province_id"
        ]

        province_name = row[
            "province_name"
        ]

        video_id = str(
            row["video_id"]
        )

        video_title = row[
            "title"
        ]

        video_url = row[
            "url"
        ]


        # ====================================================
        # CHECK ALREADY CRAWLED
        # ====================================================

        if video_id in successful_videos:

            print()
            print(
                f"[{index + 1}/{len(videos)}] "
                f"[SKIP]"
            )

            print(
                f"Video ID: {video_id}"
            )

            print(
                "Reason: already crawled successfully"
            )

            total_skipped += 1

            continue


        # ====================================================
        # VIDEO INFORMATION
        # ====================================================

        print()
        print("=" * 70)

        print(
            f"[{index + 1}/{len(videos)}]"
        )

        print(
            f"Place    : {place_name}"
        )

        print(
            f"Province : {province_name}"
        )

        print(
            f"Video    : {video_title}"
        )

        print(
            f"Video ID : {video_id}"
        )

        print(
            f"URL      : {video_url}"
        )

        print("=" * 70)


        # ====================================================
        # CRAWL COMMENTS
        # ====================================================

        try:

            print(
                "Getting comments..."
            )


            comments = yt.comments(

                video_url,

                include_replies=True,

                sort=CommentSort.TOP,

                max_results=MAX_COMMENTS,

            )


            video_comments = []

            comments_found = 0


            # =================================================
            # LOOP COMMENTS
            # =================================================

            for comment in comments:

                comments_found += 1


                # ---------------------------------------------
                # COMMENT KEY
                # ---------------------------------------------

                comment_key = (

                    video_id,

                    str(comment.author),

                    str(comment.text),

                )


                # ---------------------------------------------
                # CHECK DUPLICATE
                # ---------------------------------------------

                if (
                    comment_key
                    in existing_comment_keys
                ):

                    print(
                        f"  [SKIP DUPLICATE]"
                    )

                    print(
                        f"      {comment.author}"
                    )

                    continue


                # ---------------------------------------------
                # CREATE RECORD
                # ---------------------------------------------

                comment_data = {

                    "place_id":
                        place_id,

                    "place_name":
                        place_name,

                    "province_id":
                        province_id,

                    "province_name":
                        province_name,

                    "video_id":
                        video_id,

                    "video_title":
                        video_title,

                    "author":
                        comment.author,

                    "text":
                        comment.text,

                    "likes":
                        comment.like_count,

                    "is_reply":
                        comment.is_reply,

                    "crawled_at":
                        datetime.now().isoformat(),

                }


                video_comments.append(
                    comment_data
                )


                existing_comment_keys.add(
                    comment_key
                )


                # ---------------------------------------------
                # PRINT
                # ---------------------------------------------

                print(
                    f"  {comments_found}. "
                    f"{comment.author}"
                )

                print(
                    f"     Text  : "
                    f"{comment.text}"
                )

                print(
                    f"     Likes : "
                    f"{comment.like_count}"
                )

                print(
                    f"     Reply : "
                    f"{comment.is_reply}"
                )


            # =================================================
            # SAVE COMMENTS IMMEDIATELY
            # =================================================

            append_to_csv(

                video_comments,

                COMMENTS_FILE,

                COMMENT_COLUMNS,

            )


            total_new_comments += len(
                video_comments
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

                "video_id":
                    video_id,

                "video_title":
                    video_title,

                "status":
                    "success",

                "comment_count":
                    len(video_comments),

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


            # =================================================
            # MARK SUCCESS
            # =================================================

            successful_videos.add(
                video_id
            )

            total_success += 1


            # =================================================
            # SUMMARY VIDEO
            # =================================================

            print()

            print(
                "✓ VIDEO FINISHED"
            )

            print(
                f"  Comments found : "
                f"{comments_found}"
            )

            print(
                f"  New comments   : "
                f"{len(video_comments)}"
            )


        except Exception as e:

            # =================================================
            # ERROR
            # =================================================

            print()

            print(
                "❌ VIDEO FAILED"
            )

            print(
                f"   Video ID: "
                f"{video_id}"
            )

            print(
                f"   Error: "
                f"{e}"
            )


            # =================================================
            # WRITE FAILED LOG
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

                "video_id":
                    video_id,

                "video_title":
                    video_title,

                "status":
                    "failed",

                "comment_count":
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
# FINAL SUMMARY
# ============================================================

print()
print()
print("=" * 70)
print("YOUTUBE COMMENT CRAWLER FINISHED")
print("=" * 70)

print(
    f"Successful videos : "
    f"{total_success}"
)

print(
    f"Failed videos     : "
    f"{total_failed}"
)

print(
    f"Skipped videos    : "
    f"{total_skipped}"
)

print(
    f"New comments      : "
    f"{total_new_comments}"
)

print()
print(
    f"Comments CSV:"
)

print(
    f"  {COMMENTS_FILE}"
)

print()
print(
    f"Log CSV:"
)

print(
    f"  {LOG_FILE}"
)

print("=" * 70)