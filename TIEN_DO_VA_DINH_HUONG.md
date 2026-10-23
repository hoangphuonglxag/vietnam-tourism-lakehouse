script/
├── alerts/
│   ├── __init__.py
│   └── discord.py              # Gửi thông báo Discord dùng chung
│
├── crawl_data/
│   ├── __init__.py
│   ├── config.py               # Cấu hình crawl, storage, đường dẫn
│   │
│   ├── reference/              # Xây dựng master data
│   │   ├── crawl_province.py
│   │   ├── crawl_candidate_places_raw.py
│   │   ├── validate_places.py
│   │   ├── classify_places.py
│   │   └── publish_master.py
│   │
│   ├── crawlers/               # Chỉ lấy dữ liệu từ nguồn ngoài
│   │   ├── __init__.py
│   │   ├── crawl_google_rating.py
│   │   ├── crawl_google_reviews.py
│   │   ├── crawl_youtube_comments.py
│   │   └── crawl_youtube_videos.py
│   │
│   ├── jobs/                   # Điều phối từng loại ingestion
│   │   ├── __init__.py
│   │   ├── job_google_maps_ratings.py
│   │   ├── job_google_maps_reviews.py
│   │   ├── job_youtube_comments.py
│   │   └── job_youtube_videos.py
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── ingestion.py        # Validate, metadata, checkpoint, điều phối ghi
│   │   ├── storage.py          # Đọc/ghi object storage
│   │   ├── dedup.py            # Chống trùng
│   │   ├── retry.py            # Retry lỗi tạm thời
│   │   └── quality_gate.py     # Đánh giá chất lượng dữ liệu
│   │
│   └── metrics/
│       ├── __init__.py
│       └── ingestion.py        # Metrics theo từng lần chạy
│