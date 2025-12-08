# 使用 Python 3.12 的官方 Docker 映像作為基礎映像
FROM python:3.12-slim

# 更新系統並安裝必要的工具和依賴項
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libopus-dev \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Deno（供 yt-dlp 使用）
RUN (curl -fsSL https://deno.land/x/install/install.sh | sh) \
    || (echo "deno.land 失敗，切換到 GitHub Release..." \
    && curl -L "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip" -o deno.zip \
    && unzip deno.zip \
    && mv deno /usr/local/bin/deno \
    && chmod +x /usr/local/bin/deno \
    && rm deno.zip)

# 設定工作目錄
WORKDIR /app

# 把 requirements.txt 複製到 Docker 容器中
COPY requirements.txt .

# 安裝 Python 依賴項
RUN pip install --no-cache-dir -r requirements.txt

# 將專案代碼複製到 Docker 容器中
COPY . .

# Docker 容器啟動時，運行 main.py
CMD ["python", "main.py"]
