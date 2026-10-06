# Nhan dinh du lieu, tien do va dinh huong

**Ngay ghi nhan:** 28/09/2026  
**Pham vi:** Tieu luan chuyen nganh ve lakehouse va phan tich du lieu du lich; dinh huong ke thua cho khoa luan tot nghiep ve machine learning/deep learning.

## 1. Tom tat nhan dinh

Du an da co nen ingestion tu nhieu nguon, danh muc dia diem, luu tru Bronze, checkpoint va metrics. Day la co so tot de trinh bay bai toan data engineering/lakehouse. Tuy nhien, du lieu va cac bang phan tich chua duoc noi thanh mot luong Silver/Gold hoan chinh. DAG dbt/DuckDB/Iceberg hien nen duoc xem la prototype, chua phai san pham phan tich da tich hop voi cac dataset Bronze du lich.

Huong uu tien da chot la bo sung cac bang thong ke chinh thuc theo tinh/nam tu 2020 tro di lam truc phan tich; bo sung thoi tiet theo tinh/thang de tao boi canh lich su. Google Maps du kien duoc giu nhu mot snapshot tham chieu. YouTube va Google review khong la trong tam cua cau hoi nghien cuu chinh. Cac nguon thong ke va thoi tiet nay moi la ke hoach, chua duoc ingest hay kiem chung trong pipeline.

Cac chi tieu bo sung co the mo ta bien dong cua van tai va mot so hoat dong lien quan den du lich, nhung khong tu dong dong nghia voi luot khach du lich den tinh. Chuoi nam 2020-2025 chi co toi da sau moc nam; so lieu 2025 co the la so so bo. Vi vay uu tien thong ke mo ta va so sanh, khong tuyen bo du bao luong khach hay ket luan nhan qua.

## 2. Tinh hinh du lieu

Cac con so duoi day la snapshot cua cac CSV hien co tai workspace vao ngay ghi nhan. So dong la so ban ghi, khong dong nghia voi so quan sat doc lap hay du lieu da duoc xac nhan sach.

| Dataset | Ban ghi | Dia diem/coverage | Nhan xet |
|---|---:|---:|---|
| `data/reference/places.csv` | 7,155 | 7,155 place_id | Danh muc dia diem chinh; co 5,954 ban ghi `valid` va 1,201 ban ghi `review`. |
| `google_maps_ratings.csv` | 7,160 | 7,156 place_id duy nhat | Co lap lai mot so place; can chuan hoa va quyet dinh cach chon snapshot. |
| `google_maps_reviews.csv` | 8 | 1 dia diem | Chua du de phan tich review tren dien rong. |
| `youtube_videos.csv` | 35,874 | 6,937 place_id | Co views, ngay dang va thoi diem crawl; ket qua tim kiem co gioi han so video moi dia diem. |
| `youtube_comments.csv` | 77,952 | 1,192 place_id | Co luong van ban dang ke cho NLP, nhung coverage theo dia diem chua dong deu va chua co nhan cam xuc. |
| Local Bronze JSONL | 15,902 files | Khoang 130.7 MB | Da co partition, metadata ingestion, metrics/state va quarantine trong workspace. |

### 2.1. Pham vi Da Nang

Danh muc hien co **532 dia diem Da Nang**. Theo join bang `place_id`:

- Google Maps ratings co 532 ban ghi cho 532 dia diem; tat ca co crawl status `success`, nhung chi 469 ban ghi co `google_rating` dang so. Can dieu tra 63 rating trong bi trong/khong chuyen duoc thanh so.
- YouTube co 2,547 dong video tai 509/532 dia diem, gom 2,126 `video_id` duy nhat. Moi dia diem co gan nhu dung 5 video, nen so dong video bi anh huong boi gioi han crawler va khong the dung rieng no lam do pho bien.
- YouTube co 22,026 binh luan tai 315/532 dia diem, gom 882 video. Tat ca `video_id` trong tap binh luan Da Nang doi chieu duoc voi danh sach video hien co. Binh luan chua phu 217 dia diem con lai.

Cac so lieu nay cho thay Da Nang kha kha thi de lam pilot, nhung can ghi ro ket qua chi phan anh cac video/binh luan crawler thu thap duoc, khong phai mau dai dien cho moi du khach.

### 2.2. Du lieu thong ke va thoi tiet du kien

