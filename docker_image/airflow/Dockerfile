FROM apache/airflow:2.9.0-python3.11

# 1. Đổi sang quyền root để cài các thư viện hệ điều hành (OS packages)
USER root
RUN apt-get update && apt-get install -y \
    build-essential \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Chuyển về user airflow để cài đặt các thư viện Python (bao gồm Playwright)
USER airflow
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Cài đặt trình duyệt Chromium cho Playwright dưới quyền user airflow
RUN python -m playwright install chromium

# 3. Đổi lại quyền root lần nữa để Playwright có thể cài các OS dependencies (cần quyền apt-get)
USER root
# Sử dụng đường dẫn tuyệt đối trỏ tới file thực thi playwright của user airflow
RUN /home/airflow/.local/bin/playwright install-deps chromium

# 4. Trả lại quyền user airflow ở bước cuối cùng để chạy container an toàn
USER airflow