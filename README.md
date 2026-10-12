# Vietnam Tourism Lakehouse

Du an thu thap, luu tru va chuan bi du lieu du lich tu nguon tham chieu va mang xa hoi. Muc tieu hoc thuat la xay dung nen tang lakehouse co the truy vet du lieu ingestion, sau do mo rong thanh cac bang phan tich va bai toan machine learning/deep learning.

## Pham vi va trang thai

- Reference pipeline thu thap ranh gioi tinh va dia diem, kiem tra khong gian, phan loai va tao danh muc dia diem.
- Social ingestion thu thap Google Maps ratings/reviews va YouTube videos/comments theo `place_id`.
- Bronze ingestion dang duoc trien khai: ghi JSONL append-only o local va MinIO, kem metadata, metrics, checkpoint va quarantine.
- Silver/Gold cho cac dataset du lich chua duoc noi thanh luong phan tich hoan chinh. DAG `tourism_lakehouse_test` la prototype dbt -> DuckDB -> Iceberg; model dbt hien doc `s3://lakehouse/raw/travel_reviews/*.parquet`, chua doc truc tiep cac partition Bronze du lich.

Chi tiet nhan dinh du lieu, tien do, rui ro va ke hoach tiep theo nam trong [TIEN_DO_VA_DINH_HUONG.md](TIEN_DO_VA_DINH_HUONG.md).

## Kien truc hien tai

```text
Province boundaries / OSM
       -> reference pipeline -> validated places
                                  |
Google Maps ratings/reviews <--------+
YouTube videos -> YouTube comments <-+
       -> Airflow jobs -> JSONL Bronze (local + MinIO)
       -> checkpoint, metrics, quarantine

dbt -> DuckDB -> Iceberg/Lakekeeper: prototype, chua noi voi Bronze du lich
```

Moi partition Bronze co dang:

```text
data/bronze/<dataset>/crawl_date=YYYY-MM-DD/part-<run_id>.jsonl
```

Bronze object duoc dong bo len MinIO theo prefix `s3://lakehouse/bronze/`. Metadata ingestion gom `run_id`, `source`, `source_id`, `ingested_at_utc`, `pipeline_version`, `crawler_version`, `attempt` va `record_status`. Ban ghi khong dat quality rules duoc dua vao `data/bronze/quarantine/`.

## Cau truc thu muc

```text
airflow/dags/                  Airflow DAGs cho reference, social va lakehouse test
script/crawl_data/             crawler, validation, quality gate va BronzeWriter
data/reference/                danh muc dia diem, taxonomy va chinh sach crawl
data/historical/               CSV lich su va output tuong thich crawler
data/bronze/                   JSONL Bronze, checkpoint, metrics va quarantine
iceberg/                       PyIceberg writer va validator
tourism_dbt/                   dbt project
docker-compose.yml             Airflow, PostgreSQL, MinIO va Lakekeeper
```

## Yeu cau

- Docker Desktop va Docker Compose
- Git
- Cac API key/credential chi khi crawler hoac dich vu tuong ung yeu cau

## Cai dat

Tai thu muc goc project, tao `.env` tu file mau va thay cac gia tri placeholder bang gia tri rieng:

```powershell
Copy-Item .env.example .env
```

Khong commit `.env`; file co the chua credential, API key hoac Discord webhook. Kiem tra cau hinh va khoi dong cac service:

```powershell
docker compose config --quiet
docker compose up -d
docker compose ps
```

