"""
Discord Embed 生成器

負責生成各種情境的 Embed 訊息：
- 播放中
- 播放清單
- 新增/移除歌曲
- 錯誤訊息
"""

import discord
from typing import Optional, List, TYPE_CHECKING
from loguru import logger

from ..constants import (
    PROGRESS_BAR_LENGTH,
    PROGRESS_BAR_FILLED,
    PROGRESS_BAR_EMPTY,
)

if TYPE_CHECKING:
    from ..core.queue import Song
    from ..core.player import MusicPlayer


class EmbedBuilder:
    """
    Discord Embed 管理器
    
    使用方式：
        embeds = EmbedManager()
        embed = embeds.playing(song, is_playing=True, current_time=45, duration=180)
    """
    
    # 顏色定義
    COLOR_PLAYING = discord.Color.blurple()
    COLOR_PAUSED = discord.Color.orange()
    COLOR_SUCCESS = discord.Color.green()
    COLOR_ERROR = discord.Color.red()
    COLOR_INFO = discord.Color.blue()
    
    # === 播放相關 ===
    
    def playing(
        self,
        song: "Song",
        is_playing: bool = True,
        is_looping: bool = False,
        current_time: int = 0,
        index: Optional[int] = None,
    ) -> discord.Embed:
        """
        生成播放中的 Embed
        
        Args:
            song: 歌曲資訊
            is_playing: 是否正在播放
            is_looping: 是否循環播放
            current_time: 已播放秒數
            index: 在佇列中的編號（1-based）
        """
        try:
            status = "正在播放 ▶️" if is_playing else "已暫停 ⏸️"
            color = self.COLOR_PLAYING if is_playing else self.COLOR_PAUSED
            
            duration = song.duration
            progress_bar = self._create_progress_bar(current_time, duration)
            
            # 格式化時間
            current_str = self._format_time(current_time)
            duration_str = self._format_time(duration)
            
            embed = discord.Embed(color=color)
            
            # 作者
            embed.set_author(name=song.uploader, url=song.uploader_url or None)
            
            # 標題（含編號）
            title_text = f"{index}. " if index else ""
            title_text += song.title
            embed.description = f"[{title_text}]({song.url})"
            
            # 狀態欄位
            embed.add_field(
                name="狀態",
                value=f"{status}\n{current_str} / {duration_str}\n{progress_bar}",
                inline=False
            )
            
            # 縮圖
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            
            # Footer
            footer_text = f"循環播放: {'開啟 🔁' if is_looping else '關閉'}"
            embed.set_footer(text=footer_text)
            
            return embed
            
        except Exception as e:
            logger.error(f"生成播放 Embed 失敗: {e}")
            return self.error("無法顯示播放資訊")
    
    def player_embed(self, player: "MusicPlayer") -> discord.Embed:
        """
        根據 MusicPlayer 狀態生成 Embed
        
        這是一個便利方法，直接從 player 取得所有需要的資訊
        """
        song = player.current_song
        if not song:
            return self.info("沒有正在播放的歌曲", "播放清單是空的")
        
        return self.playing(
            song=song,
            is_playing=player.is_playing,
            is_looping=player.loop,
            current_time=player.state.current_position,
            index=player.queue.current_index
        )
    
    # === 清單相關 ===
    
    def playlist(
        self,
        songs: List["Song"],
        current_page: int,
        total_pages: int,
        total_songs: int,
        current_index: int,
        start_index: int = 1,
    ) -> discord.Embed:
        """
        生成播放清單 Embed
        
        Args:
            songs: 該頁的歌曲列表
            current_page: 當前頁碼
            total_pages: 總頁數
            total_songs: 總歌曲數
            current_index: 當前播放的編號（1-based）
            start_index: 該頁第一首的編號（1-based）
        """
        try:
            embed = discord.Embed(
                title="🎶 播放清單",
                color=self.COLOR_INFO
            )
            
            if not songs:
                embed.description = "目前播放清單中沒有音樂！"
            else:
                lines = []
                for i, song in enumerate(songs):
                    song_index = start_index + i
                    # 標記當前播放的歌曲
                    prefix = "▶️ " if song_index == current_index else ""
                    duration_str = self._format_time(song.duration)
                    lines.append(f"{prefix}{song_index}. [{song.title}]({song.url}) `{duration_str}`")
                
                embed.description = "\n".join(lines)
            
            embed.set_footer(
                text=f"頁數: {current_page}/{total_pages} | 總歌曲數: {total_songs}"
            )
            
            return embed
            
        except Exception as e:
            logger.error(f"生成播放清單 Embed 失敗: {e}")
            return self.error("無法顯示播放清單")
    
    def playlist_from_page(self, page_data: dict) -> discord.Embed:
        """
        從 MusicQueue.get_page() 的結果生成 Embed
        """
        return self.playlist(
            songs=page_data["songs"],
            current_page=page_data["current_page"],
            total_pages=page_data["total_pages"],
            total_songs=page_data["total_songs"],
            current_index=page_data["current_index"],
            start_index=page_data.get("start_index", 1)
        )
    
    # === 操作結果 ===
    
    def added_song(self, song: "Song", queue_position: Optional[int] = None) -> discord.Embed:
        """
        生成新增歌曲成功的 Embed
        """
        try:
            embed = discord.Embed(
                title="✅ 已新增歌曲",
                description=f"[{song.title}]({song.url})",
                color=self.COLOR_SUCCESS
            )
            embed.set_author(name=song.uploader, url=song.uploader_url or None)
            
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            
            # 顯示位置和時長
            info_parts = []
            if queue_position:
                info_parts.append(f"位置: #{queue_position}")
            info_parts.append(f"時長: {self._format_time(song.duration)}")
            embed.add_field(name="資訊", value=" | ".join(info_parts), inline=False)
            
            return embed
            
        except Exception as e:
            logger.error(f"生成新增歌曲 Embed 失敗: {e}")
            return self.success("已新增歌曲")
    
    def added_playlist(self, count: int, playlist_title: Optional[str] = None) -> discord.Embed:
        """
        生成新增播放清單成功的 Embed
        """
        title = playlist_title or "播放清單"
        return discord.Embed(
            title="✅ 已新增播放清單",
            description=f"從 **{title}** 新增了 **{count}** 首歌曲",
            color=self.COLOR_SUCCESS
        )
    
    def removed_song(self, song: "Song") -> discord.Embed:
        """
        生成移除歌曲成功的 Embed
        """
        embed = discord.Embed(
            title="🗑️ 已移除歌曲",
            description=f"[{song.title}]({song.url})",
            color=discord.Color.orange()
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return embed
    
    def cleared_playlist(self, count: int) -> discord.Embed:
        """
        生成清空播放清單成功的 Embed
        """
        return discord.Embed(
            title="🗑️ 已清空播放清單",
            description=f"已移除 **{count}** 首歌曲",
            color=discord.Color.orange()
        )
    
    def jumped_to(self, song: "Song", index: int) -> discord.Embed:
        """
        生成跳轉成功的 Embed
        """
        return discord.Embed(
            title="⏭️ 已跳轉",
            description=f"跳轉到第 **{index}** 首: [{song.title}]({song.url})",
            color=self.COLOR_SUCCESS
        )
    
    # === 通用訊息 ===
    
    def success(self, message: str, description: str = None) -> discord.Embed:
        """成功訊息"""
        embed = discord.Embed(
            title=f"✅ {message}",
            description=description,
            color=self.COLOR_SUCCESS
        )
        return embed
    
    def error(self, message: str, description: str = None) -> discord.Embed:
        """錯誤訊息"""
        embed = discord.Embed(
            title=f"❌ {message}",
            description=description,
            color=self.COLOR_ERROR
        )
        return embed
    
    def info(self, message: str, description: str = None) -> discord.Embed:
        """資訊訊息"""
        embed = discord.Embed(
            title=f"ℹ️ {message}",
            description=description,
            color=self.COLOR_INFO
        )
        return embed
    
    def warning(self, message: str, description: str = None) -> discord.Embed:
        """警告訊息"""
        embed = discord.Embed(
            title=f"⚠️ {message}",
            description=description,
            color=discord.Color.gold()
        )
        return embed
    
    def loading(self, message: str = "處理中...") -> discord.Embed:
        """載入中訊息"""
        return discord.Embed(
            title=f"⏳ {message}",
            color=self.COLOR_INFO
        )
    
    # === 內部方法 ===
    
    @staticmethod
    def _create_progress_bar(current: int | float, total: int | float, length: int = PROGRESS_BAR_LENGTH) -> str:
        """
        建立進度條（使用方塊風格，支援 int 和 float）
        
        Args:
            current: 當前位置（秒）
            total: 總長度（秒）
            length: 進度條長度
        """
        # 轉換為數值型別並處理邊界
        current = float(current) if current is not None else 0
        total = float(total) if total is not None else 0
        
        if total <= 0:
            return PROGRESS_BAR_EMPTY * length
        
        progress = min(int((current / total) * length), length)
        bar = PROGRESS_BAR_FILLED * progress + PROGRESS_BAR_EMPTY * (length - progress)
        return bar
    
    @staticmethod
    def _format_time(seconds: int | float) -> str:
        """
        格式化時間（支援 int 和 float，適配各平台 yt-dlp 回傳格式）
        
        Args:
            seconds: 秒數（int 或 float）
        """
        # 轉換為整數，處理 float 類型（某些平台如 Dailymotion 會回傳 float）
        seconds = int(seconds) if seconds is not None else 0
        
        if seconds >= 3600:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}:{secs:02d}"
    
    # === 別名方法 (為了相容性) ===
    
    def playing_embed(
        self,
        song: "Song",
        is_playing: bool = True,
        is_looping: bool = False,
        current_time: int = 0,
        index: Optional[int] = None,
    ) -> discord.Embed:
        """playing 的別名"""
        return self.playing(song, is_playing, is_looping, current_time, index)
    
    def playlist_embed(
        self,
        songs: List["Song"],
        current_index: int,
        page: int = 1,
        per_page: int = 5,
    ) -> discord.Embed:
        """
        生成播放清單 Embed（簡化版介面）
        
        Args:
            songs: 完整的歌曲列表
            current_index: 當前播放的索引（0-based）
            page: 頁碼（1-based）
            per_page: 每頁歌曲數
        """
        total_songs = len(songs)
        total_pages = max(1, (total_songs + per_page - 1) // per_page)
        
        # 確保頁碼合法
        page = max(1, min(page, total_pages))
        
        # 計算該頁的歌曲範圍
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_songs)
        page_songs = songs[start_idx:end_idx]
        
        return self.playlist(
            songs=page_songs,
            current_page=page,
            total_pages=total_pages,
            total_songs=total_songs,
            current_index=current_index + 1,  # 轉為 1-based
            start_index=start_idx + 1,  # 轉為 1-based
        )
    
    def added_song_embed(self, song: "Song", queue_position: Optional[int] = None) -> discord.Embed:
        """added_song 的別名"""
        return self.added_song(song, queue_position)
    
    def added_songs_embed(self, count: int, playlist_title: Optional[str] = None) -> discord.Embed:
        """added_playlist 的別名"""
        return self.added_playlist(count, playlist_title)
    
    def removed_song_embed(self, song: "Song") -> discord.Embed:
        """removed_song 的別名"""
        return self.removed_song(song)
    
    def clear_playlist_embed(self, count: int = 0) -> discord.Embed:
        """cleared_playlist 的別名"""
        return self.cleared_playlist(count)
    
    def error_embed(self, message: str, description: str = None) -> discord.Embed:
        """error 的別名"""
        return self.error(message, description)
    
    def info_embed(self, message: str, description: str = None) -> discord.Embed:
        """info 的別名"""
        return self.info(message, description)
    
    def downloading_embed(self, song: "Song") -> discord.Embed:
        """生成下載中的 Embed"""
        embed = discord.Embed(
            title=f"⏳ 下載中...",
            description=f"正在下載: [{song.title}]({song.url})",
            color=self.COLOR_INFO
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return embed