Nhung nguon duoi day la huong bo sung da chon, chua phai dataset da co trong workspace. Can tai va audit dinh nghia, don vi, pham vi dia ly, phuong phap tinh va tinh trang so lieu truoc khi dua vao phan tich.

| Nguon/nhom chi tieu | Tan suat va pham vi du kien | Cach su dung va dieu kien |
|---|---|---|
| Luot hanh khach van chuyen va hanh khach luan chuyen theo dia phuong | Nam, tu 2020 tro di | Mo ta hoat dong van tai. Phai ghi dung dinh nghia va don vi; khong goi la luot khach du lich den tinh. |
| Doanh thu du lich lu hanh theo dia phuong | Nam, neu bang nguon co cot dia phuong | Chi tieu lien quan den hoat dong du lich; neu la gia hien hanh thi khong dien giai nhu doanh thu da loai tru lam phat. |
| Chi tieu binh quan khach du lich noi dia theo khoan chi, phuong tien hoac muc dich | Tan suat va cap dia ly can xac minh theo tung bang | Khong mac dinh rang co the join theo tinh/nam. Giu grain goc va pham vi khao sat neu bang khong co khoa dia phuong. |
| Thoi tiet theo tinh/thang | Thang, tu 2020 tro di neu nguon dap ung | Tong hop chi tieu mua/nhiet do de so sanh boi canh lich su. Neu du lieu goc theo tram, can ghi ro quy tac tong hop tram thanh tinh. |

Thoi tiet thang cua nam truoc co the dung de doi chieu lich su va dat canh bao theo mua, nhung khong phai du bao cho thang nam nay. Du bao can nguon forecast rieng, thoi han du bao va do bat dinh ro rang. Neu chi tieu du lich chi co theo nam, khong suy ra quan he du lich-thoi tiet theo thang tu bang nam.

## 3. Tien do he thong

### Da co trong repo

- Reference DAG: thu thap tinh/thanh va candidate places, kiem tra chat luong, xac thuc khong gian, phan loai va tao danh muc `places`.
- Social DAG: backfill CSV lich su, crawl Google Maps ratings/reviews, YouTube videos/comments.
- BronzeWriter ghi JSONL append-only o local va MinIO; them metadata ingestion va dua record khong dat quy tac vao quarantine.
- Checkpoint theo item, metrics theo run, Airflow retry/log va Discord alerts.
- Cac container PostgreSQL, MinIO, Lakekeeper, Airflow scheduler va webserver dang `Up` tai thoi diem kiem tra. Trang thai service `Up` khong thay the viec kiem thu thanh cong tung DAG.
- Job YouTube comments da co buoc nang schema CSV cu 11 cot sang schema hien hanh 13 cot. Ban CSV hien tai da duoc doc va kiem tra lai trong moi truong Airflow.
- Metrics hien ghi JSON theo run vao `data/bronze/_metrics` va dong thoi in ra log; checkpoint trong `_state` duoc crawler dung de resume, quarantine giu record khong dat quality rules. Metrics co the doi backend giam file local, nhung state va quarantine khong the xoa chi vi thay dashboard.

### Chua hoan tat / can xac nhan

- Chua co Silver models hoan chinh cho ratings, videos, comments: chuan hoa kieu, province IDs, timestamp/ngon ngu, khoa va dedup.
- Chua co Gold tables cho phan tich theo dia diem/tinh.
- `tourism_lakehouse_test` co cac task `dbt_run`, `write_iceberg`, `validate_iceberg`, nhung model dbt duy nhat hien doc `s3://lakehouse/raw/travel_reviews/*.parquet`. Path nay khong trung voi prefix Bronze chinh `s3://lakehouse/bronze/...`; do do chua co bang chung rang luong dbt -> Iceberg dang xu ly cac dataset du lich hien tai.
- Chua co tap nhan binh luan duoc kiem duyet va chua co ket qua benchmark mo hinh NLP.
- Chua co cac CSV thong ke chinh thuc va du lieu thoi tiet theo tinh/thang trong Bronze/Silver/Gold; cac so lieu va URL can duoc tai, kiem tra dinh nghia va audit coverage.
- DAG dbt/DuckDB/Iceberg van la prototype: model hien tai doc `s3://lakehouse/raw/travel_reviews/*.parquet`, khong phai Bronze prefix `s3://lakehouse/bronze/...`. Iceberg writer dang append, nen can xu ly idempotency/dedup truoc khi cho phep chay lai luong cho cac nguon moi.