Airflow UI: [http://localhost:8080](http://localhost:8080). MinIO Console: [http://localhost:9001](http://localhost:9001). Thong tin dang nhap duoc cau hinh trong `.env`.

## Chay pipeline

Reference pipeline can chay truoc khi social crawl neu danh muc dia diem chua duoc tao/cap nhat:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags trigger tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_reference_pipeline -o table
```

Sau khi reference pipeline thanh cong, chay social ingestion:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags trigger tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_social_ingestion -o table
```

Social DAG lap crawl plan tu danh muc place va freshness, sau do chi crawl cac dataset/item thieu hoac cu. DAG duoc len lich luc `03:00 UTC` moi thu Hai; co the trigger thu cong voi province/category/dataset cu the. DAG social khong chay lai reference validation/classification va khong backfill CSV lich su mac dinh.

Xem truoc ke hoach cho khach san Da Nang, khong crawl:

```powershell
docker compose exec -T airflow-scheduler airflow dags trigger tourism_social_ingestion --conf '{"province":"Đà Nẵng","category":"hotel","datasets":["ratings","reviews","comments"],"dry_run":true}'
```

Neu plan dung, bo `dry_run` hoac dat `false` de crawl. `datasets` chap nhan `ratings`, `reviews`, `videos`, `comments`; `freshness_days` co the la so ngay chung hoac map theo dataset. `force_refresh=true` cho phep crawl lai item da `SUCCESS`, bo qua freshness. YouTube comments chi crawl video chua `SUCCESS` theo crawl log/checkpoint, bat ke freshness; neu videos cung duoc cap nhat trong run, comments se lay them video moi sau buoc videos.

Scope co the ket hop:

```json
{"province":"Đà Nẵng","category":"artwork","datasets":["videos"],"dry_run":true}
{"provinces":["Đà Nẵng","Huế"],"datasets":["comments"],"dry_run":true}
{"place_ids":["OSM_node_123","OSM_way_456"],"datasets":["ratings","reviews"],"dry_run":true}
{"provinces":["Đà Nẵng","Huế"],"category":"artwork","place_ids":["OSM_node_123"],"datasets":["videos","comments"],"dry_run":true}
```

Dung `place_ids` dung chinh xac ID trong `data/reference/places.csv`; cac bo loc tinh/category/place la giao cua nhau. Planner mac dinh chi chon item chua co crawl thanh cong hoac qua han freshness (30 ngay); `dry_run` bat buoc khong co crawler nao duoc goi. Sau khi kiem tra plan, trigger lai cung JSON nhung bo `dry_run`.

Reference taxonomy can duoc refresh mot lan de them mapping `tourism=hotel`. Neu planner bao taxonomy chua co category `hotel`, chay `tourism_reference_pipeline` co chu dich mot lan truoc. Cac lan trigger social sau khong chay validate/classify.

### Chuyen CSV crawl local vao Bronze/MinIO

`tourism_ingestion_pipeline` van giu task `backfill_historical_to_bronze`, nhung trigger ca DAG se chay ca reference va cac crawler. De chi chuyen file da crawl, copy CSV cua team vao `data/historical/` tren may coordinator (dung ten file trong `script/crawl_data/reference/backfill_historical.py`), sau do chay rieng:

```powershell
docker compose exec -T airflow-scheduler python -m script.crawl_data.reference.backfill_historical
```

Lenh nay doc cac CSV historical co mat, ghi Bronze len MinIO, va bo qua file da co marker trong `data/bronze/_backfill/`. Moi may local khong tu dong chia se file hoac MinIO voi may khac; can gom file ve coordinator truoc.

## Chay thu gioi han

Trong `.env`, co the gioi han pham vi smoke test bang cac bien duoc crawler su dung:

```dotenv
TLCN_TEST_MODE=true
GOOGLE_MAPS_RATINGS_LIMIT=1
GOOGLE_MAPS_REVIEWS_LIMIT=1
YOUTUBE_MAX_PLACES=1
YOUTUBE_VIDEOS_PER_PLACE=1
YOUTUBE_COMMENTS_PER_VIDEO=1
```

`YOUTUBE_COMMENT_VIDEO_LIMIT` gioi han so video xu ly trong job comments; `TLCN_CRAWL_TIERS` loc nhom tinh theo tier. Hanh vi limit co the khac nhau theo tung job, hay xem `.env.example` va `script/crawl_data/jobs/` truoc khi chay full. Sau khi sua `.env`, nap lai env cho Airflow:

```powershell
docker compose up -d --force-recreate airflow-scheduler airflow-webserver
```

## Kiem tra du lieu

```powershell
Get-ChildItem data\bronze -Recurse -Filter *.jsonl
Get-ChildItem data\bronze\_metrics -Filter *.json
Get-ChildItem data\bronze\_runs -Filter *.json
Get-ChildItem data\bronze\_plans -Filter *.json
Get-ChildItem data\bronze\_state -Filter *.jsonl
docker compose logs airflow-scheduler --tail=100
```

Bronze la append-only; moi run tao object moi va khong ghi de partition cu. Checkpoint trong `data/bronze/_state/` cho phep bo qua item da thanh cong khi chay lai. Run manifests nam trong `data/bronze/_runs/`; crawl plan va ly do bo qua nam trong `data/bronze/_plans/`. Khong xoa `data/bronze` hoac `_state` neu can giu du lieu va resume state.

## Lakehouse va phan tich

DAG `tourism_lakehouse_test` gom `dbt_run`, `write_iceberg` va `validate_iceberg`. Day la luong thu nghiem rieng, khong can chay khi chi muon ingest Bronze. Truoc khi dung cho phan tich du lich, can noi dbt voi Bronze hien tai, xay Silver models cho ratings/videos/comments, sau do tao Gold aggregates va kiem thu join/quality.

## Tai lieu

- [TIEN_DO_VA_DINH_HUONG.md](TIEN_DO_VA_DINH_HUONG.md): nhan dinh du lieu va ke hoach tieu luan/khoa luan.
- [data_contract.md](data_contract.md): schema va quy uoc dataset.
- [RUNBOOK_INGESTION_BRONZE.txt](RUNBOOK_INGESTION_BRONZE.txt): van hanh, checkpoint, retry va troubleshooting.
- [tourism_dbt/README.md](tourism_dbt/README.md): huong dan dbt.

## Dung dich vu

```powershell
docker compose stop
```

`docker compose down` xoa containers nhung giu volumes. Tranh `docker compose down -v` neu can giu PostgreSQL va MinIO volumes.