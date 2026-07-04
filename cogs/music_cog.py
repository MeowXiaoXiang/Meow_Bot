"""
音樂播放器 Cog - 重構版本

使用新的模組化架構，提供:
- 無限歌曲佇列
- 滑動視窗快取
- 背景預載
- 準確時間追蹤
- 純 asyncio 設計
- 自動 FFmpeg 管理
"""

# -------------------- Discord --------------------
import discord
from discord.ext import commands, tasks
from discord import app_commands

# -------------------- Module --------------------
from module.music_player import (
    # Core
    MusicPlayer,
    MusicQueue,
    Song,
    # Downloader
    YTDLPDownloader,
    # FFmpeg
    get_ffmpeg_path,
    # UI
    EmbedBuilder,
    MusicPlayerView,
    PaginationView,
    create_player_view,
    # Errors
    MusicError,
    QueueError,
    SongUnavailableError,
    # Constants
    CACHE_DIR,
    PLAYLIST_PER_PAGE,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_INTERVAL,
    YTDLP_UPDATE_INTERVAL,
    MANUAL_OPERATION_DEBOUNCE,
    EMBED_UPDATE_INTERVAL,
    VOICE_CONNECT_MAX_RETRIES,
    VOICE_CONNECT_RETRY_DELAY,
)

# -------------------- Other --------------------
import asyncio
import json
import os
import sys
import time
from loguru import logger

