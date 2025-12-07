"""
音樂播放器模組 - 重構版本

使用純 asyncio 架構，提供:
- 無限歌曲佇列
- 滑動視窗快取
- 背景預載
- 準確時間追蹤
- 自動 FFmpeg 管理
"""

# Core
from .core.queue import MusicQueue, Song
from .core.state import PlaybackState
from .core.cache import CacheManager
from .core.player import MusicPlayer

# Downloader
from .downloader.yt_dlp import YTDLPDownloader

# FFmpeg
from .ffmpeg.manager import FFmpegManager, get_ffmpeg_path

# UI
from .ui.embeds import EmbedBuilder
from .ui.buttons import MusicPlayerView, PaginationView, create_player_view

# Utils
from .utils.errors import (
    MusicError,
    DownloadError,
    PlaybackError,
    QueueError,
    QueueEmptyError,
    VoiceConnectionError,
    SongUnavailableError,
)
from .utils.decorators import auto_refresh_ui, handle_errors

# Constants
from .constants import (
    # 快取
    CACHE_WINDOW_BEHIND,
    CACHE_WINDOW_AHEAD,
    CACHE_DIR,
    PRELOAD_TIMEOUT,
    # 下載
    YTDLP_EXTRACT_TIMEOUT,
    YTDLP_PLAYLIST_TIMEOUT,
    YTDLP_DOWNLOAD_TIMEOUT,
    YTDLP_UPDATE_INTERVAL,
    # UI
    PLAYLIST_PER_PAGE,
    PAGINATION_VIEW_TIMEOUT,
    PROGRESS_BAR_LENGTH,
    PROGRESS_BAR_FILLED,
    PROGRESS_BAR_EMPTY,
    EMBED_UPDATE_INTERVAL,
    # 重連
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_INTERVAL,
    # 防抖
    MANUAL_OPERATION_DEBOUNCE,
)

__all__ = [
    # Core
    "MusicQueue",
    "Song", 
    "PlaybackState",
    "CacheManager",
    "MusicPlayer",
    # Downloader
    "YTDLPDownloader",
    # FFmpeg
    "FFmpegManager",
    "get_ffmpeg_path",
    # UI
    "EmbedBuilder",
    "MusicPlayerView",
    "PaginationView",
    "create_player_view",
    # Utils
    "MusicError",
    "DownloadError",
    "PlaybackError",
    "QueueError",
    "QueueEmptyError",
    "VoiceConnectionError",
    "SongUnavailableError",
    "auto_refresh_ui",
    "handle_errors",
    # Constants
    "CACHE_WINDOW_BEHIND",
    "CACHE_WINDOW_AHEAD",
    "CACHE_DIR",
    "PRELOAD_TIMEOUT",
    "YTDLP_EXTRACT_TIMEOUT",
    "YTDLP_PLAYLIST_TIMEOUT",
    "YTDLP_DOWNLOAD_TIMEOUT",
    "YTDLP_UPDATE_INTERVAL",
    "PLAYLIST_PER_PAGE",
    "PAGINATION_VIEW_TIMEOUT",
    "PROGRESS_BAR_LENGTH",
    "PROGRESS_BAR_FILLED",
    "PROGRESS_BAR_EMPTY",
    "EMBED_UPDATE_INTERVAL",
    "RECONNECT_MAX_ATTEMPTS",
    "RECONNECT_INTERVAL",
    "MANUAL_OPERATION_DEBOUNCE",
]
