# Meow_Bot

![Python 3.13](https://img.shields.io/badge/Python-3.13-blue?logo=python)
![discord.py 2.7](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![Version v1.2](https://img.shields.io/badge/Version-v1.2-orange)

## 介紹

**Meow_Bot** 是我為自己的 Discord 伺服器打造的機器人，有包含 **音樂播放器**。支援 YouTube 等多平台音樂播放，有播放清單管理和互動式按鈕控制介面。

## ✨ 功能特色

### 🎵 音樂播放器

- 支援 YouTube 單曲與播放清單
- 互動式播放控制按鈕（播放/暫停、上下首、循環、離開）
- 即時進度條顯示
- 滑動視窗快取機制，自動預載下幾首歌曲
- 背景下載，播放流暢不中斷

### 🎮 小遊戲

- **井字遊戲** - 與朋友對戰的經典遊戲
- **踩地雷** - Discord 版踩地雷遊戲

### 🛠️ 實用工具

- **頭像查詢** - 查看用戶大頭貼

## 📦 安裝

### 前置需求

- Python 3.13
- FFmpeg（音樂播放需要，Windows 會自動下載）
- Deno 2.3+ 或 Node.js 22+（本機若需要完整 YouTube 支援時建議安裝）
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

## 🐳 Docker 部署

```bash
# 建立並啟動
docker compose up -d

# 查看日誌
docker compose logs -f
```

記得在 `compose.yml` 同目錄建立 `.env` 檔案設定 Token。

Docker 映像會依目標架構自動安裝 `Deno 2.9.0`（支援 `amd64` / `arm64`），供 `yt-dlp` / `yt-dlp-ejs` 執行 JavaScript 萃取流程使用。Deno 版本可透過 `DENO_VERSION` build arg 覆寫。

## 📝 指令列表

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

## 📁 專案結構

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
        ├── downloader/   # yt-dlp 下載器
        ├── ffmpeg/       # FFmpeg 管理
        └── utils/        # 工具函數
```

## ⚙️ 設定說明

### 環境變數

| 變數名稱 | 說明 | 預設值 |
|---------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord 機器人 Token | （必填） |
| `DEBUG` | 開啟除錯模式 | `false` |
| `MAINTAINER_ID` | 指定接收錯誤回報的 Discord 使用者 ID，不填時回退到 application owner | （選填） |

## 🔧 版本說明

- 專案目前以 **Python 3.13** 為目標版本；Docker 會跟隨 `python:3.13-slim` 取得最新 3.13 patch
- 依賴已更新為與 **Python 3.13** 相容的版本，音樂功能改以 `discord.py[voice]` 安裝語音相依
- 在 Python 3.13 上，`discord.py[voice]` 會一併解析 voice 需要的 `audioop-lts` / `davey` 等相依
- Bot 會保留執行期 `yt-dlp` 自動更新設計；音樂功能使用時至多每 24 小時以 pip dry-run 檢查一次差異，只有發現新版才安裝，正式更新失敗時才退回 `yt-dlp -U`

### 音樂播放器設定

可在 `module/music_player/constants.py` 調整：

```python
CACHE_DIR = "./temp/music"       # 快取目錄
PLAYLIST_PER_PAGE = 5            # 播放清單每頁顯示數量
RECONNECT_MAX_ATTEMPTS = 15      # 斷線重連最大嘗試次數
```

## 📄 授權

本專案採用 [MIT License](LICENSE) 授權。