## 4. Gioi han va rui ro

1. **Khong co so lieu luong khach:** views, comments va Google review count la tin hieu/hoat dong tren nen tang, khong phai so luot khach den tinh.
2. **Time series social khong day du:** hau het place chi co mot snapshot rating. `published_at` la ngay dang video, khong phai chuoi snapshot views. `comment_created_at` co gia tri dang tuong doi nhu "2 tuan truoc", khong nen dung lam ngay review chinh xac. Cac bang thong ke nam moi neu duoc ingest se bo sung chuoi nam cho mot so chi tieu, khong bien du lieu social thanh time series.
3. **Coverage khong dong deu:** Da Nang co comment tai 315/532 dia diem. Crawl gioi han so video moi dia diem, trong khi comment crawl co the that bai hoac video khong bat binh luan.
4. **Sampling bias:** YouTube search, truy van, ngon ngu, gioi han crawler va video duoc chon anh huong ket qua. Xep hang chi nen dien dat la "trong tap du lieu da thu thap".
5. **Thieu nhan NLP:** 77,952 comment raw khong tu dong tro thanh du lieu supervised. Can gan nhan mau va bao cao quy trinh/ket qua danh gia.
6. **Du lieu review Google qua mong:** chi co 8 review text tren 1 dia diem, khong phu hop de lam bai toan NLP review Google trong pham vi hien tai.
7. **Province ID va lich su dia gioi:** can chuan hoa ID tinh va xac dinh dung ban danh muc khi join; khong gop du lieu chi dua vao ten tinh.
8. **So nam quan sat it:** giai doan 2020-2025 co toi da sau diem nam; 2025 co the la so so bo. COVID-19 anh huong manh cac nam dau, can danh dau khi so sanh va khong ngoai suy xu huong dai han.
9. **Khac grain va dinh nghia:** van tai, doanh thu, chi tieu va thoi tiet khong chac cung cap dia ly/tan suat. Khong join neu khong co khoa va grain tuong thich; chi tieu gia hien hanh can duoc dien giai dung, khong tu coi la gia thuc.
10. **Thoi tiet khong phai du bao:** gia tri thang cua nam truoc chi la quan sat lich su. Nhan dinh thang toi can du lieu forecast rieng, khong duoc suy ra tu mot thang lich su.
11. **Thay doi dia gioi hanh chinh:** can ghi version danh muc tinh va quy tac mapping qua cac nam, dac biet khi pham vi dia gioi thay doi; khong gop ten tinh bang tay.

## 5. Dinh huong cho tieu luan chuyen nganh

### Muc tieu

Xay dung va danh gia nen tang lakehouse co the truy vet, bo sung CSV thong ke chinh thuc theo dia phuong tu 2020 tro di va thoi tiet theo tinh/thang. Dung cac chi tieu nay de mo ta/so sanh hoat dong van tai va mot so khia canh lien quan den du lich, khong nhan chung la luong khach den tinh. Google Maps du kien giu mot snapshot tham chieu; YouTube la nhanh phu, khong phai trong tam phan tich.

### Cau hoi phan tich de xuat

> Trong giai doan 2020-2025, cac chi tieu thong ke duoc chon ve van tai va hoat dong lien quan den du lich bien dong ra sao giua cac dia phuong? Du lieu thoi tiet theo thang cung cap boi canh lich su gi cho viec mo ta cac dia phuong?

Cau hoi va ket luan phai dung ten, dinh nghia va cap dia ly cua tung chi tieu. Khong dien giai chi tieu hanh khach van chuyen/luan chuyen thanh so luot khach du lich; khong ket luan thoi tiet gay ra bien dong doanh thu/van tai neu chi co phan tich mo ta hoac tuong quan.

### Ky thuat va dau ra

