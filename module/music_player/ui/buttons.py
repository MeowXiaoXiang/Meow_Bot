"""
音樂播放器按鈕管理 - UI 層

提供兩種按鈕視圖:
- MusicPlayerView: 音樂播放控制按鈕 (上一首、暫停/播放、下一首、循環、離開)
- PaginationView: 播放清單翻頁按鈕
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Awaitable, Any
from discord.ui import View, Button
from discord import ButtonStyle, Interaction
from loguru import logger

from ..constants import PAGINATION_VIEW_TIMEOUT

if TYPE_CHECKING:
    from ..core.player import MusicPlayer

# 按鈕動作類型
type ButtonAction = str
type ButtonCallback = Callable[[Interaction, ButtonAction], Awaitable[Any]]


class MusicPlayerView(View):
    """
    音樂播放器控制按鈕視圖
    
    包含五個按鈕:
    - previous: 上一首 (⬅️)
    - play_pause: 播放/暫停 (▶️/⏸️)
    - next: 下一首 (➡️)
    - loop: 循環模式切換 (🔁/🔂)
    - leave: 離開語音頻道 (🚪)
    """
    
    # 按鈕 custom_id 常數
    ACTION_PREVIOUS = "music_previous"
    ACTION_PLAY_PAUSE = "music_play_pause"
    ACTION_NEXT = "music_next"
    ACTION_LOOP = "music_loop"
    ACTION_LEAVE = "music_leave"
    
    def __init__(
        self,
        *,
        button_callback: ButtonCallback | None = None,
        is_playing: bool = False,
        is_looping: bool = False,
    ):
        """
        初始化音樂播放器按鈕視圖
        
        Args:
            button_callback: 按鈕點擊回調函數，接收 (interaction, action)
            is_playing: 初始播放狀態
            is_looping: 初始循環狀態
        """
        super().__init__(timeout=None)  # 永不過期
        self.button_callback = button_callback
        self._is_playing = is_playing
        self._is_looping = is_looping
        
        # 創建按鈕
        self._create_buttons()
        
        logger.debug("[MusicPlayerView] 初始化完成")
    
    def _create_buttons(self) -> None:
        """創建所有控制按鈕"""
        # 上一首按鈕
        self.previous_button = Button(
            emoji="⬅️",
            style=ButtonStyle.secondary,
            custom_id=self.ACTION_PREVIOUS,
            row=0
        )
        self.previous_button.callback = self._handle_button
        self.add_item(self.previous_button)
        
        # 播放/暫停按鈕
        self.play_pause_button = Button(
            emoji="⏸️" if self._is_playing else "▶️",
            style=ButtonStyle.primary,
            custom_id=self.ACTION_PLAY_PAUSE,
            row=0
        )
        self.play_pause_button.callback = self._handle_button
        self.add_item(self.play_pause_button)
        
        # 下一首按鈕
        self.next_button = Button(
            emoji="➡️",
            style=ButtonStyle.secondary,
            custom_id=self.ACTION_NEXT,
            row=0
        )
        self.next_button.callback = self._handle_button
        self.add_item(self.next_button)
        
        # 循環按鈕
        self.loop_button = Button(
            emoji="🔂" if self._is_looping else "🔁",
            style=ButtonStyle.success if self._is_looping else ButtonStyle.secondary,
            custom_id=self.ACTION_LOOP,
            row=0
        )
        self.loop_button.callback = self._handle_button
        self.add_item(self.loop_button)
        
        # 離開按鈕
        self.leave_button = Button(
            emoji="🚪",
            style=ButtonStyle.danger,
            custom_id=self.ACTION_LEAVE,
            row=0
        )
        self.leave_button.callback = self._handle_button
        self.add_item(self.leave_button)
    
    async def _handle_button(self, interaction: Interaction) -> None:
        """
        處理按鈕點擊事件
        
        Args:
            interaction: Discord 互動對象
        """
        await interaction.response.defer()
        
        action = interaction.data.get("custom_id") if interaction.data else None
        if not action:
            logger.error("[MusicPlayerView] 無法取得按鈕 custom_id")
            return
        
        logger.debug(f"[MusicPlayerView] 按鈕點擊: {action}")
        
        if self.button_callback:
            try:
                await self.button_callback(interaction, action)
            except Exception as e:
                logger.exception(f"[MusicPlayerView] 按鈕回調執行失敗: {action}, {e}")
        else:
            logger.warning("[MusicPlayerView] 未設置 button_callback")

    def update_play_pause(self, is_playing: bool) -> None:
        """
        更新播放/暫停按鈕狀態
        
        Args:
            is_playing: 是否正在播放
        """
        self._is_playing = is_playing
        self.play_pause_button.emoji = "⏸️" if is_playing else "▶️"
        logger.debug(f"[MusicPlayerView] 更新播放狀態: {'播放中' if is_playing else '已暫停'}")
    
    def update_loop(self, is_looping: bool) -> None:
        """
        更新循環按鈕狀態
        
        Args:
            is_looping: 是否循環
        """
        self._is_looping = is_looping
        self.loop_button.emoji = "🔂" if is_looping else "🔁"
        self.loop_button.style = ButtonStyle.success if is_looping else ButtonStyle.secondary
        logger.debug(f"[MusicPlayerView] 更新循環狀態: {'循環開啟' if is_looping else '循環關閉'}")
    
    def update_navigation(self, has_previous: bool, has_next: bool) -> None:
        """
        更新導航按鈕狀態（在循環模式下總是可用）
        
        Args:
            has_previous: 是否有上一首
            has_next: 是否有下一首
        """
        # 如果循環模式開啟且有歌曲，導航按鈕永遠可用
        if self._is_looping:
            self.previous_button.disabled = False
            self.next_button.disabled = False
        else:
            self.previous_button.disabled = not has_previous
            self.next_button.disabled = not has_next
        
        logger.debug(
            f"[MusicPlayerView] 更新導航狀態: "
            f"上一首={'啟用' if not self.previous_button.disabled else '禁用'}, "
            f"下一首={'啟用' if not self.next_button.disabled else '禁用'}"
        )
    
    def disable_all(self) -> None:
        """禁用所有按鈕"""
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True
        logger.debug("[MusicPlayerView] 已禁用所有按鈕")


class PaginationView(View):
    """
    播放清單翻頁按鈕視圖
    
    包含兩個按鈕:
    - previous_page: 上一頁 (⬅️)
    - next_page: 下一頁 (➡️)
    """
    
    ACTION_PREVIOUS_PAGE = "pagination_previous"
    ACTION_NEXT_PAGE = "pagination_next"
    
    def __init__(
        self,
        *,
        button_callback: ButtonCallback | None = None,
        timeout_callback: TimeoutCallback | None = None,
        timeout: float = PAGINATION_VIEW_TIMEOUT,
        current_page: int = 1,
        total_pages: int = 1,
    ):
        """
        初始化翻頁按鈕視圖
        
        Args:
            button_callback: 按鈕點擊回調函數
            timeout_callback: 超時回調函數
            timeout: 超時時間（秒）
            current_page: 當前頁碼（從 1 開始）
            total_pages: 總頁數
        """
        super().__init__(timeout=timeout)
        self.button_callback = button_callback
        self.timeout_callback = timeout_callback
        self.current_page = current_page
        self.total_pages = total_pages
        
        # 創建按鈕
        self._create_buttons()
        self._update_button_states()
        
        logger.debug(f"[PaginationView] 初始化: 第 {current_page}/{total_pages} 頁")
    
    def _create_buttons(self) -> None:
        """創建翻頁按鈕"""
        # 上一頁按鈕
        self.previous_button = Button(
            emoji="⬅️",
            style=ButtonStyle.secondary,
            custom_id=self.ACTION_PREVIOUS_PAGE,
            row=0
        )
        self.previous_button.callback = self._handle_button
        self.add_item(self.previous_button)
        
        # 下一頁按鈕
        self.next_button = Button(
            emoji="➡️",
            style=ButtonStyle.secondary,
            custom_id=self.ACTION_NEXT_PAGE,
            row=0
        )
        self.next_button.callback = self._handle_button
        self.add_item(self.next_button)
    
    def _update_button_states(self) -> None:
        """根據當前頁碼更新按鈕狀態"""
        self.previous_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
    
    async def _handle_button(self, interaction: Interaction) -> None:
        """處理按鈕點擊事件"""
        await interaction.response.defer()
        
        action = interaction.data.get("custom_id") if interaction.data else None
        if not action:
            logger.error("[PaginationView] 無法取得按鈕 custom_id")
            return
        
        logger.debug(f"[PaginationView] 按鈕點擊: {action}")
        
        if self.button_callback:
            try:
                await self.button_callback(interaction, action)
            except Exception as e:
                logger.exception(f"[PaginationView] 按鈕回調執行失敗: {action}, {e}")
    
    async def on_timeout(self) -> None:
        """處理視圖超時"""
        logger.debug("[PaginationView] 視圖已超時")
        if self.timeout_callback:
            try:
                await self.timeout_callback()
            except Exception as e:
                logger.exception(f"[PaginationView] 超時回調執行失敗: {e}")
        self.stop()
    
    def update_page(self, current_page: int, total_pages: int) -> None:
        """
        更新頁碼資訊
        
        Args:
            current_page: 當前頁碼
            total_pages: 總頁數
        """
        self.current_page = current_page
        self.total_pages = total_pages
        self._update_button_states()
        logger.debug(f"[PaginationView] 更新頁碼: 第 {current_page}/{total_pages} 頁")


def create_player_view(
    player: MusicPlayer,
    button_callback: ButtonCallback | None = None,
) -> MusicPlayerView:
    """
    工廠函數: 根據播放器狀態創建播放器視圖
    
    Args:
        player: 音樂播放器實例
        button_callback: 按鈕回調函數
        
    Returns:
        配置好的 MusicPlayerView 實例
    """
    view = MusicPlayerView(
        button_callback=button_callback,
        is_playing=player.is_playing,
        is_looping=player.queue.loop,
    )
    
    # 更新導航按鈕狀態
    view.update_navigation(
        has_previous=player.queue.current_index > 0,
        has_next=player.queue.current_index < len(player.queue) - 1,
    )
    
    return view
