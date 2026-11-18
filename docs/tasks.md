# Nhiệm vụ & Định hướng Nghiên cứu Đồ án (Project Tasks & Research Notes)

## 📌 Luận điểm cốt lõi bảo vệ trước Hội đồng (Key Thesis Statement)

> **"Hệ thống Lakehouse thu thập dữ liệu mạng xã hội của chúng em có thể đóng vai trò như một chỉ số dự báo sớm (Leading Indicator) về mức độ hấp dẫn du lịch của các địa phương, giúp dự đoán xu hướng mà không cần chờ tới cuối năm chính quyền công bố số liệu thống kê."**

---

## 1. Bối cảnh & Giá trị khoa học
* **Vấn đề thực tế:** Số liệu thống kê du lịch chính thống từ Tổng cục Thống kê (GSO) và Sở Du lịch các tỉnh thường có độ trễ lớn (thường công bố theo quý, 6 tháng hoặc cuối năm).
* **Giải pháp từ đồ án:** Dữ liệu lớn từ mạng xã hội (Google Maps Reviews, YouTube Videos/Comments) thu thập qua Lakehouse mang tính thời gian thực (near real-time).
* **Mục tiêu nghiên cứu:** Xây dựng mô hình phân tích tương quan giữa:
  - *Chỉ số vi mô (Micro-metrics từ Lakehouse):* Tổng lượt xem YouTube, lượt đánh giá mới Google Maps của từng tỉnh thành.
  - *Chỉ số vĩ mô (Macro-metrics từ Tổng cục Thống kê `note.txt`):* Lượng khách quốc tế thực tế đến các trọng điểm du lịch năm 2017 - 2018.

---

## 2. Danh sách công việc cần làm (Task Checklist)

### Pha 1: Chuẩn hóa & Tối ưu luồng Ingestion (Data Platform)
- [x] Thu thập Master Data địa điểm du lịch từ OSM và 63 tỉnh thành Việt Nam.
- [x] Triển khai Ingestion mạng xã hội (Google Maps Reviews: ~94k, YouTube Videos: ~36k, YouTube Comments: ~275k).
- [ ] **Khắc phục lỗi Ghi kép (Dual-writing):** Tách bạch giữa file historical legacy CSV và Bronze JSONL trên MinIO.
- [ ] Dọn dẹp các file CSV vãng lai ở thư mục gốc `data/`.

### Pha 2: Chuyển giao dữ liệu sang Tầng Silver & Gold (Modeling & Processing)
- [ ] Hỗ trợ đồng nghiệp hoàn thiện dbt staging (`stg_google_maps_reviews`, `stg_youtube_videos`) đọc trực tiếp từ Bronze JSONL.
- [ ] Tích hợp `dim_date` có cờ ngày lễ Việt Nam (`is_vietnam_holiday`).
- [ ] Xây dựng bảng seed đối chứng `seed_gso_tourism_stats` từ dữ liệu `note.txt`.

### Pha 3: Phân tích & Trực quan hóa (Serving & Analytics)
- [ ] Xây dựng bảng Data Mart: `dm_province_tourism_buzz` (tổng hợp views, reviews, ratings theo tỉnh).
- [ ] Vẽ biểu đồ phân tán (Scatter Plot) đo lường hệ số tương quan ($R^2$) giữa "Độ thảo luận mạng xã hội" và "Lượt khách thực tế GSO".
- [ ] Đưa luận điểm "Chỉ số dự báo sớm (Leading Indicator)" lên Slide báo cáo và tóm tắt tiểu luận.
