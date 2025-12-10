"""
音樂佇列管理

特性：
- 無數量上限（允許無限點歌）
- 支援循環播放（第一首 ↔ 最後一首）
- 支援跳轉到指定編號
- 線程安全（使用 asyncio.Lock）
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, List
from loguru import logger


@dataclass
class Song:
    """
    歌曲資料結構
    
    所有欄位都是從 yt-dlp 提取的資訊
    """
    id: str                          # 影片 ID（例如 YouTube 的 video_id）
    title: str                       # 標題
    url: str                         # 原始 URL 或串流 URL
    duration: int                    # 時長（秒）
    uploader: str                    # 上傳者名稱
    uploader_url: str = ""           # 上傳者頻道連結
    thumbnail: str = ""              # 縮圖 URL
    requester_id: Optional[int] = None  # 點歌者的 Discord 用戶 ID
    
    # 快取相關
    cached_path: Optional[str] = field(default=None, repr=False)  # 本地快取路徑
    
    @property
    def is_cached(self) -> bool:
        """是否已下載到本地"""
        return self.cached_path is not None
    
    def format_duration(self) -> str:
        """格式化時長（處理 int 和 float 類型）"""
        # 確保是整數（某些平台會回傳 float）
        duration = int(self.duration) if self.duration is not None else 0
        
        if duration >= 3600:
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            seconds = duration % 60
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            minutes = duration // 60
            seconds = duration % 60
            return f"{minutes}:{seconds:02d}"


class MusicQueue:
    """
    音樂佇列管理器
    
    特性：
    - 無上限（允許無限點歌）
    - 支援跳轉到指定編號
    - 循環模式時，第一首可跳到最後一首，最後一首可跳到第一首
    
    使用方式：
        queue = MusicQueue()
        await queue.add(song)
        
        queue.next()      # 下一首
        queue.previous()  # 上一首
        queue.jump_to(5)  # 跳到第 5 首
    """
    
    def __init__(self):
        self._queue: List[Song] = []
        self._current_index: int = -1
        self._loop: bool = False
        self._lock = asyncio.Lock()
    
    # === 屬性 ===
    
    @property
    def loop(self) -> bool:
        """是否啟用循環播放"""
        return self._loop
    
    @loop.setter
    def loop(self, value: bool) -> None:
        self._loop = value
        logger.debug(f"循環模式: {'開啟' if value else '關閉'}")
    
    @property
    def is_empty(self) -> bool:
        """佇列是否為空"""
        return len(self._queue) == 0
    
    @property
    def size(self) -> int:
        """佇列中的歌曲數量"""
        return len(self._queue)
    
    @property
    def current_song(self) -> Optional[Song]:
        """當前播放的歌曲"""
        if self._current_index < 0 or self._current_index >= len(self._queue):
            return None
        return self._queue[self._current_index]
    
    @property
    def current(self) -> Optional[Song]:
        """current_song 的別名（為了相容性）"""
        return self.current_song
    
    @property
    def current_index(self) -> int:
        """
        當前播放的索引（0-based）
        """
        return self._current_index
    
    @property
    def current_index_one_based(self) -> int:
        """
        當前播放的索引（1-based，給使用者看的）
        
        如果沒有歌曲，返回 0
        """
        return self._current_index + 1 if self._current_index >= 0 else 0
    
    @property
    def current_index_zero_based(self) -> int:
        """當前播放的索引（0-based，給程式用的）"""
        return self._current_index
    
    @property
    def all_songs(self) -> List[Song]:
        """取得所有歌曲（只讀）"""
        return self._queue.copy()
    
    # === 新增/移除操作（全部異步，使用鎖保護）===
    
    async def add(self, song: Song) -> Song:
        """
        新增歌曲到佇列尾端
        
        Returns:
            新增的歌曲
        """
        async with self._lock:
            self._queue.append(song)
            
            # 如果是第一首，自動設定為當前
            if len(self._queue) == 1:
                self._current_index = 0
            
            logger.debug(f"已新增歌曲: {song.title}，目前共 {len(self._queue)} 首")
            return song
    
    async def add_many(self, songs: List[Song]) -> List[Song]:
        """
        批次新增歌曲
        
        Returns:
            成功新增的歌曲列表
        """
        async with self._lock:
            first_add = len(self._queue) == 0
            
            self._queue.extend(songs)
            
            # 如果之前是空的，設定第一首為當前
            if first_add and len(self._queue) > 0:
                self._current_index = 0
            
            logger.debug(f"批次新增 {len(songs)} 首歌曲，目前共 {len(self._queue)} 首")
            return songs
    
    async def remove(self, song_id: str) -> Optional[Song]:
        """
        通過 ID 移除歌曲
        
        Args:
            song_id: 歌曲 ID
        
        Returns:
            被移除的歌曲，若找不到則返回 None
        """
        async with self._lock:
            for i, song in enumerate(self._queue):
                if song.id == song_id:
                    removed = self._queue.pop(i)
                    
                    # 調整 current_index
                    if len(self._queue) == 0:
                        self._current_index = -1
                    elif i < self._current_index:
                        self._current_index -= 1
                    elif i == self._current_index:
                        if self._current_index >= len(self._queue):
                            self._current_index = len(self._queue) - 1
                    
                    logger.debug(f"已移除歌曲: {removed.title}")
                    return removed
            
            return None
    
    async def remove_by_index(self, index: int) -> Optional[Song]:
        """
        移除指定編號的歌曲
        
        Args:
            index: 1-based 索引（使用者輸入的編號）
        
        Returns:
            被移除的歌曲，若索引無效則返回 None
        """
        async with self._lock:
            pos = index - 1  # 轉換為 0-based
            
            if pos < 0 or pos >= len(self._queue):
                return None
            
            removed = self._queue.pop(pos)
            
            # 調整 current_index
            if len(self._queue) == 0:
                self._current_index = -1
            elif pos < self._current_index:
                # 移除的在當前之前，索引減 1
                self._current_index -= 1
            elif pos == self._current_index:
                # 移除的是當前歌曲
                if self._current_index >= len(self._queue):
                    self._current_index = len(self._queue) - 1
            
            logger.debug(f"已移除歌曲: {removed.title}")
            return removed
    
    async def clear(self) -> int:
        """
        清空佇列
        
        Returns:
            被清空的歌曲數量
        """
        async with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self._current_index = -1
            logger.debug(f"已清空播放佇列，共移除 {count} 首歌曲")
            return count
    
    # === 導航操作 ===
    
    def next(self) -> Optional[Song]:
        """
        切換到下一首
        
        循環模式：最後一首 → 第一首
        非循環模式：最後一首 → None
        
        Returns:
            下一首歌曲，若無則返回 None
        """
        if len(self._queue) == 0:
            return None
        
        if self._loop:
            # 循環模式：永遠有下一首
            self._current_index = (self._current_index + 1) % len(self._queue)
        else:
            # 非循環模式：到底就停
            if self._current_index + 1 >= len(self._queue):
                return None
            self._current_index += 1
        
        logger.debug(f"下一首: {self.current_song.title if self.current_song else 'None'}")
        return self.current_song
    
    def previous(self) -> Optional[Song]:
        """
        切換到上一首
        
        循環模式：第一首 → 最後一首
        非循環模式：第一首 → None
        
        Returns:
            上一首歌曲，若無則返回 None
        """
        if len(self._queue) == 0:
            return None
        
        if self._loop:
            # 循環模式：永遠有上一首
            self._current_index = (self._current_index - 1) % len(self._queue)
        else:
            # 非循環模式：到頂就停
            if self._current_index <= 0:
                return None
            self._current_index -= 1
        
        logger.debug(f"上一首: {self.current_song.title if self.current_song else 'None'}")
        return self.current_song
    
    def jump_to(self, index: int) -> Optional[Song]:
        """
        跳轉到指定索引
        
        Args:
            index: 0-based 索引
        
        Returns:
            目標歌曲，若索引無效則返回 None
        """
        if index < 0 or index >= len(self._queue):
            logger.warning(f"跳轉失敗：無效的索引 {index}（共 {len(self._queue)} 首）")
            return None
        
        self._current_index = index
        logger.debug(f"跳轉到第 {index + 1} 首: {self.current_song.title}")
        return self.current_song
    
    def jump_to_one_based(self, index: int) -> Optional[Song]:
        """
        跳轉到指定編號（1-based）
        
        Args:
            index: 1-based 索引
        
        Returns:
            目標歌曲，若索引無效則返回 None
        """
        return self.jump_to(index - 1)
    
    # === 查詢操作 ===
    
    def has_next(self) -> bool:
        """是否有下一首可播放"""
        if len(self._queue) == 0:
            return False
        if self._loop:
            return len(self._queue) > 1
        return self._current_index + 1 < len(self._queue)
    
    def has_previous(self) -> bool:
        """是否有上一首可播放"""
        if len(self._queue) == 0:
            return False
        if self._loop:
            return len(self._queue) > 1
        return self._current_index > 0
    
    def get_song(self, index: int) -> Optional[Song]:
        """
        取得指定編號的歌曲
        
        Args:
            index: 1-based 索引
        
        Returns:
            歌曲，若索引無效則返回 None
        """
        pos = index - 1
        if pos < 0 or pos >= len(self._queue):
            return None
        return self._queue[pos]
    
    def get_upcoming(self, count: int = 3) -> List[Song]:
        """
        取得接下來要播放的歌曲
        
        Args:
            count: 要取得的數量
        
        Returns:
            接下來的歌曲列表（不含當前歌曲）
        """
        if len(self._queue) == 0 or self._current_index < 0:
            return []
        
        start = self._current_index + 1
        end = min(start + count, len(self._queue))
        
        return self._queue[start:end]
    
    def get_previous_songs(self, count: int = 2) -> List[Song]:
        """
        取得之前播放過的歌曲
        
        Args:
            count: 要取得的數量
        
        Returns:
            之前的歌曲列表（不含當前歌曲）
        """
        if len(self._queue) == 0 or self._current_index <= 0:
            return []
        
        start = max(0, self._current_index - count)
        end = self._current_index
        
        return self._queue[start:end]
    
    # === 分頁顯示 ===
    
    def get_page(self, page: int = 1, per_page: int = 5) -> dict:
        """
        取得分頁資料
        
        Args:
            page: 頁碼（1-based）
            per_page: 每頁數量
        
        Returns:
            dict 包含：
            - songs: 該頁的歌曲列表
            - current_page: 當前頁碼
            - total_pages: 總頁數
            - total_songs: 總歌曲數
            - current_index: 當前播放的編號（1-based）
        """
        total = len(self._queue)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            "songs": self._queue[start:end],
            "start_index": start + 1,  # 1-based
            "current_page": page,
            "total_pages": total_pages,
            "total_songs": total,
            "current_index": self._current_index + 1 if self._current_index >= 0 else 0
        }
    
    def __len__(self) -> int:
        """返回佇列中的歌曲數量"""
        return len(self._queue)
    
    def __iter__(self):
        """支援迭代"""
        return iter(self._queue)
    
    # === 內部方法 ===
    
    def _get_window_indices(self, behind: int = 2, ahead: int = 3) -> List[int]:
        """
        取得滑動窗口內的索引（給 CacheManager 用）
        
        Args:
            behind: 當前歌曲之前保留幾首
            ahead: 當前歌曲之後保留幾首
        
        Returns:
            0-based 索引列表
        """
        if self._current_index < 0:
            return []
        
        start = max(0, self._current_index - behind)
        end = min(len(self._queue), self._current_index + ahead + 1)
        
        return list(range(start, end))
