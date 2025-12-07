"""
音樂播放器 UI 層

提供 Discord 嵌入訊息和按鈕視圖
"""

from .embeds import EmbedBuilder
from .buttons import MusicPlayerView, PaginationView, create_player_view

__all__ = [
    "EmbedBuilder",
    "MusicPlayerView",
    "PaginationView",
    "create_player_view",
]
