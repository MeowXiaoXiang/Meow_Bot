"""
音樂播放器核心

整合所有播放相關功能：
- 播放控制（播放、暫停、停止、上/下一首）
- 狀態追蹤（使用 PlaybackState）
- 佇列管理（使用 MusicQueue）
- 快取管理（使用 CacheManager）
- 下載管理（使用 YTDLPDownloader）
"""

import asyncio
import discord
from pathlib import Path
from typing import Optional, Callable, Awaitable, TYPE_CHECKING
from loguru import logger

from .state import PlaybackState
from .queue import MusicQueue, Song
from .cache import CacheManager
from ..downloader.yt_dlp import YTDLPDownloader
from ..utils.errors import (
    MusicError,
    PlaybackError,
    VoiceConnectionError,
    QueueEmptyError,
)

if TYPE_CHECKING:
    from discord import VoiceClient


class MusicPlayer:
    """
    音樂播放器核心類別
    
    整合佇列、快取、下載、播放控制等功能。
    
    使用方式：
        player = MusicPlayer(
            ffmpeg_path="/path/to/ffmpeg",
            cache_dir="./cache",
            on_song_change=my_callback
        )
        
        await player.connect(voice_channel)
        await player.add_song("https://www.youtube.com/watch?v=xxx")
        await player.play()
    """
    
    def __init__(
        self,
        ffmpeg_path: str = None,
        cache_dir: str = "./temp/music",
        loop: Optional[asyncio.AbstractEventLoop] = None,
        on_song_change: Optional[Callable[["MusicPlayer"], Awaitable[None]]] = None,
        on_song_end: Optional[Callable[[], Awaitable[None]]] = None,
        on_error: Optional[Callable[[MusicError], Awaitable[None]]] = None,
        downloader: Optional["YTDLPDownloader"] = None,
    ):
        """
        初始化音樂播放器
        
        Args:
            ffmpeg_path: FFmpeg 執行檔路徑
            cache_dir: 快取目錄路徑
            loop: 事件循環（可選，會自動取得）
            on_song_change: 歌曲切換時的回調
            on_song_end: 歌曲自然結束時的回調
            on_error: 錯誤發生時的回調
            downloader: 下載器（可選，若提供則使用外部下載器）
        """
        self.ffmpeg_path = ffmpeg_path
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 事件循環（若未提供則嘗試取得當前運行中的循環）
        self._loop = loop or asyncio.get_running_loop()
        
        # 回調
        self._on_song_change = on_song_change
        self._on_song_end = on_song_end
        self._on_error = on_error
        
        # 核心元件
        self.queue = MusicQueue()
        self.state = PlaybackState()
        self.cache = CacheManager(
            cache_dir=str(self.cache_dir),
            window_behind=2,
            window_ahead=3
        )
        
        # 下載器（可使用外部提供的或內部建立的）
        if downloader:
            self.downloader = downloader
        elif ffmpeg_path:
            self.downloader = YTDLPDownloader(
                download_dir=str(self.cache_dir),
                ffmpeg_path=ffmpeg_path
            )
        else:
            self.downloader = None
        
        # Discord 語音客戶端
        self._voice_client: Optional["VoiceClient"] = None
        
        # 內部狀態
        self._is_stopping = False  # 防止遞迴呼叫
        
        logger.debug(f"MusicPlayer 初始化: cache_dir={cache_dir}")
    
    # === 屬性 ===
    
    @property
    def voice_client(self) -> Optional["VoiceClient"]:
        """Discord 語音客戶端"""
        return self._voice_client
    
    @property
    def is_connected(self) -> bool:
        """是否已連接語音頻道"""
        return self._voice_client is not None and self._voice_client.is_connected()
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        return self.state.is_playing and not self.state.is_paused
    
    @property
    def is_paused(self) -> bool:
        """是否已暫停"""
        return self.state.is_paused
    
    @property
    def current_song(self) -> Optional[Song]:
        """當前播放的歌曲"""
        return self.queue.current_song
    
    @property
    def loop(self) -> bool:
        """是否啟用循環播放"""
        return self.queue.loop
    
    @loop.setter
    def loop(self, value: bool) -> None:
        """設定循環播放"""
        self.queue.loop = value
    
    # === 連接管理 ===
    
    async def connect(self, channel: discord.VoiceChannel) -> None:
        """
        連接到語音頻道
        
        Args:
            channel: Discord 語音頻道
        """
        try:
            if self._voice_client and self._voice_client.is_connected():
                # 如果已經在同一個頻道，不需要重新連接
                if self._voice_client.channel.id == channel.id:
                    logger.debug("已經在目標頻道")
                    return
                # 移動到新頻道
                await self._voice_client.move_to(channel)
            else:
                self._voice_client = await channel.connect()
            
            logger.debug(f"已連接到語音頻道: {channel.name}")
            
        except Exception as e:
            logger.error(f"連接語音頻道失敗: {e}")
            raise VoiceConnectionError(str(e))
    
    async def disconnect(self) -> None:
        """
        斷開語音連接
        """
        if self._voice_client:
            await self.stop()
            await self._voice_client.disconnect()
            self._voice_client = None
            logger.debug("已斷開語音連接")
    
    async def set_voice_client(self, voice_client: "VoiceClient") -> None:
        """
        設定語音客戶端
        
        支援外部管理連接的情況（例如 cog 自行連接語音頻道）
        """
        self._voice_client = voice_client
    
    # === 播放控制 ===
    
    async def play(self, song: Optional[Song] = None) -> Optional[Song]:
        """
        開始播放歌曲
        
        Args:
            song: 要播放的歌曲。若為 None，則播放當前佇列的歌曲
        
        Returns:
            正在播放的歌曲，若無法播放則返回 None
        """
        if not self.is_connected:
            raise VoiceConnectionError("未連接到語音頻道")
        
        # 如果提供了 song，使用它；否則使用當前歌曲
        if song is None:
            song = self.queue.current_song
        
        if not song:
            logger.warning("佇列為空，無法播放")
            return None
        
        # 確保有快取
        cache_path = self.cache.get(song.id)
        if cache_path:
            song.cached_path = cache_path
        
        if not song.cached_path or not Path(song.cached_path).exists():
            logger.debug(f"下載中: {song.title}")
            if self.downloader:
                info, path = await self.downloader.download(song.url, song.id)
                if not path:
                    logger.error(f"下載失敗: {song.title}")
                    # 不自動跳歌，讓呼叫者處理
                    return None
                song.cached_path = str(path)
            else:
                logger.error("無法下載：downloader 未設定")
                return None
        
        # 停止當前播放
        if self._voice_client.is_playing():
            self._voice_client.stop()
        
        # 建立音訊源
        try:
            audio_source = discord.FFmpegOpusAudio(
                source=song.cached_path,
                executable=self.ffmpeg_path
            )
        except Exception as e:
            logger.error(f"建立音訊源失敗: {e}")
            raise PlaybackError(str(e))
        
        # 開始播放
        self._voice_client.play(
            audio_source,
            after=self._on_playback_finished
        )
        
        # 更新狀態
        self.state.start(duration=song.duration, song_id=song.id)
        
        logger.debug(f"開始播放: {song.title}")
        
        # 觸發快取管理（預載下幾首）
        asyncio.create_task(
            self.cache.on_song_change(
                self.queue.all_songs,
                self.queue.current_index_zero_based,
                self.downloader
            )
        )
        
        # 觸發回調
        if self._on_song_change:
            asyncio.create_task(self._safe_callback(self._on_song_change))
        
        return song
    
    async def pause(self) -> bool:
        """
        暫停播放
        
        Returns:
            是否成功暫停
        """
        if not self.is_connected:
            return False
        
        if self._voice_client.is_playing():
            self._voice_client.pause()
            self.state.pause()
            logger.debug("已暫停")
            return True
        
        return False
    
    async def resume(self) -> bool:
        """
        恢復播放
        
        Returns:
            是否成功恢復
        """
        if not self.is_connected:
            return False
        
        if self._voice_client.is_paused():
            self._voice_client.resume()
            self.state.resume()
            logger.debug("已恢復")
            return True
        
        return False
    
    async def toggle_pause(self) -> bool:
        """
        切換暫停/播放狀態
        
        Returns:
            切換後是否為暫停狀態
        """
        if self.is_paused:
            await self.resume()
            return False
        else:
            await self.pause()
            return True
    
    async def stop(self) -> None:
        """
        停止播放並重置狀態
        """
        self._is_stopping = True
        
        if self._voice_client and self._voice_client.is_playing():
            self._voice_client.stop()
        
        self.state.stop()
        
        self._is_stopping = False
        logger.debug("已停止")
    
    async def next(self) -> Optional[Song]:
        """
        播放下一首
        
        Returns:
            下一首歌曲，若無則返回 None
        """
        song = self.queue.next()
        if song:
            return await self.play()
        else:
            logger.debug("沒有下一首了")
            await self.stop()
            return None
    
    async def previous(self) -> Optional[Song]:
        """
        播放上一首
        
        Returns:
            上一首歌曲，若無則返回 None
        """
        song = self.queue.previous()
        if song:
            return await self.play()
        else:
            logger.debug("沒有上一首了")
            return None
    
    async def jump_to(self, index: int) -> Optional[Song]:
        """
        跳轉到指定編號播放
        
        Args:
            index: 1-based 編號
        
        Returns:
            目標歌曲，若索引無效則返回 None
        """
        song = self.queue.jump_to(index)
        if song:
            return await self.play()
        else:
            logger.warning(f"無效的編號: {index}")
            return None
    
    # === 佇列操作 ===
    
    async def add_song(self, url: str, requester_id: Optional[int] = None) -> Optional[Song]:
        """
        新增歌曲到佇列
        
        Args:
            url: 影片 URL
            requester_id: 點歌者的 Discord 用戶 ID
        
        Returns:
            新增的歌曲，失敗返回 None
        """
        # 提取資訊
        info = await self.downloader.extract_info(url)
        if not info:
            return None
        if info.get("success") is False:
            logger.warning(f"無法取得資訊: {info.get('display_message')}")
            return None
        
        # 建立 Song 物件
        song = Song(
            id=info["id"],
            title=info["title"],
            url=info["url"],
            duration=info["duration"],
            uploader=info["uploader"],
            uploader_url=info.get("uploader_url", ""),
            thumbnail=info.get("thumbnail", ""),
            requester_id=requester_id
        )
        
        # 新增到佇列
        await self.queue.add(song)
        
        return song
    
    async def add_playlist(self, url: str, requester_id: Optional[int] = None) -> list[Song]:
        """
        新增播放清單到佇列
        
        Args:
            url: 播放清單 URL
            requester_id: 點歌者的 Discord 用戶 ID
        
        Returns:
            新增的歌曲列表
        """
        # 提取播放清單
        entries = await self.downloader.extract_playlist(url)
        if not entries:
            return []
        
        songs = []
        for info in entries:
            song = Song(
                id=info["id"],
                title=info["title"],
                url=info["url"],
                duration=info.get("duration", 0),
                uploader=info.get("uploader", "未知"),
                uploader_url=info.get("uploader_url", ""),
                thumbnail=info.get("thumbnail", ""),
                requester_id=requester_id
            )
            songs.append(song)
        
        # 批次新增
        await self.queue.add_many(songs)
        
        return songs
    
    async def remove_song(self, index: int) -> Optional[Song]:
        """
        移除指定編號的歌曲
        
        Args:
            index: 1-based 編號
        
        Returns:
            被移除的歌曲
        """
        return await self.queue.remove(index)
    
    async def clear_queue(self) -> int:
        """
        清空佇列
        
        Returns:
            被清空的歌曲數量
        """
        count = await self.queue.clear()
        self.cache.clear_all()
        return count
    
    # === 狀態查詢 ===
    
    def get_status(self) -> dict:
        """
        取得播放器完整狀態
        """
        return {
            "is_connected": self.is_connected,
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "loop": self.loop,
            "current_song": self.current_song,
            "current_position": self.state.current_position,
            "duration": self.state.duration,
            "progress_display": self.state.progress_display,
            "queue_size": self.queue.size,
            "current_index": self.queue.current_index,
        }
    
    # === 內部方法 ===
    
    def _on_playback_finished(self, error: Optional[Exception]) -> None:
        """
        播放完成的回調（由 Discord 音訊系統呼叫）
        
        注意：這是在另一個線程中執行的
        """
        if error:
            logger.error(f"播放錯誤: {error}")
        
        # 如果是手動停止，不自動播放下一首
        if self._is_stopping:
            return
        
        # 使用 call_soon_threadsafe 確保線程安全
        # 注意：必須使用儲存的 loop，因為此回調在音訊執行緒中執行
        if not self._loop:
            logger.error("無法處理歌曲結束：事件循環未設定")
            return
        
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._handle_song_end())
        )
    
    async def _handle_song_end(self) -> None:
        """
        處理歌曲自然結束
        """
        logger.debug("歌曲播放結束")
        self.state.stop()
        
        # 呼叫外部回調（如果有設定）
        if self._on_song_end:
            try:
                await self._on_song_end()
            except Exception as e:
                logger.error(f"on_song_end 回調執行失敗: {e}")
            # 讓外部處理下一首邏輯，不在這裡自動播放
            return
        
        # 沒有外部回調時，自動播放下一首
        if self.queue.has_next():
            await self.next()
        else:
            logger.info("播放清單已結束")
    
    async def _safe_callback(self, callback: Callable) -> None:
        """
        安全執行回調
        """
        try:
            await callback(self)
        except Exception as e:
            logger.error(f"回調執行失敗: {e}")
    
    async def _handle_error(self, error: MusicError) -> None:
        """
        處理錯誤
        """
        logger.error(f"播放器錯誤: {error.message}")
        if self._on_error:
            await self._safe_callback(lambda _: self._on_error(error))
    
    # === 清理 ===
    
    async def cleanup(self) -> None:
        """
        清理資源（程式結束時呼叫）
        """
        await self.disconnect()
        self.cache.cleanup()
        logger.info("MusicPlayer 已清理")
