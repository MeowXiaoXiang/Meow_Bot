"""
播放狀態追蹤

精確追蹤播放時間，解決「播放秒數與實際脫鉤」的問題。
使用時間戳計算而非累加，確保暫停/恢復後時間正確。
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlaybackState:
    """
    精確追蹤播放狀態
    
    使用方式：
        state = PlaybackState()
        state.start(duration=180)  # 開始播放 3 分鐘的歌
        
        # 隨時獲取當前播放位置
        print(state.current_position)  # 例如：45 秒
        print(state.progress_percentage)  # 例如：25%
        
        state.pause()   # 暫停
        state.resume()  # 恢復
        state.stop()    # 停止
    """
    
    is_playing: bool = False
    is_paused: bool = False
    
    # 私有屬性用於時間計算
    _start_time: float = field(default=0, repr=False)
    _pause_start: float = field(default=0, repr=False)
    _total_paused: float = field(default=0, repr=False)
    _duration: int = field(default=0, repr=False)
    
    # 當前歌曲資訊（可選）
    _current_song_id: Optional[str] = field(default=None, repr=False)
    
    # 手動操作時間戳（用於防止回調衝突）
    _last_manual_operation_time: float = field(default=0, repr=False)
    
    def start(self, duration: int, song_id: Optional[str] = None) -> None:
        """
        開始播放
        
        Args:
            duration: 歌曲總長度（秒）
            song_id: 可選的歌曲 ID（用於追蹤）
        """
        self.is_playing = True
        self.is_paused = False
        self._start_time = time.time()
        self._total_paused = 0
        self._duration = duration
        self._current_song_id = song_id
    
    def pause(self) -> bool:
        """
        暫停播放
        
        Returns:
            是否成功暫停（已暫停則返回 False）
        """
        if self.is_playing and not self.is_paused:
            self.is_paused = True
            self._pause_start = time.time()
            return True
        return False
    
    def resume(self) -> bool:
        """
        恢復播放
        
        Returns:
            是否成功恢復（未暫停則返回 False）
        """
        if self.is_paused:
            self.is_paused = False
            self._total_paused += time.time() - self._pause_start
            return True
        return False
    
    def stop(self) -> None:
        """停止播放，重置所有狀態"""
        self.is_playing = False
        self.is_paused = False
        self._start_time = 0
        self._pause_start = 0
        self._total_paused = 0
        self._current_song_id = None
    
    def reset(self) -> None:
        """完全重置（包括 duration）"""
        self.stop()
        self._duration = 0
    
    @property
    def current_position(self) -> int:
        """
        即時計算當前播放秒數
        
        Returns:
            當前播放位置（秒），範圍 [0, duration]
        """
        if not self.is_playing:
            return 0
        
        if self.is_paused:
            # 暫停時：計算到暫停那一刻的時間
            elapsed = self._pause_start - self._start_time - self._total_paused
        else:
            # 播放中：計算到現在的時間
            elapsed = time.time() - self._start_time - self._total_paused
        
        # 確保在有效範圍內
        return max(0, min(int(elapsed), self._duration))
    
    @property
    def remaining(self) -> int:
        """
        剩餘播放時間（秒）
        """
        return max(0, self._duration - self.current_position)
    
    @property
    def progress_percentage(self) -> float:
        """
        播放進度百分比
        
        Returns:
            進度百分比（0.0 - 100.0）
        """
        if self._duration <= 0:
            return 0.0
        return (self.current_position / self._duration) * 100
    
    @property
    def duration(self) -> int:
        """歌曲總長度（秒）"""
        return self._duration
    
    @property
    def current_song_id(self) -> Optional[str]:
        """當前播放的歌曲 ID"""
        return self._current_song_id
    
    @property
    def is_finished(self) -> bool:
        """是否播放完畢"""
        if not self.is_playing:
            return False
        return self.current_position >= self._duration
    
    def format_time(self, seconds: Optional[int] = None) -> str:
        """
        格式化時間為 MM:SS 或 HH:MM:SS
        
        Args:
            seconds: 要格式化的秒數，None 則使用當前位置
        """
        if seconds is None:
            seconds = self.current_position
        
        if seconds >= 3600:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}:{secs:02d}"
    
    @property
    def progress_bar(self) -> str:
        """
        生成進度條字串
        
        Returns:
            例如：「▓▓▓▓▓▓░░░░░░░░░」
        """
        total_blocks = 15
        filled = int((self.progress_percentage / 100) * total_blocks)
        empty = total_blocks - filled
        return "▓" * filled + "░" * empty
    
    @property
    def progress_display(self) -> str:
        """
        生成完整的進度顯示
        
        Returns:
            例如：「1:23 ▓▓▓▓▓░░░░░░░░░░ 3:45」
        """
        current = self.format_time(self.current_position)
        total = self.format_time(self._duration)
        return f"{current} {self.progress_bar} {total}"
    
    # === 手動操作追蹤 ===
    
    def mark_manual_operation(self) -> None:
        """
        標記一次手動操作
        
        用於防止手動操作後觸發的 on_song_end 回調造成重複切歌
        """
        self._last_manual_operation_time = time.time()
    
    @property
    def last_manual_operation_time(self) -> float:
        """上次手動操作的時間戳"""
        return self._last_manual_operation_time
