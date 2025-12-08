# Meow_Bot - Copilot 指引

## 專案概述

Discord 機器人，使用 **discord.py 2.x** 框架，主要功能為音樂播放器，附帶小遊戲（井字遊戲、踩地雷）和實用工具。

## 架構設計

### Cog 模組系統
- **入口點**: `main.py` 負責 Bot 初始化、Cog 自動載入、錯誤處理
- **Cogs 目錄**: `cogs/` 存放功能模組，每個 `.py` 都需有 `async def setup(bot)` 函數
- **動態載入**: Bot 啟動時自動掃描 `cogs/` 資料夾載入所有模組

### 音樂播放器模組化架構 (`module/music_player/`)
音樂模組設計為**獨立可移轉**，與 Cog 分離，方便在其他專案重用：
```
module/music_player/
├── core/           # 核心邏輯（player, queue, cache, state）
├── downloader/     # yt-dlp 非同步下載器（純 asyncio.create_subprocess_exec）
├── ffmpeg/         # FFmpeg 自動管理（Docker 用系統、Windows 自動下載）
├── ui/             # Discord UI 元件（buttons, embeds）
├── utils/          # 錯誤系統、裝飾器
└── constants.py    # 集中管理所有可調參數
```

## 關鍵設計模式

### 純 asyncio 設計
- 使用 `asyncio.create_subprocess_exec` 執行 yt-dlp，不阻塞事件循環
- 所有 I/O 操作皆為非同步

### 播放器並發控制（重要！）
音樂播放器使用 `_play_lock` (`asyncio.Lock`) 防止狀態競爭：

**原則：**
1. **鎖的範圍**：所有涉及 stop → queue操作 → play 的流程應該是原子操作
2. **避免死鎖**：`asyncio.Lock` 不可重入，絕對不能在持有鎖時再次嘗試取得相同的鎖
3. **內部方法**：`_play_song_internal()` 是不含鎖的內部實現，供已持有鎖的方法呼叫
4. **外部方法**：`_play_song()` 包含鎖，供外部呼叫

5. **避免長時間 I/O**：不要在持有鎖期間執行長時間阻塞或網路下載（例如直接在鎖中等待 yt-dlp 下載）。應該把下載或其它長時間任務放在鎖外執行，或使用背景預載（例如 `CacheManager`）在播放之前完成下載，將鎖的持有時間降到最低。

**正確範例：**
```python
async def _handle_next(self):
    async with self._play_lock:  # 整個操作加鎖
        await self.player.stop()
        next_song = self.player.queue.next()
        if next_song:
            await self._play_song_internal(next_song)  # 使用內部方法
```

**錯誤範例（會死鎖）：**
```python
async def _play_song(self, song):
    async with self._play_lock:
        if failed:
            await self._play_next_song()  # ❌ 這會嘗試再次取鎖
```

### 錯誤處理
- 統一繼承 `MusicError`，包含 `message`（技術訊息）和 `user_message`（使用者友善訊息）
- 錯誤自動傳送給 Bot 擁有者（`on_command_error` / `on_app_command_error`）
- yt-dlp 錯誤透過 `_create_error_response()` 回傳結構化錯誤字典，不拋例外
- 播放失敗時返回 `False` 讓呼叫者決定是否嘗試下一首

### UI 按鈕處理注意事項
- `_button_callback` 處理動作後需判斷是否 `return`，避免後續呼叫導致狀態錯誤
- 例如：離開按鈕 (`ACTION_LEAVE`) 處理後必須 `return`，不可再呼叫 `_refresh_player_ui()`
- 不要直接修改 `queue._current_index`，使用 `queue.jump_to()` 方法

## 開發指引

### 新增 Cog
```python
# cogs/my_feature.py
import discord
from discord.ext import commands

class MyFeature(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @discord.app_commands.command(name="指令名稱", description="說明")
    async def my_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("回應")

async def setup(bot):
    await bot.add_cog(MyFeature(bot))
```

### 常數調整
所有播放器參數集中於 `module/music_player/constants.py`

### 環境變數
- `DISCORD_BOT_TOKEN`: Bot Token（必要）
- `DEBUG`: 設為 `true` 啟用 DEBUG 日誌

## 執行方式

### 本機開發
```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt
python main.py
```

### Docker 部署
```bash
docker compose up -d
```

## 注意事項

- **Windows 事件循環**: `main.py` 已設定 `WindowsSelectorEventLoopPolicy`
- **FFmpeg**: Windows 開發環境自動從 GitHub 下載至 `module/music_player/ffmpeg/bin/`
- **日誌**: 使用 `loguru`，檔案輸出至 `./logs/system.log`（7 天輪替）
- **暫存目錄**: 音樂快取存放於 `./temp/music/`
- **指令名稱**: 使用中文（如 `/音樂-播放`），符合目標使用者習慣
