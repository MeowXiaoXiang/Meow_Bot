# Meow_Bot

![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![Version v1.1](https://img.shields.io/badge/Version-v1.1-orange)

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

- Python 3.12
- FFmpeg（音樂播放需要，Windows 會自動下載）
- Discord Bot Token

### 安裝步驟

1. **複製專案**

   ```bash
   git clone https://github.com/MeowXiaoXiang/Meow_Bot.git
   cd Meow_Bot
   ```

2. **建立虛擬環境**

   ```bash
   python -m venv venv
   
   # Windows
   .\venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

3. **安裝依賴套件**

   ```bash
   pip install -r requirements.txt
   ```

4. **設定環境變數**

   建立 `.env` 檔案：

   ```env
   DISCORD_BOT_TOKEN=你的機器人Token
   DEBUG=false
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
| `/avatar <用戶>` | 查看指定用戶的頭像 |
| `/tic_tac_toe <對手>` | 開始井字遊戲 |
| `/minesweeper` | 開始踩地雷遊戲 |

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

### 音樂播放器設定

可在 `module/music_player/constants.py` 調整：

```python
CACHE_DIR = "./temp/music"       # 快取目錄
PLAYLIST_PER_PAGE = 5            # 播放清單每頁顯示數量
RECONNECT_MAX_ATTEMPTS = 15      # 斷線重連最大嘗試次數
```

## 📄 授權

本專案採用 [MIT License](LICENSE) 授權。
