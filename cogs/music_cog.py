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
)

# -------------------- Other --------------------
import asyncio
import os
import shutil
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
        
        # yt-dlp 更新檢查
        self.last_yt_dlp_check: float | None = None
        
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
        if not self.player:
            return
        
        logger.debug("[MusicPlayerCog] 歌曲自然結束，準備處理下一首")
        
        # 檢查是否有手動操作（避免重複觸發）
        if self.player.state.last_manual_operation_time:
            time_since_manual = time.time() - self.player.state.last_manual_operation_time
            if time_since_manual < MANUAL_OPERATION_DEBOUNCE:
                logger.debug(f"檢測到最近的手動操作 ({time_since_manual:.2f}s 前)，忽略自動切歌")
                return
        
        # 嘗試播放下一首
        try:
            await self._play_next_song()
        except MusicError as e:
            logger.error(f"[MusicPlayerCog] 播放下一首時發生錯誤: {e}")
            await self._show_error(e.user_message)
    
    async def _play_next_song(self):
        """播放下一首歌曲"""
        if not self.player:
            return
        
        queue = self.player.queue
        
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
        
        # 播放下一首
        await self._play_song(next_song)
    
    async def _play_song(self, song: Song):
        """
        播放指定歌曲
        
        Args:
            song: 要播放的歌曲
        """
        if not self.player:
            return
        
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
            
            # 播放
            await self.player.play(song)
            
            # 更新 UI
            await self._refresh_player_ui()
            
            # 觸發背景預載
            asyncio.create_task(self._preload_upcoming())
            
        except SongUnavailableError:
            logger.warning(f"歌曲無法播放: {song.title}")
            # 從佇列移除並嘗試下一首
            await self.player.queue.remove(song.id)
            await self._play_next_song()
    
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
            try:
                await self.player_message.edit(embed=embed, view=self.player_view)
            except discord.NotFound:
                logger.warning("播放器訊息已被刪除")
                self.player_message = None
            except discord.HTTPException as e:
                logger.error(f"更新播放器訊息失敗: {e}")
    
    async def _show_empty_queue(self):
        """顯示佇列為空的狀態"""
        embed = self.embed_builder.error_embed("播放清單中無音樂")
        embed.description = "請透過指令 [音樂-新增音樂到播放清單] 來新增音樂"
        
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
                await self._play_song(current_song)
    
    async def _handle_next(self):
        """處理下一首"""
        if not self.player:
            return
        
        await self.player.stop()
        self.player.state.mark_manual_operation()
        
        next_song = self.player.queue.next()
        if next_song:
            await self._play_song(next_song)
        else:
            # 非循環模式已到底，更新 UI 顯示停止狀態
            await self._refresh_player_ui()
    
    async def _handle_previous(self):
        """處理上一首"""
        if not self.player:
            return
        
        await self.player.stop()
        self.player.state.mark_manual_operation()
        
        prev_song = self.player.queue.previous()
        if prev_song:
            await self._play_song(prev_song)
        else:
            # 非循環模式已到頂，更新 UI 顯示停止狀態
            await self._refresh_player_ui()
    
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
                await message.edit(embed=embed, view=None)
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass
    
    # ==================== 斜線指令 ====================
    
    @app_commands.command(name="音樂-播放", description="啟動音樂播放器並播放指定的網址")
    @app_commands.rename(url="網址")
    @app_commands.describe(url="影片、音樂或播放清單的網址")
    async def start_player(self, interaction: discord.Interaction, url: str):
        """啟動播放器"""
        await interaction.response.defer()
        
        # 定期檢查 yt-dlp 更新
        if time.time() - (self.last_yt_dlp_check or 0) > YTDLP_UPDATE_INTERVAL:
            await self._check_ytdlp_update()
            self.last_yt_dlp_check = time.time()
        
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
        
        try:
            # 取得訊息
            response = await interaction.original_response()
            self.player_message = await response.channel.fetch_message(response.id)
            
            # 連接語音頻道
            channel = interaction.user.voice.channel
            voice_client = await channel.connect()
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
                await self.player_message.edit(content=None, embed=embed, view=None)
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
            
            # 下載
            _, file_path = await self.downloader.download(url)
            if not file_path:
                embed = self.embed_builder.error_embed("下載音樂失敗")
                await self.player_message.edit(content=None, embed=embed, view=None)
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
            await self.player_message.edit(content=None, embed=embed, view=self.player_view)
            
            # 啟動定期更新任務
            if not self.update_embed_task.is_running():
                self.update_embed_task.start()
                
        except Exception as e:
            logger.exception(f"啟動單曲播放時發生錯誤: {e}")
            embed = self.embed_builder.error_embed(f"錯誤: {e}")
            await self.player_message.edit(content=None, embed=embed, view=None)
    
    async def _handle_playlist_start(self, interaction: discord.Interaction, url: str):
        """處理播放清單啟動"""
        try:
            # 解析播放清單
            entries = await self.downloader.extract_playlist(url)
            if not entries:
                embed = self.embed_builder.error_embed("無法解析播放清單或播放清單為空")
                await self.player_message.edit(content=None, embed=embed, view=None)
                return
            
            # 建立 Song 物件並加入佇列
            songs = []
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
                songs.append(song)
                await self.player.queue.add(song)
            
            # 下載第一首
            first_song = songs[0]
            _, file_path = await self.downloader.download(first_song.url)
            if not file_path:
                embed = self.embed_builder.error_embed("下載第一首歌曲失敗")
                await self.player_message.edit(content=None, embed=embed, view=None)
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
            await self.player_message.edit(content=None, embed=embed, view=self.player_view)
            
            # 啟動定期更新任務
            if not self.update_embed_task.is_running():
                self.update_embed_task.start()
            
            # 背景預載
            asyncio.create_task(self._preload_upcoming())
            
        except Exception as e:
            logger.exception(f"啟動播放清單時發生錯誤: {e}")
            embed = self.embed_builder.error_embed(f"錯誤: {e}")
            await self.player_message.edit(content=None, embed=embed, view=None)
    
    @app_commands.command(name="音樂-新增", description="新增音樂到播放清單")
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
                self.player.queue._current_index = len(self.player.queue) - 1
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
                self.player.queue._current_index = len(self.player.queue) - added_count
                await self._play_song(first_new_song)
            
            # 更新按鈕
            await self._refresh_player_ui()
            
            # 背景預載
            asyncio.create_task(self._preload_upcoming())
            
        except Exception as e:
            logger.exception(f"新增播放清單時發生錯誤: {e}")
            await interaction.followup.send("無法新增播放清單，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-清單", description="查看當前播放清單")
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
                    await self.playlist_message.edit(view=None)
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
            await interaction.followup.send(embed=embed, view=pagination_view)
            response = await interaction.original_response()
            self.playlist_message = await response.channel.fetch_message(response.id)
            
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
            
            await self.playlist_message.edit(embed=embed, view=pagination_view)
            
        except Exception as e:
            logger.exception(f"翻頁時發生錯誤: {e}")
    
    async def _playlist_timeout_callback(self):
        """播放清單視圖超時"""
        if self.playlist_message:
            try:
                await self.playlist_message.edit(view=None)
            except:
                pass
    
    @app_commands.command(name="音樂-清空", description="清空播放清單")
    async def clear_playlist(self, interaction: discord.Interaction):
        """清空播放清單"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
            # 停止播放
            await self.player.stop()
            
            # 清空佇列
            await self.player.queue.clear()
            
            # 清空快取
            self.player.cache.clear()
            
            # 更新 UI
            if self.player_message:
                await self.player_message.edit(view=None)
            
            embed = self.embed_builder.clear_playlist_embed()
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception(f"清理播放清單時發生錯誤: {e}")
            await interaction.followup.send("清理播放清單時發生錯誤，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-顯示播放器", description="重新顯示播放器控制面板（將播放器移至最新訊息）")
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
                embed.description = "請透過指令 [音樂-新增音樂到播放清單] 來新增音樂"
            
            # 發送新的播放器訊息
            await interaction.followup.send(embed=embed, view=self.player_view)
            response = await interaction.original_response()
            self.player_message = await response.channel.fetch_message(response.id)
            
            # 更新舊訊息（如果存在）
            if old_message:
                try:
                    old_embed = discord.Embed(
                        title="🔀 播放器已移動",
                        description="請使用上方的新播放器控制面板",
                        color=discord.Color.greyple()
                    )
                    await old_message.edit(embed=old_embed, view=None)
                except discord.NotFound:
                    pass  # 舊訊息已被刪除
                except discord.HTTPException:
                    pass  # 編輯失敗（可能訊息太舊）
            
        except Exception as e:
            logger.exception(f"顯示播放器時發生錯誤: {e}")
            await interaction.followup.send("顯示播放器時發生錯誤，請稍後再試。", ephemeral=True)
    
    @app_commands.command(name="音樂-跳轉", description="跳轉到播放清單中的指定歌曲")
    @app_commands.rename(index="歌曲編號")
    @app_commands.describe(index="要跳轉到的歌曲編號（從 1 開始）")
    async def jump_to_song(self, interaction: discord.Interaction, index: int):
        """跳轉到指定歌曲"""
        await interaction.response.defer()
        
        if not self.player:
            await interaction.followup.send("播放器尚未啟動", ephemeral=True)
            return
        
        try:
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
            
            # 停止當前播放
            await self.player.stop()
            self.player.state.mark_manual_operation()
            
            # 播放目標歌曲
            await self._play_song(song)
            
            embed = self.embed_builder.info_embed(f"已跳轉到: {song.title}")
            await interaction.followup.send(embed=embed)
            
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
    
    @tasks.loop(seconds=15)
    async def update_embed(self):
        """定期更新播放器嵌入"""
        try:
            if not self.player or not self.player.is_playing:
                return
            
            await self._refresh_player_ui()
            
        except Exception as e:
            logger.error(f"更新播放器嵌入時發生錯誤: {e}")
    
    # ==================== 工具方法 ====================
    
    async def _cleanup_resources(self):
        """清理所有資源"""
        try:
            # 停止播放
            if self.player:
                await self.player.stop()
                if self.player.voice_client:
                    await self.player.voice_client.disconnect()
                await self.player.queue.clear()
                self.player.cache.clear()
            
            # 停止背景任務
            if self.update_embed_task.is_running():
                self.update_embed_task.stop()
            
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
    
    async def _check_ytdlp_update(self):
        """檢查 yt-dlp 更新"""
        try:
            yt_dlp_path = shutil.which("yt-dlp")
            if yt_dlp_path:
                logger.debug("[YT-DLP] 檢查 yt-dlp 更新...")
                process = await asyncio.create_subprocess_exec(
                    "yt-dlp", "-U",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
                logger.debug(f"[YT-DLP] 更新輸出: {stdout.decode().strip()}")
        except Exception as e:
            logger.error(f"[YT-DLP] 檢查更新時發生錯誤: {e}")
    
    # ==================== 事件監聽 ====================
    
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
            if not self.manual_disconnect:
                logger.warning("Bot 被動斷線，啟動自動重連")
                self.reconnect_attempts = 0
                if not self.voice_reconnect_loop.is_running():
                    self.voice_reconnect_loop.start()
    
    @tasks.loop(seconds=15)
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
                    await self.player_message.edit(embed=embed, view=None)
                
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
        
        try:
            voice_client = await self.last_voice_channel.connect()
            await self.player.set_voice_client(voice_client)
            
            # 嘗試恢復播放
            current_song = self.player.queue.current
            if current_song:
                await self._play_song(current_song)
            
            logger.info("成功重連並恢復播放")
            
        except Exception as e:
            logger.error(f"重連失敗: {e}")


async def setup(bot: commands.Bot):
    """載入 Cog"""
    await bot.add_cog(MusicPlayerCog(bot))
