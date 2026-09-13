# Vietnam Tourism Lakehouse

Pipeline thu thap va luu tru du lieu du lich Viet Nam theo mo hinh lakehouse.
Project su dung Airflow de dieu phoi ingestion, MinIO lam object storage tuong
thich S3, Lakekeeper lam Iceberg REST Catalog va PostgreSQL lam metadata store.

## Project lam gi?

Pipeline gom hai luong chinh:

```text
Reference pipeline
provinces -> candidate places -> validation -> classification -> places

Social pipeline
places -> Google Maps ratings/reviews
       -> YouTube videos/comments
```

Du lieu raw va ket qua ingestion duoc ghi vao Bronze theo dang JSONL,
append-only. Moi partition co dang:

```text
data/bronze/<dataset>/crawl_date=YYYY-MM-DD/part-<run_id>.jsonl
```

Dong thoi, `BronzeWriter` ghi cung object vao bucket MinIO:

```text
s3://lakehouse/bronze/<dataset>/crawl_date=YYYY-MM-DD/...
```

Moi record co metadata ingestion nhu `run_id`, `source`, `ingested_at_utc`,
`crawler_version` va `record_status`.

## Cau truc chinh

```text
airflow/dags/                  Airflow DAGs
script/crawl_data/             crawler, validation va BronzeWriter
data/reference/                dimension va policy crawl
data/historical/               du lieu CSV lich su de backfill
data/bronze/                   Bronze local, checkpoint va metrics
iceberg/                       cac module Iceberg/Lakehouse
tourism_dbt/                   dbt models
docker-compose.yml             PostgreSQL, MinIO, Lakekeeper, Airflow
```

## Yeu cau

- Docker Desktop voi Docker Compose
- Git
- API key/cau hinh crawler neu chay Google Maps hoac YouTube

## Cai dat va cau hinh

Clone project va tao file `.env` tu file mau:

```powershell
Copy-Item .env.example .env
```

Kiem tra va dieu chinh cac gia tri trong `.env`, dac biet la credential
MinIO/PostgreSQL va cac gioi han crawler. Khong commit `.env` vi file co the
chua password, API key va Discord webhook.

## Chay nhanh

Mo PowerShell tai thu muc project:

```powershell
docker compose config --quiet
docker compose up -d
docker compose ps
```

Mo Airflow tai [http://localhost:8080](http://localhost:8080). Tai khoan mac
dinh trong `.env.example` la `airflow` / `airflow`.

### 1. Chay reference pipeline

Reference pipeline tao hoac cap nhat danh sach dia diem. Can chay thanh cong
truoc khi crawl social:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags trigger tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_reference_pipeline -o table
```

### 2. Chay social ingestion

Sau khi reference pipeline thanh cong:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags trigger tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_social_ingestion -o table
```

Social DAG gom backfill du lieu lich su, Google Maps ratings/reviews va
YouTube videos/comments. DAG nay duoc lap lich hang tuan luc `03:00 UTC` thu
Hai, nhung co the trigger thu cong.

## Che do test va gioi han

De smoke test voi pham vi nho, dat trong `.env`:

```dotenv
TLCN_TEST_MODE=true
GOOGLE_MAPS_RATINGS_LIMIT=1
GOOGLE_MAPS_REVIEWS_LIMIT=1
YOUTUBE_MAX_PLACES=1
YOUTUBE_MAX_VIDEOS=1
YOUTUBE_MAX_COMMENTS=1
```

Khi chay du lieu lon, co the dat gioi han ve `0` theo quy uoc cua tung job.
`TLCN_CRAWL_TIERS` dung de chon nhom khu vuc, vi du:

```dotenv
TLCN_CRAWL_TIERS=tier_1,tier_2,tier_3
```

Sau khi sua `.env`, nap lai environment cho Airflow:

```powershell
docker compose up -d --force-recreate airflow-scheduler airflow-webserver
```

## Kiem tra ket qua

Du lieu local, metrics va checkpoint nam tai:

```powershell
Get-ChildItem data\bronze -Recurse -Filter *.jsonl
Get-ChildItem data\bronze\_metrics -Filter *.json
Get-ChildItem data\bronze\_state -Filter *.jsonl
docker compose logs airflow-scheduler --tail=100
```

Bronze la append-only: moi lan chay tao partition moi theo `run_id`, khong ghi
de partition cu. Checkpoint nam trong `data/bronze/_state/` giup bo qua item da
thanh cong khi chay lai. Khong xoa `data/bronze` hoac `_state` neu muon resume.

## Chay module truc tiep

Co the chay mot so module tu PowerShell sau khi cai dependencies Python:

```powershell
python -m script.crawl_data.backfill_historical
python -m script.crawl_data.update_region_priority
python -m script.crawl_data.quality_gate places
```

Trong van hanh binh thuong, nen chay qua Airflow de co retry, checkpoint,
metrics va task log tap trung.

## Tai lieu lien quan

- [RUNBOOK_INGESTION_BRONZE.txt](RUNBOOK_INGESTION_BRONZE.txt): huong dan van hanh, resume, retry va xu ly loi.
- [data_contract.md](data_contract.md): contract cua cac dataset.
- [tourism_dbt/README.md](tourism_dbt/README.md): dbt models.

## Dung he thong

```powershell
docker compose stop
```

Dung `docker compose down` neu can xoa container nhung van giu volume. Khong
dung `docker compose down -v` neu muon giu du lieu PostgreSQL va MinIO.