"""
音樂播放器裝飾器

提供自動化功能：
- auto_refresh_ui: 操作完成後自動刷新 UI
- handle_errors: 統一錯誤處理
"""

from functools import wraps
from typing import Callable, TypeVar, ParamSpec
from loguru import logger

from .errors import MusicError

P = ParamSpec('P')
T = TypeVar('T')


def auto_refresh_ui(func: Callable[P, T]) -> Callable[P, T]:
    """
    裝飾器：任何操作完成後自動刷新播放器 UI
    
    套用後，方法執行完畢會自動呼叫 self._refresh_player_ui()
    
    使用方式：
        @auto_refresh_ui
        async def play(self):
            ...
            # 執行完畢後自動刷新 UI
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        try:
            result = await func(self, *args, **kwargs)
            
            # 嘗試刷新 UI（如果有這個方法）
            if hasattr(self, '_refresh_player_ui'):
                try:
                    await self._refresh_player_ui()
                except Exception as e:
                    logger.warning(f"刷新 UI 失敗: {e}")
            
            return result
            
        except MusicError as e:
            # 統一處理音樂錯誤
            if hasattr(self, '_handle_error'):
                await self._handle_error(e)
            raise
            
    return wrapper


def handle_errors(func: Callable[P, T]) -> Callable[P, T]:
    """
    裝飾器：統一處理錯誤並記錄
    
    使用方式：
        @handle_errors
        async def some_operation(self):
            # 任何 MusicError 會被捕捉並記錄
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except MusicError as e:
            logger.error(f"[{func.__name__}] 音樂錯誤: {e.message}")
            raise
        except Exception as e:
            logger.exception(f"[{func.__name__}] 未預期錯誤: {e}")
            raise
            
    return wrapper


def log_operation(operation_name: str = None):
    """
    裝飾器：記錄操作的開始和結束
    
    使用方式：
        @log_operation("播放歌曲")
        async def play(self, song):
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        name = operation_name or func.__name__
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.debug(f"開始: {name}")
            try:
                result = await func(*args, **kwargs)
                logger.debug(f"完成: {name}")
                return result
            except Exception as e:
                logger.error(f"失敗: {name} - {e}")
                raise
                
        return wrapper
    return decorator


def ensure_voice_connected(func: Callable[P, T]) -> Callable[P, T]:
    """
    裝飾器：確保已連接到語音頻道
    
    使用方式：
        @ensure_voice_connected
        async def play(self):
            # 保證此時已連接語音
            ...
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        from .errors import VoiceConnectionError
        
        # 檢查是否有 voice_client 屬性
        voice_client = getattr(self, 'voice_client', None)
        if voice_client is None:
            voice_client = getattr(self, '_voice_client', None)
        
        if voice_client is None or not voice_client.is_connected():
            raise VoiceConnectionError("未連接到語音頻道")
        
        return await func(self, *args, **kwargs)
        
    return wrapper


def cooldown(seconds: float = 1.0):
    """
    裝飾器：防止按鈕連點（冷卻時間）
    
    使用方式：
        @cooldown(seconds=0.5)
        async def on_button_click(self, interaction):
            ...
    """
    import time
    last_call = {}
    
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            now = time.time()
            key = id(self)
            
            if key in last_call and now - last_call[key] < seconds:
                logger.debug(f"冷卻中，忽略操作: {func.__name__}")
                return None
            
            last_call[key] = now
            return await func(self, *args, **kwargs)
            
        return wrapper
    return decorator
