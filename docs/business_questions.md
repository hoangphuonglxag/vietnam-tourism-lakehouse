# Vietnam Tourism Lakehouse - Business Questions & Analytical Framework

**Tài liệu:** Đề xuất Câu hỏi Nghiệp vụ & Khung phân tích (Business Questions)  
**Dành cho:** Đồ án / Tiểu luận chuyên ngành Kỹ thuật Dữ liệu & Hệ thống Lakehouse  
**Mục tiêu:** Định hình rõ đầu ra của hệ thống (KPIs, Dashboard, Báo cáo & Tiền đề cho AI/ML) để chứng minh giá trị thực tế của nền tảng Data Lakehouse trước Hội đồng phản biện.

---

## 1. Tại sao cần xác định Câu hỏi Nghiệp vụ trước?

Một hệ sinh thái Data Lakehouse dù hiện đại đến đâu (Airflow, MinIO, Iceberg, dbt) cũng chỉ là "kho chứa tốn kém" nếu không giải quyết được các bài toán thực tế.

Trong bài toán **Du lịch Việt Nam**, việc kết hợp giữa **Dữ liệu địa lý (OSM)**, **Dữ liệu trải nghiệm thực tế (Google Maps Reviews)** và **Dữ liệu truyền thông số (YouTube Engagement)** mở ra 4 nhóm bài toán nghiệp vụ kinh điển mà Hội đồng chuyên ngành đánh giá rất cao:

```text
1. Quản lý chất lượng & Uy tín điểm đến (Service Quality & Reputation)
2. Sức hút truyền thông & Độ lan tỏa số (Media Buzz & Viral Potential)
3. Phân tích tính mùa vụ & Sự kiện (Seasonality & Holiday Impact)
4. Phân tích phản hồi khách hàng (Customer Feedback & Text Analytics)
```

---

## 2. Danh mục các Câu hỏi Nghiệp vụ chi tiết (Core Business Questions)

---

### NHÓM 1: Quản trị Chất lượng & Đánh giá Danh tiếng (Reputation & Service Quality)

#### ❓ Câu hỏi 1: Tỉnh/thành phố và vùng miền nào có mức độ hài lòng du lịch cao nhất cả nước?
* **Ý nghĩa nghiệp vụ:** Giúp cơ quan quản lý du lịch hoặc các công ty lữ hành xếp hạng năng lực phục vụ của từng địa phương, xác định địa phương nào đang làm du lịch tốt, nơi nào dịch vụ đang có dấu hiệu đi xuống.
* **Chỉ số đo lường (KPIs):**
  - `Average Google Rating`: Điểm đánh giá trung bình theo tỉnh/vùng.
  - `Review Volume`: Tổng dung lượng đánh giá (phản ánh lượng khách thực tế).
  - `High-Quality Place Ratio`: Tỷ lệ địa điểm đạt từ 4.5 sao trở lên.
* **Bảng tham gia (DW/Mart):** `dim_provinces`, `dim_places`, `fact_place_reviews` (hoặc `dm_province_tourism_buzz`).
* **Trực quan hóa đề xuất:** Bản đồ nhiệt Việt Nam (Choropleth Map) hiển thị màu sắc theo điểm số đánh giá trung bình, kèm biểu đồ cột xếp hạng Top 10 tỉnh cao nhất / thấp nhất.

---

#### ❓ Câu hỏi 2: Phân khúc dịch vụ nào (Khách sạn, Ẩm thực, Di tích, Khu vui chơi) thường nhận nhiều phàn nàn nhất?
* **Ý nghĩa nghiệp vụ:** Giúp trả lời câu hỏi cốt lõi: *"Du khách đến tỉnh X thường thất vọng về điều gì nhất? Có phải do nhà hàng chặt chém hay phòng nghỉ xuống cấp?"*.
* **Chỉ số đo lường (KPIs):**
  - `Category Avg Rating`: Điểm trung bình của từng nhóm `category`.
  - `Negative Review Ratio`: Tỷ lệ review 1 - 2 sao trên tổng số review của phân khúc.
* **Bảng tham gia (DW/Mart):** `dim_places`, `fact_place_reviews`.
* **Trực quan hóa đề xuất:** Biểu đồ Radar (Spider Chart) hoặc Grouped Bar Chart so sánh điểm số giữa các danh mục của từng tỉnh trọng điểm.

---

### NHÓM 2: Sức hút Truyền thông & Mức độ Lan tỏa (Social Media & Tourism Buzz)

#### ❓ Câu hỏi 3: Có sự chênh lệch (gap) giữa "Độ nổi tiếng trên mạng xã hội" và "Chất lượng trải nghiệm thực tế" không?
* **Ý nghĩa nghiệp vụ:** 
  - Tìm ra các **"Hidden Gems" (Ngọc ẩn):** Những địa điểm có chất lượng dịch vụ cực cao (rating > 4.7 sao) nhưng rất ít xuất hiện trên truyền thông YouTube. Đây là cơ hội vàng để quảng bá xúc tiến du lịch.
  - Cảnh báo các **"Bẫy truyền thông" (Overhyped / Tourist Traps):** Những nơi xuất hiện dày đặc trên vlog/video (hàng triệu view) nhưng điểm trải nghiệm thực tế trên Google Maps lại rất thấp.
* **Chỉ số đo lường (KPIs):**
  - `Social Buzz Index`: Tổng lượt xem (views) + bình luận video YouTube về địa điểm.
  - `Satisfaction Index`: Điểm Google Rating trung bình.
* **Bảng tham gia (DW/Mart):** `dim_places`, `fact_place_reviews`, `fact_youtube_engagement`.
* **Trực quan hóa đề xuất:** Biểu đồ phân tán 4 góc phần tư (Scatter Plot 4-quadrant):
  - Trục X: Lượt xem YouTube (Mức độ truyền thông).
  - Trục Y: Điểm đánh giá Google (Mức độ hài lòng).

