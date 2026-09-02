# Meow_Bot

![Python 3.14](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![discord.py 2.7](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![Version v1.3](https://img.shields.io/badge/Version-v1.3-orange)

## 介紹

**Meow_Bot** 是我為自己的 Discord 伺服器打造的機器人，有包含 **音樂播放器**。支援 YouTube 等多平台音樂播放，有播放清單管理和互動式按鈕控制介面。

## 功能特色

### 音樂播放器

- 支援 YouTube 單曲與播放清單
- 互動式播放控制按鈕（播放/暫停、上下首、循環、離開）
- 即時進度條顯示
- 滑動視窗快取機制，自動預載下幾首歌曲
- 背景下載，播放流暢不中斷

### 小遊戲

- **井字遊戲** - 與朋友對戰的經典遊戲
- **踩地雷** - Discord 版踩地雷遊戲

### 實用工具

- **頭像查詢** - 查看用戶大頭貼

## 安裝

### 前置需求

- Python 3.14
- FFmpeg（音樂播放與轉檔需要，必須位於 PATH）
- Deno 2.3+（完整 YouTube 支援需要，必須位於 PATH）
- Discord Bot Token

### 安裝步驟

1. **複製專案**

   ```bash
   git clone https://github.com/MeowXiaoXiang/Meow_Bot.git
   cd Meow_Bot
   ```

2. **建立虛擬環境**

   ```bash
   python -m venv .venv
   
   # Windows
   .\.venv\Scripts\activate
   
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **安裝依賴套件**

   ```bash
   python -m pip install -r requirements.txt
   ```

   Windows 可使用 winget 安裝音樂功能需要的系統工具，安裝後請重新開啟終端機：

   ```powershell
   winget install -e --id Gyan.FFmpeg.Shared
   winget install -e --id DenoLand.Deno
   ```

   `Gyan.FFmpeg.Shared` 為 Windows x64 套件；Windows on ARM 使用者請改用能提供 `ffmpeg` PATH command 的相容發行版。

   Linux 手動部署時，請依發行版的套件管理方式安裝 FFmpeg 與 Deno，並在啟動前確認下列指令均可執行：

   ```bash
   ffmpeg -version
   deno --version
   ```

   Bot 不會下載或設定 FFmpeg、Deno 或 Node.js；本專案只支援 Deno，沒有 Node.js fallback。
   Music Cog 載入時也會確認 FFmpeg 提供 `libopus` encoder；沒有它會直接停用音樂模組，避免到播放時才失敗。

4. **設定環境變數**

   建立 `.env` 檔案：

   ```env
   DISCORD_BOT_TOKEN=你的機器人Token
   DEBUG=false
   MAINTAINER_ID=
   ```

5. **啟動機器人**

   ```bash
   python main.py
   ```

## Docker 部署

```bash
# 建立並啟動
docker compose up -d

# 查看日誌
docker compose logs -f
```

記得在 `compose.yml` 同目錄建立 `.env` 檔案設定 Token。

Docker 映像以 Python 3.14 與 Debian trixie 為基底，透過 Debian APT 安裝 FFmpeg；Deno 則從官方的 multi-architecture binary image 複製，預設為 `2.9.6`，支援 `amd64` / `arm64`。兩者都會在 image build 階段驗證可從 PATH 執行；Deno 供 yt-dlp 的 JavaScript 萃取流程使用。若有必要，可用 `docker compose build --build-arg DENO_VERSION=<版本>` 覆寫 Deno 版本。

Compose 不再指定公開 DNS，會使用 Docker 與宿主環境的預設 DNS 設定。

yt-dlp 本身由 Bot 管理：第一次載入 Music Cog 時會依作業系統與架構下載官方 nightly standalone binary；之後每次載入會檢查更新。Binary 固定保存於 `module/music_player/ytdlp/bin/`，Compose 會以 bind mount 保留它，讓 container recreate 後仍可使用既有版本。

## 指令列表

### 音樂指令

| 指令 | 說明 |
|------|------|
| `/音樂-播放 <網址>` | 啟動播放器並播放指定網址 |
| `/音樂-新增 <網址>` | 新增音樂到播放清單 |
| `/音樂-清單` | 查看當前播放清單 |
| `/音樂-跳轉 <編號>` | 跳轉到指定歌曲 |
| `/音樂-移除 <編號>` | 移除指定歌曲 |
| `/音樂-清空` | 清空播放清單 |
| `/音樂-顯示播放器` | 重新顯示播放器控制面板 |

### 其他指令

| 指令 | 說明 |
|------|------|
| `/查看成員頭貼` | 查看指定用戶的頭像 |
| `/小遊戲-ooxx` | 開始井字遊戲 |
| `/踩地雷` | 開始踩地雷遊戲 |

## 專案結構

```bash
Meow_Bot/
├── main.py                 # 程式入口
├── requirements.txt        # 依賴套件
├── compose.yml            # Docker Compose 設定
├── Dockerfile             # Docker 映像設定
├── .env                   # 環境變數（需自行建立）
├── cogs/                  # 功能模組
│   ├── music_cog.py      # 音樂播放器
│   ├── avatar.py         # 頭像查詢
│   ├── tic_tac_toe.py    # 井字遊戲
│   └── minesweeper.py    # 踩地雷
└── module/
    └── music_player/      # 音樂播放器核心
        ├── core/         # 播放器核心邏輯
        ├── ui/           # UI 元件（按鈕、嵌入）
        ├── ytdlp/        # yt-dlp manager、CLI client 與 managed binary
        └── utils/        # 工具函數
```

## 設定說明

### 環境變數

| 變數名稱 | 說明 | 預設值 |
|---------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord 機器人 Token | （必填） |
| `DEBUG` | 開啟除錯模式 | `false` |
| `MAINTAINER_ID` | 指定接收錯誤回報的 Discord 使用者 ID，不填時回退到 application owner | （選填） |

## 版本說明

- 專案目前以 **Python 3.14** 為目標版本；Docker 會跟隨 `python:3.14-slim-trixie` 取得最新 3.14 patch
- 依賴已確認與 **Python 3.14** 相容，音樂功能以 `discord.py[voice]` 安裝語音相依
- 在 Python 3.14 上，`discord.py[voice]` 會一併解析 voice 需要的 `audioop-lts` / `davey` 等相依
- Bot 使用官方 nightly yt-dlp standalone binary；Music Cog 載入時會更新它。更新失敗但既有 binary 可用時，音樂功能會繼續啟動；只有沒有可用 binary 且首次下載失敗時才會停用 Music Cog
- 播放器模組目前版本為 **1.0.0**，可由 `module.music_player.__version__` 取得；跨專案複製時請依其公開匯出介面整合

### 音樂播放器設定

可在 `module/music_player/constants.py` 調整：

```python
CACHE_DIR = "./temp/music"       # 快取目錄
PLAYLIST_PER_PAGE = 5            # 播放清單每頁顯示數量
RECONNECT_MAX_ATTEMPTS = 15      # 斷線重連最大嘗試次數
```

## 授權

本專案採用 [MIT License](LICENSE) 授權。
