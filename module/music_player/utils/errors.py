"""
音樂播放器統一錯誤系統

所有錯誤都繼承自 MusicError，包含：
- message: 技術性錯誤訊息（給開發者 / log）
- user_message: 使用者友善的訊息（給 Discord 顯示）
"""

from typing import Optional


class MusicError(Exception):
    """音樂播放器錯誤基類"""
    
    def __init__(self, message: str, user_message: Optional[str] = None):
        self.message = message
        self.user_message = user_message or message
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return self.message


class DownloadError(MusicError):
    """下載失敗"""
    
    def __init__(self, message: str, url: Optional[str] = None):
        self.url = url
        super().__init__(
            message=message,
            user_message="下載失敗，請稍後再試"
        )


class PlaybackError(MusicError):
    """播放錯誤"""
    
    def __init__(self, message: str):
        super().__init__(
            message=message,
            user_message="播放時發生錯誤"
        )


class QueueError(MusicError):
    """佇列操作錯誤"""
    pass


class QueueEmptyError(QueueError):
    """佇列為空"""
    
    def __init__(self):
        super().__init__(
            message="Queue is empty",
            user_message="播放清單是空的"
        )


class VoiceConnectionError(MusicError):
    """語音連接錯誤"""
    
    def __init__(self, message: str):
        super().__init__(
            message=message,
            user_message="無法連接到語音頻道"
        )


class SongUnavailableError(MusicError):
    """
    歌曲無法播放（版權、私人、年齡限制等）
    
    reason 可為：
    - age_restricted: 年齡限制
    - copyright: 版權問題
    - private: 私人影片
    - unavailable: 已不可用
    - region_blocked: 地區限制
    - unknown: 未知原因
    """
    
    REASON_MESSAGES = {
        "age_restricted": "此影片有年齡限制，無法播放",
        "copyright": "此影片因版權問題被阻擋",
        "private": "此影片為私人或不公開",
        "unavailable": "此影片已不可用",
        "region_blocked": "此影片在您的地區無法觀看",
        "unknown": "影片無法播放",
    }
    
    def __init__(self, message: str, reason: str = "unknown", url: Optional[str] = None):
        self.reason = reason
        self.url = url
        user_message = self.REASON_MESSAGES.get(reason, self.REASON_MESSAGES["unknown"])
        super().__init__(message=message, user_message=user_message)


class TimeoutError(MusicError):
    """操作超時"""
    
    def __init__(self, operation: str, timeout: int):
        self.operation = operation
        self.timeout = timeout
        super().__init__(
            message=f"{operation} timed out after {timeout}s",
            user_message="操作超時，請稍後再試"
        )
