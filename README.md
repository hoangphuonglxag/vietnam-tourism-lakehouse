# TLCN Ingestion va Bronze

## Pham vi

Pipeline hien tai tap trung vao ingestion va luu tru Bronze append-only:

```text
Reference: provinces -> OSM candidates -> validation -> places
Social:    Google Maps ratings/reviews, YouTube videos/comments
```

Bronze duoc luu tai `data/bronze/`, theo partition:

```text
data/bronze/<dataset>/crawl_date=YYYY-MM-DD/part-<run_id>.jsonl
```

Moi record co metadata nhu `run_id`, `source`, `ingested_at_utc`, `crawler_version` va `record_status`.

## Cau hinh

Cau hinh runtime nam trong `.env`. Docker Compose nap `.env` vao Airflow container.

Sau khi sua `.env`, nap lai environment:

```powershell
docker compose up -d --force-recreate airflow-scheduler airflow-webserver
```

Cac bien gioi han social:

```dotenv
GOOGLE_MAPS_RATINGS_LIMIT=0
GOOGLE_MAPS_REVIEWS_LIMIT=0
YOUTUBE_MAX_PLACES=0
YOUTUBE_MAX_VIDEOS=5
YOUTUBE_MAX_COMMENTS=5
```

`0` nghia la khong gioi han. `TLCN_TEST_MODE` chu yeu ap dung cho luong reference; social duoc gioi han boi cac bien `*_LIMIT` o tren.

De smoke test:

```dotenv
TLCN_TEST_MODE=true
GOOGLE_MAPS_RATINGS_LIMIT=1
GOOGLE_MAPS_REVIEWS_LIMIT=1
YOUTUBE_MAX_PLACES=1
YOUTUBE_MAX_VIDEOS=1
YOUTUBE_MAX_COMMENTS=1
```

## Chay pipeline

Khoi dong service:

```powershell
docker compose config --quiet
docker compose up -d
docker compose ps
```

Mo Airflow tai `http://localhost:8080`. DAG mac dinh co the dang paused.

Chay reference truoc:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags trigger tourism_reference_pipeline
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_reference_pipeline -o table
```

Reference tao/cap nhat `places.csv` va ghi Bronze reference/OSM. Chi chay social sau khi reference thanh cong:

```powershell
docker compose exec -T airflow-scheduler airflow dags unpause tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags trigger tourism_social_ingestion
docker compose exec -T airflow-scheduler airflow dags list-runs -d tourism_social_ingestion -o table
```

Social dang co lich hang tuan trong DAG. Co the trigger thu cong bat ky luc nao.

## Tier khu vuc

`data/reference/region_crawl_policy.csv` luu tier va score theo tinh. Bien chon tier:

```dotenv
TLCN_CRAWL_TIERS=tier_1,tier_2,tier_3
```

Vi du:

```dotenv
TLCN_CRAWL_TIERS=tier_1
```

Policy co the tao lai tu `places.csv`:

```powershell
python -m script.crawl_data.update_region_priority
```

## Dung giua chung va chay lai

Bronze ghi file moi theo `run_id`, khong ghi de partition cu. Checkpoint nam tai:

```text
data/bronze/_state/
```

Metrics nam tai:

```text
data/bronze/_metrics/
```

Neu DAG bi dung giua chung:

- Bronze da ghi thanh cong van con nguyen.
- Record/place da checkpoint `SUCCESS` se duoc bo qua o run sau khi `TLCN_REFRESH_SUCCESS=false`.
- Record dang chay do dang co the chua co checkpoint va se duoc thu lai.
- Run Airflow cu co the hien `failed`, nhung du lieu Bronze da ghi truoc do khong bi xoa.
- Khong xoa `_state` hoac `data/bronze` de resume.

Voi task Google Maps reviews, progress duoc ghi sau moi place. Neu task nhan
SIGTERM khi dung co chu dinh, job gui Discord summary dang `STOPPED` gom so
place da xu ly, success, failed va remaining. Neu bam `Mark Failed` sau khi
process da bi kill, summary co the khong duoc gui; xem metrics JSON de lay so
lieu cuoi cung.

Dung co chu dinh:

```powershell
docker compose stop airflow-scheduler
```

Neu chi muon dung DAG, dung Stop tren Airflow UI. Khi chay lai, trigger mot run moi.

## Limit, skip va run lap

Limit khong danh dau record con lai la `SUCCESS` va khong lam mat record.

Vi du:

```dotenv
GOOGLE_MAPS_RATINGS_LIMIT=10
```

Job loc cac place da thanh cong truoc, sau do lay 10 place chua thanh cong dau tien. Run se xu ly 10 place nay va ket thuc. Run tiep theo se lay 10 place chua thanh cong ke tiep.

Cac truong hop khac:

- Place da thanh cong: bi bo qua o run sau, khong crawl lai khi `TLCN_REFRESH_SUCCESS=false`.
- Place bi gioi han boi `LIMIT`: chua bi skip vinh vien; se duoc xem xet o run tiep theo.
- Place bi loi: ghi loi/checkpoint `FAILED`; run sau co the thu lai.
- Place thieu `place_id`: job danh dau `skipped`, nhung khong co SUCCESS; neu input khong doi thi no co the bi gap lai o run sau.
- YouTube videos gioi han so video moi place bang `YOUTUBE_MAX_VIDEOS`.
- YouTube comments gioi han so comment moi video bang `YOUTUBE_MAX_COMMENTS`.

## Chay nhieu lan

Chay lai voi `TLCN_REFRESH_SUCCESS=false` la cach binh thuong de resume. Cac record da thanh cong duoc loc boi CSV/checkpoint.

Khong dat `TLCN_REFRESH_SUCCESS=true` trong van hanh thuong. Bien nay bat crawl lai ca record da thanh cong va co the tao them quan sat moi trong Bronze.

Bronze la append-only, nen nhieu run co the tao nhieu partition. Day la chu y de giu lich su crawl; downstream can deduplicate theo business key va thoi diem crawl.

## Theo doi

Airflow UI dung de xem state, retry va task log. Metrics JSON xem tai `data/bronze/_metrics/`. Discord nhan thong bao tong ket khi DAG success/failure; chi tiet van nam trong Airflow log va metrics.

Kiem tra nhanh:

```powershell
Get-ChildItem data\bronze -Recurse -Filter *.jsonl
Get-ChildItem data\bronze\_metrics -Filter *.json
Get-ChildItem data\bronze\_state -Filter *.jsonl
docker compose logs airflow-scheduler --tail=100
```

## Airflow UTC

Airflow container dung UTC. Vi du `14:50 UTC` tuong duong `21:50` gio Viet Nam.

## Bao mat

Khong commit `.env`. File nay chua database password, API key va Discord webhook. Neu secret da bi chia se trong chat/log, can rotate sau khi kiem thu.