- **Nguon thong ke:** luu CSV goc, URL/ten bang, ngay tai, don vi, dinh nghia, pham vi dia ly, nam tham chieu va co danh dau so so bo. Khong tron cac chi tieu khac dinh nghia/grain vao mot chi so tong hop tuy tien.
- **Thoi tiet:** Bronze luu ban ghi va metadata nguon; Silver chuan hoa province key, nam/thang quan sat, don vi va cach tong hop tram. Gold thoi tiet co grain `province_id + year_month`; bang thong ke nam giu grain va dinh nghia rieng.
- **Bronze -> Silver -> Gold:** moi nguon co luong/doc lap; Silver xu ly kieu du lieu, province mapping, missingness va dedup; Gold chi join bang co khoa/grain tuong thich. Them test uniqueness, not-null, accepted values, coverage va so dong sau join.
- **Thoi tiet va du lich:** so sanh mo ta cac mau hinh lich su. Neu chi tieu du lich la nam thi tong hop thoi tiet ve nam cho phan tich nam; khong dung thoi tiet thang de tao ket luan thang khi khong co chi tieu du lich theo thang.
- **Google Maps:** neu chay them, luu mot snapshot co `snapshot_at` va coverage; dung lam tham chieu cat ngang, khong coi la time series hay mau review NLP day du.
- **YouTube (phu):** giu du lieu va pipeline neu co ich cho demo lakehouse, nhung tach khoi cau hoi chinh. Neu sau nay mo rong NLP, can tap nhan va danh gia rieng; ket qua chi dai dien cho tap crawl.

Khong dat muc tieu du bao luong khach, du bao thoi tiet tu so lieu lich su, hay khang dinh quan he nhan qua. So nam 2020-2025 qua it de lam co so vung cho mo hinh du bao time series.

## 6. Ke hoach uu tien tiep theo

1. **Kiem chung nguon va scope:** tai cac CSV thong ke da chon tu 2020 tro di; ghi ten bang, URL, ngay tai, dinh nghia, don vi, cap dia ly va danh dau nam 2025 so bo neu dung.
2. **Audit grain va coverage:** thong ke nam/tinh, missingness, duplicate, province keys va thay doi dia gioi; xac minh bang chi tieu chi tieu co cap tinh hay chi co cap toan quoc.
3. **Chon nguon thoi tiet:** uu tien du lieu quan trac lich su theo thang, xac dinh tram/dai dien tinh va quy tac tong hop; tach du lieu quan trac khoi API du bao.
4. **Them ingestion rieng cho tung nguon:** CSV thong ke co the nap mot lan/backfill; API thoi tiet can retry, rate limit va secrets neu co. Them schema/quality contract va bao toan source fields.
5. **Dam bao chay lai an toan:** Bronze append-only can co run/source IDs va dedup/idempotency o Silver hoac co che nap; khong de chay lai cung file lam nhan ban Gold/Iceberg.
6. **Hoan thien Silver/Gold:** chuan hoa province IDs va version dia gioi; giu grain nam va thang rieng; test uniqueness, not-null, accepted values, coverage va join row counts.
7. **Snapshot Google Maps (phu):** neu chay, ghi snapshot timestamp va coverage; danh dau la tham chieu, khong crawl lap lai neu khong co muc dich refresh.
8. **Bao cao ket qua va gioi han:** phan biet hanh khach van tai voi khach du lich, so lieu gia hien hanh voi gia thuc, so lieu so bo voi chinh thuc; khong suy dien nhan qua hay du bao tu chuoi ngan.

## 7. Huong ke thua cho khoa luan tot nghiep

Khoa luan co the ke thua pipeline va Silver/Gold. Du lieu thong ke nam 2020-2025 va thoi tiet thang phu hop hon cho mo ta/phan tich du lieu, chua du dai de lam co so du bao time series hoac deep learning dang tin cay. Neu chon tiep huong DL, co the tach thanh bai toan NLP binh luan YouTube: xay tap nhan co quy trinh, so sanh baseline voi PhoBERT/XLM-R, chia train/test theo `video_id` va phan tich loi. Day la huong nghien cuu rieng, khong tu dong nam trong scope phan tich thong ke chinh.

Mo rong sang nhieu tinh, nhieu nen tang hoac time series chi nen lam khi co du lieu bo sung va co the kiem chung coverage. Khong can dat muc tieu so sanh voi luong khach thuc te neu chua co nguon thong ke va khoa lien ket dang tin cay.

## 8. Ket luan

Du an da co ingestion va Bronze, nhung can hoan thien Silver/Gold va noi dung dbt/Iceberg voi Bronze hien tai. Scope uu tien la bo sung thong ke chinh thuc theo tinh/nam tu 2020 va thoi tiet tinh/thang de mo ta boi canh; Google Maps giu snapshot tham chieu, YouTube la nhanh phu. Cac chi tieu nay khong thay the so lieu luot khach du lich. Truoc khi ket luan, can kiem chung dinh nghia, grain, dia gioi, coverage va tinh lap an toan cua pipeline.
