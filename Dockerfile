# 使用 Python 3.13 的官方 Docker 映像作為基礎映像
FROM python:3.13-slim

ARG DENO_VERSION=2.9.0
ARG TARGETARCH

# 安裝執行期依賴：
# - ffmpeg: Discord 音樂播放與轉檔需要
# - deno: yt-dlp-ejs/yt-dlp 的 JavaScript runtime，改善 YouTube 支援
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    curl \
    unzip \
    && case "${TARGETARCH}" in \
        amd64) DENO_ARCH="x86_64" ;; \
        arm64) DENO_ARCH="aarch64" ;; \
        *) echo "Unsupported target architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${DENO_ARCH}-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 把 requirements.txt 複製到 Docker 容器中
COPY requirements.txt .

# 先更新 pip，避免較舊安裝器在新 Python 版本上抓不到合適 wheel
RUN python -m pip install --upgrade pip

# 安裝 Python 依賴項
RUN python -m pip install --no-cache-dir -r requirements.txt

# 將專案代碼複製到 Docker 容器中
COPY . .

# Docker 容器啟動時，運行 main.py
CMD ["python", "main.py"]
