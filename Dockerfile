ARG PYTHON_VERSION=3.14
ARG DENO_VERSION=2.9.6

# 使用官方 Deno binary image，提供已驗證的 amd64 / arm64 standalone binary。
FROM denoland/deno:bin-${DENO_VERSION} AS deno

# 使用 Python 官方 Debian trixie slim 映像作為執行期基底。
FROM python:${PYTHON_VERSION}-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# FFmpeg（包含 libopus encoder）由 Debian 套件庫提供；Deno 由官方 binary stage 複製。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno

# 在 image build 階段確認 Music Cog 需要的兩項外部工具皆可從 PATH 執行。
RUN deno --version \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q 'libopus'

WORKDIR /app

COPY requirements.txt .

# 保持 pip 為可支援新 Python wheel 的版本，再安裝鎖定的執行期依賴。
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
