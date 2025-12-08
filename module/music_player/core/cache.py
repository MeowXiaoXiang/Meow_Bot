"""
滑動窗口快取管理器

策略：
- 保留當前歌曲前後 N 首的快取
- 自動刪除超出範圍的快取
- 背景預載下幾首歌曲
- 避免硬碟空間無限增長

範例（window_behind=2, window_ahead=3）：
    佇列：[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                      ↑ 當前第 5 首
    保留：[3, 4, 5, 6, 7, 8] 共 6 首快取
    刪除：[1, 2] 的快取（太舊）
    預載：[6, 7, 8]（如果還沒下載）
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Set, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from .queue import Song, MusicQueue


class CacheManager:
    """
    滑動窗口快取管理器
    
    使用方式：
        cache = CacheManager(cache_dir="./cache", window_behind=2, window_ahead=3)
        
        # 每次歌曲切換時呼叫
        await cache.on_song_change(queue.all_songs, queue.current_index_zero_based, downloader)
        
        # 檢查快取
        if cache.exists(song.id):
            path = cache.get_path(song.id)
    """
    
    def __init__(
        self,
        cache_dir: str,
        window_behind: int = 2,
        window_ahead: int = 3
    ):
        """
        初始化快取管理器
        
        Args:
            cache_dir: 快取目錄路徑
            window_behind: 當前歌曲之前保留幾首快取
            window_ahead: 當前歌曲之後保留幾首快取（同時也是預載數量）
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.window_behind = window_behind
        self.window_ahead = window_ahead
        
        # 預載任務追蹤
        self._preload_tasks: Dict[str, asyncio.Task] = {}
        
        # 當前保留的 song_id 集合（用於判斷是否應該刪除）
        self._keep_ids: Set[str] = set()
        
        logger.debug(
            f"CacheManager 初始化: cache_dir={cache_dir}, "
            f"window=[{window_behind}, {window_ahead}]"
        )
    
    # === 路徑與檢查 ===
    
    def get_path(self, song_id: str) -> Path:
        """
        取得歌曲快取的完整路徑
        
        Args:
            song_id: 歌曲 ID
        
        Returns:
            快取檔案路徑（.opus）
        """
        return self.cache_dir / f"{song_id}.opus"
    
    def exists(self, song_id: str) -> bool:
        """
        檢查歌曲快取是否存在
        
        Args:
            song_id: 歌曲 ID
        
        Returns:
            快取是否存在
        """
        return self.get_path(song_id).exists()
    
    def get(self, song_id: str) -> Optional[str]:
        """
        取得快取檔案路徑（如果存在）
        
        Args:
            song_id: 歌曲 ID
        
        Returns:
            快取路徑字串，若不存在則返回 None
        """
        path = self.get_path(song_id)
        if path.exists():
            return str(path)
        return None
    
    def put(self, song_id: str, file_path: str) -> None:
        """
        記錄快取（將檔案視為已快取）
        
        如果檔案不在快取目錄中，會嘗試移動或複製
        
        Args:
            song_id: 歌曲 ID
            file_path: 檔案路徑
        """
        target = self.get_path(song_id)
        source = Path(file_path)
        
        # 如果檔案已在正確位置，不需要做什麼
        if source == target:
            return
        
        # 如果目標已存在，直接返回
        if target.exists():
            return
        
        # 嘗試移動檔案
        try:
            if source.exists():
                source.rename(target)
                logger.debug(f"移動快取檔案: {song_id}")
        except Exception as e:
            logger.warning(f"無法移動快取檔案: {e}")
    
    def clear(self) -> int:
        """
        clear_all 的別名
        """
        return self.clear_all()
    
    def get_cache_size(self) -> int:
        """
        取得目前快取總大小（bytes）
        """
        total = 0
        for file in self.cache_dir.glob("*.opus"):
            try:
                total += file.stat().st_size
            except Exception:
                pass
        return total
    
    def get_cache_count(self) -> int:
        """
        取得目前快取檔案數量
        """
        return len(list(self.cache_dir.glob("*.opus")))
    
    # === 核心邏輯 ===
    
    async def on_song_change(
        self,
        queue: List["Song"],
        current_index: int,
        downloader  # YTDLPDownloader
    ) -> None:
        """
        歌曲切換時呼叫此方法
        
        會自動：
        1. 清理滑動窗口外的舊快取
        2. 背景預載接下來的歌曲
        
        Args:
            queue: 所有歌曲列表
            current_index: 當前歌曲索引（0-based）
            downloader: YTDLPDownloader 實例
        """
        if not queue or current_index < 0:
            return
        
        # 更新保留的 song_id 集合
        self._update_keep_ids(queue, current_index)
        
        # 清理舊快取
        await self._cleanup_old()
        
        # 預載新歌
        await self._preload_ahead(queue, current_index, downloader)
    
    def _update_keep_ids(self, queue: List["Song"], current_index: int) -> None:
        """
        更新應保留的 song_id 集合
        """
        keep_start = max(0, current_index - self.window_behind)
        keep_end = min(len(queue), current_index + self.window_ahead + 1)
        
        self._keep_ids = {queue[i].id for i in range(keep_start, keep_end)}
        
        logger.debug(
            f"快取窗口更新: 保留索引 [{keep_start}, {keep_end}), "
            f"共 {len(self._keep_ids)} 首"
        )
    
    async def _cleanup_old(self) -> None:
        """
        清理滑動窗口外的快取
        """
        deleted_count = 0
        
        for file in self.cache_dir.glob("*.opus"):
            song_id = file.stem
            
            # 如果不在保留集合中，刪除
            if song_id not in self._keep_ids:
                try:
                    file.unlink()
                    deleted_count += 1
                    logger.debug(f"刪除舊快取: {song_id}")
                except Exception as e:
                    logger.warning(f"刪除快取失敗: {song_id} - {e}")
        
        if deleted_count > 0:
            logger.debug(f"清理了 {deleted_count} 個舊快取")
    
    async def _preload_ahead(
        self,
        queue: List["Song"],
        current_index: int,
        downloader
    ) -> None:
        """
        背景預載接下來的歌曲
        """
        for offset in range(1, self.window_ahead + 1):
            next_index = current_index + offset
            
            # 超出佇列範圍就停止（預載不考慮循環）
            if next_index >= len(queue):
                break
            
            song = queue[next_index]
            
            # 已有快取，跳過
            if self.exists(song.id):
                continue
            
            # 已在預載中，跳過
            if song.id in self._preload_tasks:
                task = self._preload_tasks[song.id]
                if not task.done():
                    continue
            
            # 建立背景預載任務
            task = asyncio.create_task(
                self._preload_one(song, downloader),
                name=f"preload_{song.id}"
            )
            self._preload_tasks[song.id] = task
    
    async def _preload_one(self, song: "Song", downloader) -> None:
        """
        預載單首歌
        """
        try:
            logger.debug(f"背景預載開始: {song.title}")
            info, path = await downloader.download(song.url)
            
            if path:
                # 更新歌曲的快取路徑
                song.cached_path = str(path)
                logger.debug(f"背景預載完成: {song.title}")
            else:
                logger.warning(f"背景預載失敗（無檔案）: {song.title}")
                
        except asyncio.CancelledError:
            logger.debug(f"背景預載被取消: {song.title}")
            raise
        except Exception as e:
            logger.warning(f"背景預載失敗: {song.title} - {e}")
        finally:
            # 清理任務記錄
            self._preload_tasks.pop(song.id, None)
    
    # === 預載控制 ===
    
    def cancel_all_preloads(self) -> int:
        """
        取消所有預載任務
        
        Returns:
            被取消的任務數量
        """
        cancelled = 0
        for song_id, task in list(self._preload_tasks.items()):
            if not task.done():
                task.cancel()
                cancelled += 1
                logger.debug(f"取消預載: {song_id}")
        
        self._preload_tasks.clear()
        
        if cancelled > 0:
            logger.debug(f"取消了 {cancelled} 個預載任務")
        
        return cancelled
    
    def is_preloading(self, song_id: str) -> bool:
        """
        檢查歌曲是否正在預載
        """
        if song_id not in self._preload_tasks:
            return False
        return not self._preload_tasks[song_id].done()
    
    async def wait_for_preload(self, song_id: str, timeout: float = 30) -> bool:
        """
        等待特定歌曲的預載完成
        
        Args:
            song_id: 歌曲 ID
            timeout: 超時時間（秒）
        
        Returns:
            是否成功（超時或預載失敗返回 False）
        """
        if self.exists(song_id):
            return True
        
        if song_id not in self._preload_tasks:
            return False
        
        task = self._preload_tasks[song_id]
        
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            return self.exists(song_id)
        except asyncio.TimeoutError:
            logger.warning(f"等待預載超時: {song_id}")
            return False
        except Exception:
            return False
    
    # === 清理 ===
    
    # 需要清理的媒體檔案副檔名
    MEDIA_EXTENSIONS = {".opus", ".webm", ".m4a", ".mp3", ".mp4", ".wav", ".ogg", ".flac"}
    
    def clear_all(self) -> int:
        """
        清空所有快取（包括未完成轉換的原始檔）
        
        Returns:
            被刪除的檔案數量
        """
        # 先取消所有預載
        self.cancel_all_preloads()
        
        deleted = 0
        # 清理所有媒體檔案，不只是 .opus
        for file in self.cache_dir.iterdir():
            if file.is_file() and file.suffix.lower() in self.MEDIA_EXTENSIONS:
                try:
                    file.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"刪除快取失敗: {file} - {e}")
        
        self._keep_ids.clear()
        
        logger.debug(f"已清空所有快取，共刪除 {deleted} 個檔案")
        return deleted
    
    def cleanup(self) -> None:
        """
        清理資源（程式結束時呼叫）
        """
        self.cancel_all_preloads()
        # 注意：不刪除快取檔案，讓下次啟動時可以重用
    
    async def preload_window(
        self,
        queue: "MusicQueue",
        downloader,
    ) -> None:
        """
        預載滑動窗口內的歌曲（便利方法）
        
        直接從 MusicQueue 取得資訊來預載
        
        Args:
            queue: MusicQueue 實例
            downloader: YTDLPDownloader 實例
        """
        await self.on_song_change(
            queue=list(queue),
            current_index=queue.current_index,
            downloader=downloader,
        )