class MusicPlayerCog(commands.Cog):
    """Discord 音樂播放器 Cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # 核心組件
        self.ffmpeg_path: str | None = None
        self.player: MusicPlayer | None = None
        self.downloader: YTDLPDownloader | None = None
        
        # UI 相關
        self.embed_builder = EmbedBuilder()
        self.player_view: MusicPlayerView | None = None
        self.player_message: discord.Message | None = None
        self.playlist_message: discord.Message | None = None
        
        # 分頁設定
        self.playlist_per_page = PLAYLIST_PER_PAGE
        self.current_playlist_page = 1
        
        # 連線狀態
        self.last_voice_channel: discord.VoiceChannel | None = None
        self.manual_disconnect = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = RECONNECT_MAX_ATTEMPTS
        self.last_yt_dlp_check: float | None = None

        # 播放鎖（防止競爭條件）
        self._play_lock = asyncio.Lock()
        self._yt_dlp_update_lock = asyncio.Lock()

        # 追蹤 wrapper 背景任務，避免 cleanup 時遺漏未完成 task
        self._background_tasks: set[asyncio.Task] = set()

        # 背景任務
        self.update_embed_task = self.update_embed
    
    async def cog_load(self):
        """Cog 載入時初始化"""
        # 確保暫存目錄存在
        os.makedirs(CACHE_DIR, exist_ok=True)
        logger.debug(f"確認 {CACHE_DIR} 目錄存在")
        
        # 初始化 FFmpeg（優先使用系統 PATH，找不到才下載）
        self.ffmpeg_path = await get_ffmpeg_path()
        
        if self.ffmpeg_path:
            # 初始化下載器
            self.downloader = YTDLPDownloader(
                download_dir=CACHE_DIR,
                ffmpeg_path=self.ffmpeg_path
            )
            
            # 初始化播放器（不帶 voice_client，等連接時設定）
            self.player = MusicPlayer(
                downloader=self.downloader,
                cache_dir=CACHE_DIR,
                ffmpeg_path=self.ffmpeg_path,
                on_song_end=self._on_song_end,
            )
            
            logger.info("[MusicPlayerCog] 初始化完成")
        else:
            logger.error("FFmpeg 初始化失敗，無法正常啟動音樂播放器！")
    
    async def cog_unload(self):
        """Cog 卸載時清理資源"""
        await self._cleanup_resources()
        logger.info("[MusicPlayerCog] 已卸載，資源已清理")
    
    # ==================== 核心回調 ====================
    
    async def _on_song_end(self):
        """
        歌曲自然播放結束的回調
        
        只在歌曲自然播放完畢時觸發，手動停止不會觸發
        """
        # 檢查是否正在關閉播放器
        if self.manual_disconnect:
            logger.debug("[MusicPlayerCog] 歌曲結束，但正在關閉播放器，忽略")
            return
        
        if not self.player:
            return
        
        # 檢查是否已連接語音頻道
        if not self.player.is_connected:
            logger.debug("[MusicPlayerCog] 歌曲結束，但未連接語音頻道，忽略")
            return
        
        logger.debug("[MusicPlayerCog] 歌曲自然結束，準備處理下一首")
        
        async with self._play_lock:
            if self.manual_disconnect or not self.player or not self.player.is_connected:
                logger.debug("[MusicPlayerCog] 歌曲結束後狀態已變更，忽略自動切歌")
                return

            # 檢查是否有手動操作（避免重複觸發）
            if self.player.state.last_manual_operation_time:
                time_since_manual = time.time() - self.player.state.last_manual_operation_time
                if time_since_manual < MANUAL_OPERATION_DEBOUNCE:
                    logger.debug(f"檢測到最近的手動操作 ({time_since_manual:.2f}s 前)，忽略自動切歌")
                    return

            # 嘗試播放下一首
            try:
                await self._play_next_song_locked()
            except MusicError as e:
                logger.error(f"[MusicPlayerCog] 播放下一首時發生錯誤: {e}")
                await self._show_error(e.user_message)

    async def _play_next_song(self):
        async with self._play_lock:
            await self._play_next_song_locked()

    async def _play_next_song_locked(self):
        """播放下一首歌曲（包含失敗重試邏輯）"""
        if not self.player:
            return
        
        queue = self.player.queue
        max_retries = 5  # 最多嘗試 5 首，避免無限迴圈
        
        # 單首歌曲循環模式：直接重播當前歌曲
        if queue.loop and len(queue) == 1:
            current_song = queue.current
            if current_song:
                success = await self._play_song_internal(current_song)
                if not success:
                    await self._show_error("無法播放此歌曲")
            return
        
        for _ in range(max_retries):
            # 檢查佇列是否為空
            if len(queue) == 0:
                logger.debug("佇列為空，停止播放")
                await self._show_empty_queue()
                return
            
            # 嘗試切換到下一首
            next_song = queue.next()
            
            if next_song is None:
                # 沒有下一首（非循環模式且已到底）
                logger.debug("已到達佇列末尾，停止播放")
                current_song = queue.current
                if current_song:
                    embed = self.embed_builder.playing_embed(
                        song=current_song,
                        is_looping=queue.loop,
                        is_playing=False,
                        current_time=0,
                    )
                    await self._update_player_message(embed)
                return
            
            # 嘗試播放
            success = await self._play_song_internal(next_song)
            if success:
                return  # 成功播放，結束
            
            # 失敗，繼續嘗試下一首
            logger.debug(f"歌曲 {next_song.title} 播放失敗，嘗試下一首")
        
        # 連續失敗太多次
        logger.error(f"連續 {max_retries} 首歌曲播放失敗")
        await self._show_error("連續多首歌曲無法播放，請檢查網路連線")
    
    async def _play_song(self, song: Song) -> bool:
        """
        播放指定歌曲
        
        Args:
            song: 要播放的歌曲
        
        Returns:
            True 如果成功播放, False 如果失敗（呼叫者應嘗試下一首）
        """
        if not self.player:
            return False
        
        # 使用鎖防止多個任務同時播放
        async with self._play_lock:
            return await self._play_song_internal(song)
    
    async def _play_song_internal(self, song: Song) -> bool:
        """
        播放歌曲的內部實現（不包含鎖，避免死鎖）
        
        Returns:
            True 如果成功播放, False 如果失敗
        """
        if not self.player:
            return False
        
        try:
            # 檢查快取，若無則下載
            cache = self.player.cache
            file_path = cache.get(song.id)
            
            if not file_path:
                # 顯示下載中狀態
                embed = self.embed_builder.downloading_embed(song)
                await self._update_player_message(embed)
                
                # 下載歌曲
                info, file_path = await self.downloader.download(song.url)
                
                if not file_path:
                    raise SongUnavailableError(song.title)
                
                # 加入快取
                cache.put(song.id, str(file_path))
            
            # 播放（player.play 內部會觸發預載）
            result = await self.player.play(song)
            
            if result is None:
                # 下載失敗，移除歌曲
                logger.warning(f"歌曲無法播放（player 返回 None）: {song.title}")
                await self.player.queue.remove(song.id)
                return False  # 告訴呼叫者失敗，由呼叫者決定是否嘗試下一首
            
            # 更新 UI
            await self._refresh_player_ui()
            return True
            
        except SongUnavailableError:
            logger.warning(f"歌曲無法播放: {song.title}")
            # 從佇列移除
            await self.player.queue.remove(song.id)
            return False  # 告訴呼叫者失敗
    
    async def _preload_upcoming(self):
        """預載即將播放的歌曲"""
        if not self.player:
            return
        
        try:
            await self.player.cache.preload_window(
                queue=self.player.queue,
                downloader=self.downloader,
            )
        except Exception as e:
            logger.warning(f"[MusicPlayerCog] 預載失敗: {e}")

    def _schedule_preload_upcoming(self):
        """建立可追蹤的預載任務，方便 cleanup 時取消"""
        task = asyncio.create_task(
            self._preload_upcoming(),
            name="music_preload_upcoming"
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
    
    # ==================== UI 更新 ====================
    
    async def _refresh_player_ui(self):
        """刷新播放器 UI（嵌入和按鈕）"""
        if not self.player or not self.player_message:
            return
        
        current_song = self.player.queue.current
        if not current_song:
            await self._show_empty_queue()
            return
        
        # 建立嵌入
        embed = self.embed_builder.playing_embed(
            song=current_song,
            is_looping=self.player.queue.loop,
            is_playing=self.player.is_playing,
            current_time=self.player.state.current_position,
        )
        
        # 更新按鈕狀態
        if self.player_view:
            self.player_view.update_play_pause(self.player.is_playing)
            self.player_view.update_loop(self.player.queue.loop)
            self.player_view.update_navigation(
                has_previous=self.player.queue.current_index > 0,
                has_next=self.player.queue.current_index < len(self.player.queue) - 1,
            )
        
        await self._update_player_message(embed)
    
    async def _update_player_message(self, embed: discord.Embed):
        """更新播放器訊息"""
        if self.player_message:
            await self._edit_player_message(embed=embed, view=self.player_view)

    async def _bind_persistent_message(
        self,
        message: discord.Message | None,
    ) -> discord.Message | None:
        """將 interaction/webhook 訊息重新綁定成一般可長期編輯的訊息物件。"""
        if message is None:
            return None

        channel = getattr(message, "channel", None)
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return message

        try:
            return await fetch_message(message.id)
        except discord.HTTPException as error:
            logger.debug(f"重新綁定訊息失敗，沿用既有引用: {error}")
            return message

    async def _edit_message_safely(
        self,
        message: discord.Message | None,
        **kwargs,
    ) -> discord.Message | None:
        """安全編輯訊息，必要時在 webhook token 過期後重新綁定重試。"""
        if message is None:
            return None

        try:
            await message.edit(**kwargs)
            return message
        except discord.NotFound:
            logger.warning("播放器訊息已被刪除")
            return None
        except discord.HTTPException as error:
            if getattr(error, "code", None) == 50027:
                logger.warning("播放器訊息 webhook token 已失效，嘗試重新綁定一般訊息引用")
                rebound_message = await self._bind_persistent_message(message)
                if rebound_message is not None and rebound_message is not message:
                    try:
                        await rebound_message.edit(**kwargs)
                        return rebound_message
                    except discord.NotFound:
                        logger.warning("重新綁定後的播放器訊息已不存在")
                        return None
                    except discord.HTTPException as rebound_error:
                        logger.error(f"重新綁定後仍無法更新播放器訊息: {rebound_error}")
                        return rebound_message

            logger.error(f"更新播放器訊息失敗: {error}")
            return message

    async def _edit_player_message(self, **kwargs) -> bool:
        """更新目前追蹤中的播放器訊息，並維持最新的訊息引用。"""
        updated_message = await self._edit_message_safely(self.player_message, **kwargs)
        self.player_message = updated_message
        return updated_message is not None
    
    async def _show_empty_queue(self):
        """顯示佇列為空的狀態"""
        embed = self.embed_builder.error_embed("播放清單中無音樂")
        embed.description = "請透過 `/音樂-新增` 來新增音樂"
        
        if self.player_view:
            self.player_view.disable_all()
        
        await self._update_player_message(embed)
    
    async def _show_error(self, message: str):
        """顯示錯誤訊息"""
        embed = self.embed_builder.error_embed(message)
        await self._update_player_message(embed)
    
    # ==================== 按鈕處理 ====================
    
    async def _button_callback(self, interaction: discord.Interaction, action: str):
        """
        處理播放器按鈕點擊
        
        Args:
            interaction: Discord 互動
            action: 按鈕動作
        """
        if not self.player:
            return
        
        try:
            if action == MusicPlayerView.ACTION_PLAY_PAUSE:
                await self._handle_play_pause()
            elif action == MusicPlayerView.ACTION_NEXT:
                await self._handle_next()
            elif action == MusicPlayerView.ACTION_PREVIOUS:
                await self._handle_previous()
            elif action == MusicPlayerView.ACTION_LOOP:
                await self._handle_loop()
            elif action == MusicPlayerView.ACTION_LEAVE:
                await self._handle_leave()
                return  # 離開後不需要更新 UI，_handle_leave 已處理
            
            # 更新 UI
            await self._refresh_player_ui()
            
        except MusicError as e:
            logger.error(f"按鈕處理錯誤: {e}")
            await self._show_error(e.user_message)
    
    async def _handle_play_pause(self):
        """處理播放/暫停"""
        if not self.player:
            return
        
        if self.player.is_paused:
            await self.player.resume()
        elif self.player.is_playing:
            await self.player.pause()
        else:
            # 嘗試重新播放當前歌曲
            current_song = self.player.queue.current
            if current_song:
                self.player.state.mark_manual_operation()
                await self._play_song(current_song)
    
    async def _handle_next(self):
        """處理下一首（整個操作加鎖確保原子性）"""
        if not self.player:
            return
        
        async with self._play_lock:
            # 先標記手動操作，避免 stop() 觸發的回調被處理
            self.player.state.mark_manual_operation()
            
            # 單首歌曲循環模式：重新開始播放（而非無限跳歌）
            queue = self.player.queue
            if queue.loop and len(queue) == 1:
                current_song = queue.current
                if current_song:
                    await self.player.stop()
                    success = await self._play_song_internal(current_song)
                    if not success:
                        await self._show_error("無法重新播放此歌曲")
                return
            
            await self.player.stop()
            
            next_song = queue.next()
            if next_song:
                success = await self._play_song_internal(next_song)
                if not success:
                    # 失敗，嘗試下一首（在鎖內）
                    await self._try_next_available_song()
            else:
                # 非循環模式已到底，更新 UI 顯示停止狀態
                await self._refresh_player_ui()
    
    async def _handle_previous(self):
        """處理上一首（整個操作加鎖確保原子性）"""
        if not self.player:
            return
        
        async with self._play_lock:
            # 先標記手動操作，避免 stop() 觸發的回調被處理
            self.player.state.mark_manual_operation()
            
            # 單首歌曲循環模式：重新開始播放（而非無限跳歌）
            queue = self.player.queue
            if queue.loop and len(queue) == 1:
                current_song = queue.current
                if current_song:
                    await self.player.stop()
                    success = await self._play_song_internal(current_song)
                    if not success:
                        await self._show_error("無法重新播放此歌曲")
                return
            
            await self.player.stop()
            
            prev_song = queue.previous()
            if prev_song:
                success = await self._play_song_internal(prev_song)
                if not success:
                    # 失敗，嘗試上一首（在鎖內）
                    await self._try_previous_available_song()
            else:
                # 非循環模式已到頂，更新 UI 顯示停止狀態
                await self._refresh_player_ui()
    
    async def _try_next_available_song(self):
        """在鎖內嘗試找到下一首可播放的歌曲"""
        queue = self.player.queue
        
        # 單首歌曲循環模式：不嘗試下一首（因為只有一首）
        if queue.loop and len(queue) == 1:
            await self._show_error("唯一的歌曲無法播放")
            return
        
        max_retries = 5
        for _ in range(max_retries):
            if len(queue) == 0:
                await self._show_empty_queue()
                return
            
            next_song = queue.next()
            if next_song is None:
                await self._refresh_player_ui()
                return
            
            success = await self._play_song_internal(next_song)
            if success:
                return
        
        await self._show_error("連續多首歌曲無法播放")
    
    async def _try_previous_available_song(self):
        """在鎖內嘗試找到上一首可播放的歌曲"""
        queue = self.player.queue
        
        # 單首歌曲循環模式：不嘗試上一首（因為只有一首）
        if queue.loop and len(queue) == 1:
            await self._show_error("唯一的歌曲無法播放")
            return
        
        max_retries = 5
        for _ in range(max_retries):
            if len(queue) == 0:
                await self._show_empty_queue()
                return
            
            prev_song = queue.previous()
            if prev_song is None:
                await self._refresh_player_ui()
                return
            
            success = await self._play_song_internal(prev_song)
            if success:
                return
        
        await self._show_error("連續多首歌曲無法播放")
    
    async def _handle_loop(self):
        """處理循環開關"""
        if not self.player:
            return
        
        self.player.queue.loop = not self.player.queue.loop
        logger.debug(f"循環模式: {'開啟' if self.player.queue.loop else '關閉'}")
    
    async def _handle_leave(self):
        """處理離開"""
        self.manual_disconnect = True
        
        # 先保存訊息引用，因為 cleanup 會清除它
        message = self.player_message
        
        await self._cleanup_resources()
        
        # 更新訊息顯示已關閉
        if message:
            try:
                embed = discord.Embed(
                    title="👋 播放器已關閉",
                    description="感謝使用！使用 `/音樂-播放` 可以重新啟動",
                    color=discord.Color.green()
                )
                await self._edit_message_safely(message, embed=embed, view=None)
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass
    
    # ==================== 斜線指令 ====================
    
    @app_commands.command(name="音樂-播放", description="啟動音樂播放器並播放指定的網址")
    @app_commands.guild_only()
    @app_commands.rename(url="網址")
    @app_commands.describe(url="影片、音樂或播放清單的網址")
    async def start_player(self, interaction: discord.Interaction, url: str):
        """啟動播放器"""
        await interaction.response.defer()

        # 檢查初始化狀態
        if not self.ffmpeg_path or not self.player or not self.downloader:
            await interaction.followup.send("播放器尚未初始化完成，請稍後再試。")
            return
        
        # 檢查用戶是否在語音頻道
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("請先加入語音頻道再執行此指令。")
            return
        
        # 檢查播放器是否已在運行
        if self.player.voice_client and self.player.voice_client.is_connected():
            await interaction.followup.send(
                "播放器已經啟動，請使用 `/音樂-新增` 指令。"
            )
            return

        await self._ensure_ytdlp_current()
        
        try:
            # 取得訊息，並立即重新綁定成一般 channel message
            original_message = await interaction.original_response()
            self.player_message = await self._bind_persistent_message(original_message)
            
            # 連接語音頻道（帶重試）
            channel = interaction.user.voice.channel
            voice_client = await self._connect_voice_with_retry(channel)
            
            if voice_client is None:
                await interaction.followup.send(
                    "無法連接語音頻道，請稍後再試。（網路連線可能不穩定）"
                )
                return
            
            self.last_voice_channel = channel
            self.manual_disconnect = False
            
            # 設定語音客戶端
            await self.player.set_voice_client(voice_client)
            
            # 判斷是單曲還是播放清單
            is_playlist = self.downloader.is_playlist(url)
            
            if is_playlist:
                await interaction.followup.send("⏳ 正在解析播放清單，請稍候...")
                await self._handle_playlist_start(interaction, url)
            else:
                await interaction.followup.send("⏳ 正在解析單曲音樂，請稍候...")
                await self._handle_single_song_start(interaction, url)
                
        except discord.ClientException as e:
            logger.error(f"連接語音頻道失敗: {e}")
            await interaction.followup.send("無法加入語音頻道，請確認機器人是否有權限。")
        except Exception as e:
            logger.exception(f"啟動播放器時發生錯誤: {e}")
            await interaction.followup.send(f"啟動播放器時發生錯誤: {e}")
    
    async def _handle_single_song_start(self, interaction: discord.Interaction, url: str):
        """處理單曲播放啟動"""
        try:
            # 取得歌曲資訊
            info = await self.downloader.extract_info(url)
            if not info:
                embed = self.embed_builder.error_embed("無法解析音樂資訊")
                await self._edit_player_message(content=None, embed=embed, view=None)
                return
            
            # 建立 Song 物件（確保 duration 為 int）
            duration = info.get("duration") or 0
            try:
                duration = int(float(duration)) if duration else 0
            except (ValueError, TypeError, OverflowError):
                duration = 0
            
            song = Song(
                id=info.get("id") or "",
                title=info.get("title") or "未知標題",
                url=url,
                duration=duration,
                thumbnail=info.get("thumbnail") or "",
                uploader=info.get("uploader") or "未知上傳者",
                uploader_url=info.get("uploader_url") or "",
            )
            
            # 下載
            _, file_path = await self.downloader.download(url)
            if not file_path:
                embed = self.embed_builder.error_embed("下載音樂失敗")
                await self._edit_player_message(content=None, embed=embed, view=None)
                return
            
            # 加入佇列和快取
            await self.player.queue.add(song)
            self.player.cache.put(song.id, str(file_path))
            
            # 播放
            await self.player.play(song)
            
            # 建立按鈕視圖
            self.player_view = create_player_view(
                player=self.player,
                button_callback=self._button_callback,
            )
            
            # 更新 UI
            embed = self.embed_builder.playing_embed(
                song=song,
                is_looping=self.player.queue.loop,
                is_playing=True,
            )
            await self._edit_player_message(content=None, embed=embed, view=self.player_view)
            
            # 啟動定期更新任務
            if not self.update_embed_task.is_running():
                self.update_embed_task.start()
                
        except Exception as e:
            logger.exception(f"啟動單曲播放時發生錯誤: {e}")
            embed = self.embed_builder.error_embed(f"錯誤: {e}")
            await self._edit_player_message(content=None, embed=embed, view=None)
    
    async def _handle_playlist_start(self, interaction: discord.Interaction, url: str):
        """處理播放清單啟動"""
        try:
            # 解析播放清單
            entries = await self.downloader.extract_playlist(url)
            if not entries:
                embed = self.embed_builder.error_embed("無法解析播放清單或播放清單為空")
                await self._edit_player_message(content=None, embed=embed, view=None)
                return
            
            # 建立 Song 物件並加入佇列
            songs = []
            for entry in entries:
                # 確保 duration 為 int
                duration = entry.get("duration") or 0
                try:
                    duration = int(float(duration)) if duration else 0
                except (ValueError, TypeError, OverflowError):
                    duration = 0
                
                song = Song(
                    id=entry.get("id") or "",
                    title=entry.get("title") or "未知標題",
                    url=entry.get("url") or "",
                    duration=duration,
                    thumbnail=entry.get("thumbnail") or "",
                    uploader=entry.get("uploader") or "未知上傳者",
                    uploader_url=entry.get("uploader_url") or "",
                )
                songs.append(song)
                await self.player.queue.add(song)
            
            # 下載第一首
            first_song = songs[0]
            _, file_path = await self.downloader.download(first_song.url)
            if not file_path:
                embed = self.embed_builder.error_embed("下載第一首歌曲失敗")
                await self._edit_player_message(content=None, embed=embed, view=None)
                return
            
            # 加入快取並播放
            self.player.cache.put(first_song.id, str(file_path))
            await self.player.play(first_song)
            
            # 建立按鈕視圖
            self.player_view = create_player_view(
                player=self.player,
                button_callback=self._button_callback,
            )
            
            # 更新 UI
            embed = self.embed_builder.playing_embed(
                song=first_song,
                is_looping=self.player.queue.loop,
                is_playing=True,
            )
            await self._edit_player_message(content=None, embed=embed, view=self.player_view)
            
            # 啟動定期更新任務
            if not self.update_embed_task.is_running():
                self.update_embed_task.start()
            
            # 背景預載
            self._schedule_preload_upcoming()
            
        except Exception as e:
            logger.exception(f"啟動播放清單時發生錯誤: {e}")
            embed = self.embed_builder.error_embed(f"錯誤: {e}")
            await self._edit_player_message(content=None, embed=embed, view=None)
    
    @app_commands.command(name="音樂-新增", description="新增音樂到播放清單")
    @app_commands.guild_only()
    @app_commands.rename(url="網址")
    @app_commands.describe(url="影片、音樂或播放清單的網址")
    async def add_music(self, interaction: discord.Interaction, url: str):
        """新增音樂到播放清單"""
        await interaction.response.defer()
        
        # 檢查播放器狀態
        if not self.player or not self.player.voice_client:
            await interaction.followup.send(
                "播放器尚未啟動，請先使用 `/音樂-播放` 指令。",
                ephemeral=True
            )
            return

        await self._ensure_ytdlp_current()
        
        try:
            is_playlist = self.downloader.is_playlist(url)
            
            if is_playlist:
                await self._handle_playlist_add(interaction, url)
            else:
                await self._handle_single_song_add(interaction, url)
                
        except Exception as e:
            logger.exception(f"新增音樂時發生錯誤: {e}")
            await interaction.followup.send("無法新增音樂，請稍後再試。", ephemeral=True)
    
    async def _handle_single_song_add(self, interaction: discord.Interaction, url: str):
        """處理單曲新增"""
        try:
            # 取得歌曲資訊
            info = await self.downloader.extract_info(url)
            if not info:
                await interaction.followup.send("無法解析音樂資訊", ephemeral=True)
                return
            
            # 建立 Song 物件
            song = Song(
                id=info.get("id") or "",
                title=info.get("title") or "未知標題",
                url=url,
                duration=info.get("duration") or 0,
                thumbnail=info.get("thumbnail") or "",
                uploader=info.get("uploader") or "未知上傳者",
                uploader_url=info.get("uploader_url") or "",
            )
            
            # 加入佇列
            await self.player.queue.add(song)
            
            # 顯示已新增
            embed = self.embed_builder.added_song_embed(song)
            await interaction.followup.send(embed=embed)
            
            # 如果目前沒有播放，開始播放
            if not self.player.is_playing:
                # 使用 jump_to 跳到新增的歌曲（索引為佇列長度 - 1）
                target_index = len(self.player.queue) - 1
                self.player.queue.jump_to(target_index)
                await self._play_song(song)
            
            # 更新按鈕
            await self._refresh_player_ui()
            
        except Exception as e:
            logger.exception(f"新增單曲時發生錯誤: {e}")
            await interaction.followup.send("無法新增音樂，請稍後再試。", ephemeral=True)
    
    async def _handle_playlist_add(self, interaction: discord.Interaction, url: str):
        """處理播放清單新增"""
        try:
            await interaction.followup.send("正在解析播放清單，請稍候...", ephemeral=True)
            
            # 解析播放清單
            entries = await self.downloader.extract_playlist(url)
            if not entries:
                await interaction.followup.send("無法解析播放清單或播放清單為空", ephemeral=True)
                return
            
            # 加入佇列
            added_count = 0
            was_empty = len(self.player.queue) == 0 or not self.player.is_playing
            first_new_song = None
            
            for entry in entries:
                song = Song(
                    id=entry.get("id") or "",
                    title=entry.get("title") or "未知標題",
                    url=entry.get("url") or "",
                    duration=entry.get("duration") or 0,
                    thumbnail=entry.get("thumbnail") or "",
                    uploader=entry.get("uploader") or "未知上傳者",
                    uploader_url=entry.get("uploader_url") or "",
                )
                await self.player.queue.add(song)
                added_count += 1
                
                if first_new_song is None:
                    first_new_song = song
            
            # 顯示結果
            embed = self.embed_builder.added_songs_embed(added_count)
            await interaction.followup.send(embed=embed)
            
            # 如果之前沒有播放，開始播放第一首新歌
            if was_empty and first_new_song:
                # 使用 jump_to 跳到第一首新歌的位置
                target_index = len(self.player.queue) - added_count
                self.player.queue.jump_to(target_index)
                await self._play_song(first_new_song)
            
            # 更新按鈕
            await self._refresh_player_ui()
            
            # 背景預載
            self._schedule_preload_upcoming()
            
        except Exception as e:
            logger.exception(f"新增播放清單時發生錯誤: {e}")
            await interaction.followup.send("無法新增播放清單，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-清單", description="查看當前播放清單")
    @app_commands.guild_only()
    async def view_playlist(self, interaction: discord.Interaction):
        """查看播放清單"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 清除舊的播放清單訊息
            if self.playlist_message:
                try:
                    self.playlist_message = await self._edit_message_safely(
                        self.playlist_message,
                        view=None,
                    )
                except:
                    pass
                self.playlist_message = None
            
            # 取得分頁資料
            songs = list(self.player.queue)
            total_songs = len(songs)
            total_pages = max(1, (total_songs + self.playlist_per_page - 1) // self.playlist_per_page)
            
            self.current_playlist_page = 1
            
            # 建立嵌入
            embed = self.embed_builder.playlist_embed(
                songs=songs,
                current_index=self.player.queue.current_index,
                page=1,
                per_page=self.playlist_per_page,
            )
            
            # 建立翻頁按鈕
            pagination_view = PaginationView(
                button_callback=self._pagination_callback,
                timeout_callback=self._playlist_timeout_callback,
                current_page=1,
                total_pages=total_pages,
            )
            
            # 發送訊息
            self.playlist_message = await interaction.followup.send(
                embed=embed,
                view=pagination_view,
                wait=True,
            )
            self.playlist_message = await self._bind_persistent_message(self.playlist_message)
            
        except Exception as e:
            logger.exception(f"查看播放清單時發生錯誤: {e}")
            await interaction.followup.send("無法查看播放清單，請稍後再試。", ephemeral=True)
    
    async def _pagination_callback(self, interaction: discord.Interaction, action: str):
        """處理翻頁按鈕"""
        if not self.player or not self.playlist_message:
            return
        
        try:
            songs = list(self.player.queue)
            total_songs = len(songs)
            total_pages = max(1, (total_songs + self.playlist_per_page - 1) // self.playlist_per_page)
            
            # 計算新頁碼
            if action == PaginationView.ACTION_PREVIOUS_PAGE:
                self.current_playlist_page = max(1, self.current_playlist_page - 1)
            else:
                self.current_playlist_page = min(total_pages, self.current_playlist_page + 1)
            
            # 建立嵌入
            embed = self.embed_builder.playlist_embed(
                songs=songs,
                current_index=self.player.queue.current_index,
                page=self.current_playlist_page,
                per_page=self.playlist_per_page,
            )
            
            # 更新按鈕
            pagination_view = PaginationView(
                button_callback=self._pagination_callback,
                timeout_callback=self._playlist_timeout_callback,
                current_page=self.current_playlist_page,
                total_pages=total_pages,
            )
            
            self.playlist_message = await self._edit_message_safely(
                self.playlist_message,
                embed=embed,
                view=pagination_view,
            )
            
        except Exception as e:
            logger.exception(f"翻頁時發生錯誤: {e}")
    
    async def _playlist_timeout_callback(self):
        """播放清單視圖超時"""
        if self.playlist_message:
            try:
                self.playlist_message = await self._edit_message_safely(
                    self.playlist_message,
                    view=None,
                )
            except:
                pass
    
    @app_commands.command(name="音樂-清空", description="清空播放清單")
    @app_commands.guild_only()
    async def clear_playlist(self, interaction: discord.Interaction):
        """清空播放清單"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 標記手動操作並停止播放
            self.player.state.mark_manual_operation()
            await self.player.stop()
            
            # 清空佇列
            cleared_count = await self.player.queue.clear()
            
            # 清空快取
            self.player.cache.clear()
            
            # 更新 UI
            if self.player_message:
                await self._edit_player_message(view=None)
            
            embed = self.embed_builder.clear_playlist_embed(cleared_count)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception(f"清理播放清單時發生錯誤: {e}")
            await interaction.followup.send("清理播放清單時發生錯誤，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-顯示播放器", description="重新顯示播放器控制面板（將播放器移至最新訊息）")
    @app_commands.guild_only()
    async def show_player(self, interaction: discord.Interaction):
        """重新顯示播放器"""
        await interaction.response.defer()
        
        if not self.player or not self.player.voice_client:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 標記舊訊息
            old_message = self.player_message
            
            # 建立新的播放器視圖
            self.player_view = create_player_view(
                player=self.player,
                button_callback=self._button_callback,
            )
            
            # 建立嵌入
            current_song = self.player.queue.current
            if current_song:
                embed = self.embed_builder.playing_embed(
                    song=current_song,
                    is_looping=self.player.queue.loop,
                    is_playing=self.player.is_playing,
                    current_time=self.player.state.current_position,
                )
            else:
                embed = self.embed_builder.error_embed("播放清單中無音樂")
                embed.description = "請透過 `/音樂-新增` 來新增音樂"
            
            # 發送新的播放器訊息
            self.player_message = await interaction.followup.send(
                embed=embed,
                view=self.player_view,
                wait=True,
            )
            self.player_message = await self._bind_persistent_message(self.player_message)
            
            # 更新舊訊息（如果存在）
            if old_message:
                try:
                    old_embed = discord.Embed(
                        title="🔀 播放器已移動",
                        description="請使用上方的新播放器控制面板",
                        color=discord.Color.greyple()
                    )
                    await self._edit_message_safely(old_message, embed=old_embed, view=None)
                except discord.NotFound:
                    pass  # 舊訊息已被刪除
                except discord.HTTPException:
                    pass  # 編輯失敗（可能訊息太舊）
            
        except Exception as e:
            logger.exception(f"顯示播放器時發生錯誤: {e}")
            await interaction.followup.send("顯示播放器時發生錯誤，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-跳轉", description="跳轉到播放清單中的指定歌曲")
    @app_commands.guild_only()
    @app_commands.rename(index="歌曲編號")
    @app_commands.describe(index="要跳轉到的歌曲編號（從 1 開始）")
    async def jump_to_song(self, interaction: discord.Interaction, index: int):
        """跳轉到指定歌曲"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 使用鎖保護整個跳轉操作
            async with self._play_lock:
                # 轉換為 0-based index
                target_index = index - 1
                
                # 嘗試跳轉
                song = self.player.queue.jump_to(target_index)
                
                if song is None:
                    await interaction.followup.send(
                        f"找不到編號為 {index} 的歌曲（範圍：1-{len(self.player.queue)}）",
                        ephemeral=True
                    )
                    return
                
                # 先標記手動操作，再停止當前播放
                self.player.state.mark_manual_operation()
                await self.player.stop()
                
                # 播放目標歌曲（使用內部方法避免重複取鎖）
                success = await self._play_song_internal(song)
                
                if success:
                    embed = self.embed_builder.info_embed(f"已跳轉到: {song.title}")
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(
                        f"歌曲 {song.title} 無法播放",
                        ephemeral=True
                    )
            
        except QueueError as e:
            await interaction.followup.send(e.user_message, ephemeral=True)
        except Exception as e:
            logger.exception(f"跳轉歌曲時發生錯誤: {e}")
            await interaction.followup.send("跳轉歌曲時發生錯誤，請稍後再試。", ephemeral=True)
    
    async def song_index_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[int]]:
        """歌曲編號自動完成"""
        if not self.player:
            return []
        
        try:
            choices = []
            for i, song in enumerate(self.player.queue):
                display = f"{i + 1}. {song.title}"
                if current in str(i + 1) or current.lower() in song.title.lower():
                    choices.append(app_commands.Choice(name=display[:100], value=i + 1))
            
            return choices[:25]
        except Exception as e:
            logger.error(f"Autocomplete 時發生錯誤: {e}")
            return []
    
    @app_commands.command(name="音樂-移除", description="移除播放清單中的特定音樂")
    @app_commands.guild_only()
    @app_commands.rename(index="歌曲編號")
    @app_commands.describe(index="要移除的歌曲編號")
    async def remove_song(self, interaction: discord.Interaction, index: int):
        """移除指定歌曲"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 轉換為 0-based index
            target_index = index - 1
            
            # 取得歌曲資訊
            songs = list(self.player.queue)
            if target_index < 0 or target_index >= len(songs):
                await interaction.followup.send(
                    f"找不到編號為 {index} 的歌曲",
                    ephemeral=True
                )
                return
            
            song = songs[target_index]
            
            # 移除
            await self.player.queue.remove(song.id)
            
            # 更新 UI
            await self._refresh_player_ui()
            
            embed = self.embed_builder.removed_song_embed(song)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception(f"移除歌曲時發生錯誤: {e}")
            await interaction.followup.send("移除歌曲時發生錯誤，請稍後再試。", ephemeral=True)
    
    # ==================== 背景任務 ====================
    
    @tasks.loop(seconds=EMBED_UPDATE_INTERVAL)
    async def update_embed(self):
        """定期更新播放器嵌入"""
        try:
            if not self.player or not self.player.is_playing:
                return
            
            await self._refresh_player_ui()
            
        except Exception as e:
            logger.error(f"更新播放器嵌入時發生錯誤: {e}")
    
    # ==================== 工具方法 ====================
    
    async def _connect_voice_with_retry(
        self, 
        channel: discord.VoiceChannel
    ) -> discord.VoiceClient | None:
        """
        帶重試的語音頻道連線
        
        Args:
            channel: 目標語音頻道
            
        Returns:
            VoiceClient 如果成功，None 如果失敗
        """
        last_error = None
        
        for attempt in range(1, VOICE_CONNECT_MAX_RETRIES + 1):
            try:
                logger.debug(f"嘗試連接語音頻道 (第 {attempt}/{VOICE_CONNECT_MAX_RETRIES} 次)")
                voice_client = await channel.connect()
                logger.info(f"成功連接語音頻道: {channel.name}")
                return voice_client
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"連接語音頻道失敗 (第 {attempt}/{VOICE_CONNECT_MAX_RETRIES} 次): "
                    f"{type(e).__name__}: {e}"
                )
                
                if attempt < VOICE_CONNECT_MAX_RETRIES:
                    await asyncio.sleep(VOICE_CONNECT_RETRY_DELAY)
        
        logger.error(f"連接語音頻道失敗，已達最大重試次數: {last_error}")
        return None
    
    async def _cleanup_resources(self):
        """ 清理所有資源"""
        try:
            # 停止背景任務（優先停止，避免繼續更新 UI）
            if self.update_embed_task.is_running():
                self.update_embed_task.stop()

            if self.voice_reconnect_loop.is_running():
                self.voice_reconnect_loop.stop()

            pending_background_tasks = [
                task for task in self._background_tasks
                if not task.done()
            ]
            for task in pending_background_tasks:
                task.cancel()
            if pending_background_tasks:
                await asyncio.gather(*pending_background_tasks, return_exceptions=True)
            self._background_tasks.clear()
            
            # 停止播放並斷開連線
            if self.player:
                # 標記手動操作並停止播放
                self.player.state.mark_manual_operation()
                await self.player.stop()
                
                # 斷開語音連線
                if self.player.voice_client:
                    await self.player.voice_client.disconnect()
                
                # 等待一下讓 FFmpeg 完全釋放檔案
                await asyncio.sleep(0.5)
                
                # 清空佇列
                await self.player.queue.clear()
                
                # 清理快取（先取消預載，再刪除檔案）
                await self.player.cache.cancel_all_preloads_and_wait()
                self.player.cache.clear()
            
            # 重置狀態
            self.player_message = None
            self.playlist_message = None
            self.player_view = None
            self.current_playlist_page = 1
            
            if self.manual_disconnect:
                self.last_voice_channel = None
            
            logger.debug("[MusicPlayerCog] 資源已清理")
            
        except Exception as e:
            logger.exception(f"清理資源時發生錯誤: {e}")

    async def _ensure_ytdlp_current(self) -> None:
        """依使用情況節流檢查，並避免多個指令同時執行 pip。"""
        now = time.monotonic()
        if now - (self.last_yt_dlp_check or 0) <= YTDLP_UPDATE_INTERVAL:
            return

        async with self._yt_dlp_update_lock:
            now = time.monotonic()
            if now - (self.last_yt_dlp_check or 0) <= YTDLP_UPDATE_INTERVAL:
                return

            await self._check_ytdlp_update()
            self.last_yt_dlp_check = time.monotonic()

    async def _check_ytdlp_update(self) -> None:
        """先用 pip dry-run 檢查差異，有更新時才安裝。"""
        try:
            logger.debug("[YT-DLP] 使用 pip dry-run 檢查執行期更新")

            stdout, _, returncode = await self._run_update_command(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "--disable-pip-version-check",
                    "--no-input",
                    "install",
                    "--dry-run",
                    "--quiet",
                    "--report",
                    "-",
                    "--upgrade",
                    "yt-dlp",
                    "yt-dlp-ejs",
                ],
                "pip dry-run yt-dlp yt-dlp-ejs",
            )

            if returncode != 0:
                logger.warning("[YT-DLP] pip dry-run 失敗，本次不執行更新")
                return

            try:
                report = json.loads(stdout)
            except json.JSONDecodeError as error:
                logger.warning(f"[YT-DLP] 無法解析 pip dry-run 報告: {error}")
                return

            pending_installs = report.get("install", [])
            if not pending_installs:
                logger.debug("[YT-DLP] yt-dlp 與 yt-dlp-ejs 已是最新版本")
                return

            versions = [
                f"{item.get('metadata', {}).get('name', 'unknown')}=="
                f"{item.get('metadata', {}).get('version', 'unknown')}"
                for item in pending_installs
            ]
            logger.info(f"[YT-DLP] 發現可用更新: {', '.join(versions)}")

            _, _, returncode = await self._run_update_command(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "--disable-pip-version-check",
                    "--no-input",
                    "install",
                    "--upgrade",
                    "yt-dlp",
                    "yt-dlp-ejs",
                ],
                "pip install --upgrade yt-dlp yt-dlp-ejs",
                timeout=300,
            )

            if returncode == 0:
                logger.info("[YT-DLP] pip 更新流程完成")
                return

            logger.warning("[YT-DLP] pip 更新失敗，退回 yt-dlp -U")
            await self._run_update_command(
                [sys.executable, "-m", "yt_dlp", "-U"],
                "yt-dlp -U",
            )
        except Exception as e:
            logger.error(f"[YT-DLP] 檢查更新時發生錯誤: {type(e).__name__}: {e}")

    async def _run_update_command(
        self,
        args: list[str],
        label: str,
        timeout: int = 120,
    ) -> tuple[str, str, int]:
        """執行更新命令，逾時時確保程序被回收"""
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self._terminate_process(process, label)
            raise

        stdout_str = stdout.decode(errors="replace").strip()
        stderr_str = stderr.decode(errors="replace").strip()

        logger.debug(f"[YT-DLP] {label} returncode={process.returncode}")
        if stdout_str:
            logger.debug(f"[YT-DLP] {label} stdout: {stdout_str}")
        if stderr_str:
            logger.debug(f"[YT-DLP] {label} stderr: {stderr_str}")

        return stdout_str, stderr_str, process.returncode or 0

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        label: str,
    ) -> None:
        """逾時時安全終止更新程序"""
        if process.returncode is not None:
            return

        logger.warning(f"[YT-DLP] 更新程序逾時，終止中: {label}")
        try:
            process.kill()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            logger.warning(f"[YT-DLP] 更新程序終止後仍未回收: {label}")
    
    # ==================== 事件監聯 ====================
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """監聽語音狀態變化，處理自動重連"""
        if member.id != self.bot.user.id:
            return
        
        # Bot 被動斷線
        if before.channel is not None and after.channel is None:
            # 只有在播放器活躍時才需要重連
            # 條件：非手動斷線 且 有播放器訊息 且 佇列有內容
            should_reconnect = (
                not self.manual_disconnect
                and self.player_message is not None
                and self.player is not None
                and len(self.player.queue) > 0
            )
            
            if should_reconnect:
                logger.warning("Bot 被動斷線，啟動自動重連")
                self.reconnect_attempts = 0
                if not self.voice_reconnect_loop.is_running():
                    self.voice_reconnect_loop.start()
            else:
                logger.debug("Bot 離開語音頻道（無需重連）")
    
    @tasks.loop(seconds=RECONNECT_INTERVAL)
    async def voice_reconnect_loop(self):
        """自動重連任務"""
        try:
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.error("自動重連已達最大次數，停止重連")
                self.voice_reconnect_loop.stop()
                
                if self.player_message:
                    embed = self.embed_builder.error_embed(
                        "❌ 無法自動重連語音頻道，請手動重新啟動播放器"
                    )
                    await self._edit_player_message(embed=embed, view=None)
                
                await self._cleanup_resources()
                return
            
            # 檢查是否已連接
            if self.player and self.player.voice_client and self.player.voice_client.is_connected():
                logger.info("已成功重連，停止重連任務")
                self.voice_reconnect_loop.stop()
                return
            
            logger.info(f"嘗試重連 (第 {self.reconnect_attempts + 1}/{self.max_reconnect_attempts} 次)")
            
            await self._attempt_reconnect()
            self.reconnect_attempts += 1
            
        except Exception as e:
            logger.exception(f"重連任務執行時發生錯誤: {e}")
    
    async def _attempt_reconnect(self):
        """嘗試重新連接"""
        if not self.last_voice_channel or not self.player:
            return
        
        # 使用帶重試的連線方法
        voice_client = await self._connect_voice_with_retry(self.last_voice_channel)
        
        if voice_client is None:
            logger.error("重連失敗：無法連接語音頻道")
            return
        
        await self.player.set_voice_client(voice_client)
        
        # 嘗試恢復播放
        current_song = self.player.queue.current
        if current_song:
            await self._play_song(current_song)
        
        logger.info("成功重連並恢復播放")


async def setup(bot: commands.Bot):
    """載入 Cog"""
    await bot.add_cog(MusicPlayerCog(bot))