---

#### ❓ Câu hỏi 4: Những nhà sáng tạo nội dung (YouTubers / Kênh du lịch) nào có tầm ảnh hưởng lớn nhất đối với du lịch từng vùng?
* **Ý nghĩa nghiệp vụ:** Doanh nghiệp và địa phương có thể chọn lọc đúng đối tác (KOLs/KOCs) có sức lan tỏa thực chất để thực hiện các chiến dịch truyền thông quảng bá điểm đến.
* **Chỉ số đo lường (KPIs):**
  - `Total Videos Produced`: Số video về địa điểm du lịch của kênh.
  - `Total Views & Likes`: Tổng lượt tương tác thu hút được.
  - `Engagement Rate`: Lượt bình luận trên lượt xem (`comments / views`).
* **Bảng tham gia (DW/Mart):** `dim_places`, `dim_provinces`, `fact_youtube_engagement`.
* **Trực quan hóa đề xuất:** Treemap hoặc Bảng xếp hạng Top Kênh du lịch theo từng vùng miền.

---

### NHÓM 3: Tính Mùa vụ & Tác động của Dịp Lễ Tết (Seasonality & Peak Travel)

#### ❓ Câu hỏi 5: Dịch vụ du lịch có bị giảm chất lượng vào các mùa cao điểm (Tết Âm lịch, 30/4 - 1/5) do quá tải không?
* **Ý nghĩa nghiệp vụ:** Chứng minh năng lực phân tích thời gian thực tế của Data Warehouse thông qua chiều `dim_date` (được gắn cờ ngày lễ Việt Nam). Xác định xem hiện tượng "quá tải, chặt chém, phục vụ chậm" có thể hiện rõ qua điểm đánh giá của du khách hay không.
* **Chỉ số đo lường (KPIs):**
  - `Holiday vs. Normal Day Avg Rating`: So sánh điểm trung bình giữa ngày nghỉ lễ và ngày thường.
  - `Review Velocity`: Tốc độ tăng trưởng lượng đánh giá mới trong tuần lễ hội so với tuần bình thường.
* **Bảng tham gia (DW/Mart):** `dim_date`, `fact_place_reviews`.
* **Trực quan hóa đề xuất:** Biểu đồ đường chuỗi thời gian (Time-series Line Chart) biểu diễn biến động rating và lượng review qua 12 tháng, làm nổi bật (highlight) các giai đoạn ngày lễ lớn.

---

### NHÓM 4: Phân tích Phản hồi Khách hàng & Tiền đề cho AI/NLP (Text & Sentiment)

#### ❓ Câu hỏi 6: Các từ khóa và vấn đề nổi cộm nào xuất hiện nhiều nhất trong các đánh giá tiêu cực (1 - 2 sao)?
* **Ý nghĩa nghiệp vụ:** Giúp chủ doanh nghiệp và cơ quan du lịch biết chính xác du khách đang than phiền vì điều gì: "đắt", "vệ sinh bẩn", "thái độ nhân viên", "đợi lâu", hay "bãi đỗ xe chật"?
* **Chỉ số đo lường (KPIs):**
  - `Keyword Frequency in Negative Reviews`: Tần suất xuất hiện của các cụm từ phàn nàn.
  - `Sentiment Polarity`: Tỷ lệ sắc thái cảm xúc (Tích cực / Tiêu cực / Trung lập).
* **Bảng tham gia (DW/Mart):** `fact_place_reviews`, `fact_youtube_comments`.
* **Trực quan hóa đề xuất:** Đám mây từ (Word Cloud) hoặc Biểu đồ cột ngang Top 10 vấn đề bị phàn nàn nhiều nhất.

---

## 3. Khung tổng hợp kiến trúc kết nối: Từ Câu hỏi tới Data Marts

| Nhóm câu hỏi | Câu hỏi cụ thể | Bảng Data Mart phục vụ | Người dùng hưởng lợi |
|---|---|---|---|
| **Chất lượng** | Xếp hạng mức độ hài lòng du lịch theo tỉnh & danh mục | `dm_province_tourism_buzz`, `dm_place_monthly_reputation` | Sở Du lịch, Cơ quan quản lý, Khách du lịch |
| **Truyền thông** | So sánh độ phủ YouTube vs Trải nghiệm thực tế | `dm_place_monthly_reputation`, `fact_youtube_engagement` | Đơn vị Marketing, Lữ hành, Booking |
| **Mùa vụ** | Tác động của Lễ Tết đến chất lượng phục vụ | `fact_place_reviews` join `dim_date` | Đơn vị điều phối hạ tầng, Khách sạn |
| **Cảm xúc (NLP)**| Top nguyên nhân khiến du khách thất vọng | `fact_place_reviews` (cột `review_text`) | Chủ nhà hàng, Khách sạn, Điểm tham quan |

---

## 4. Lời khuyên khi báo cáo trước Hội đồng

Khi thuyết trình về các câu hỏi nghiệp vụ này, bạn hãy tự tin nhấn mạnh:
> *"Kiến trúc Lakehouse của nhóm chúng em không chỉ dừng lại ở việc lưu trữ kỹ thuật đơn thuần, mà được thiết kế định hướng nghiệp vụ (Business-driven Lakehouse). Toàn bộ mô hình Fact/Dimension ở tầng Gold đều được tối ưu hóa để trả lời chính xác 6 câu hỏi nghiệp vụ cốt lõi của ngành du lịch Việt Nam, từ quản lý danh tiếng địa phương đến đo lường sức lan tỏa truyền thông và chuẩn bị dữ liệu đầu vào cho các mô hình AI/NLP trong tương lai."*
